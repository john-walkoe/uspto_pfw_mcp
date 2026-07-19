"""Search tools: applications + inventor, minimal/balanced/full variants
(audit F2 split from main.py)."""

from typing import Any, Dict, List, Optional

from fastmcp.server.apps import AppConfig

from ..api.enhanced_client import EnhancedPatentClient
from ..api.helpers import (
    create_error_response,
    escape_lucene_query_term,
    format_error_response,
    map_query_field_names,
)
from ..client_registry import _client
from ..config.field_manager import field_manager
from ..models.constants import SearchStrategy
from ..models.search_params import (
    InventorSearchParameters,
    ParameterValidationError,
    SearchParameters,
)
from ..shared.safe_logger import get_safe_logger
from ..util.error_handlers import mcp_error_handler
from ..app_uris import _SEARCH_URI

logger = get_safe_logger(__name__)


# Filter helper functions for readability
def _matches_art_unit(metadata: Dict, art_unit: Optional[str]) -> bool:
    """Check if metadata matches art unit filter"""
    if not art_unit:
        return True
    return str(metadata.get('groupArtUnitNumber', '')) == str(art_unit)


def _matches_examiner(metadata: Dict, examiner_name: Optional[str]) -> bool:
    """Check if metadata matches examiner name filter"""
    if not examiner_name:
        return True
    return examiner_name.lower() in metadata.get('examinerNameText', '').lower()


def _matches_applicant(metadata: Dict, applicant_name: Optional[str]) -> bool:
    """Check if metadata matches applicant name filter"""
    if not applicant_name:
        return True
    return applicant_name.lower() in metadata.get('firstApplicantName', '').lower()


def _matches_customer_number(metadata: Dict, customer_number: Optional[str]) -> bool:
    """Check if metadata matches customer number filter"""
    if not customer_number:
        return True
    return str(metadata.get('customerNumber', '')) == str(customer_number)


def _matches_status_code(metadata: Dict, status_code: Optional[str]) -> bool:
    """Check if metadata matches status code filter"""
    if not status_code:
        return True
    return str(metadata.get('applicationStatusCode', '')) == str(status_code)


def _matches_filing_date_range(
    metadata: Dict,
    filing_date_start: Optional[str],
    filing_date_end: Optional[str]
) -> bool:
    """Check if metadata matches filing date range filter"""
    if not filing_date_start and not filing_date_end:
        return True

    filing_date = metadata.get('filingDate', '')
    if not filing_date:
        return False  # Skip if no filing date and filter is specified

    if filing_date_start and filing_date < filing_date_start:
        return False
    if filing_date_end and filing_date > filing_date_end:
        return False

    return True


def _matches_grant_date_range(
    metadata: Dict,
    grant_date_start: Optional[str],
    grant_date_end: Optional[str]
) -> bool:
    """Check if metadata matches grant date range filter"""
    if not grant_date_start and not grant_date_end:
        return True

    grant_date = metadata.get('grantDate', '')
    if not grant_date:
        return False  # Skip if no grant date and filter is specified

    if grant_date_start and grant_date < grant_date_start:
        return False
    if grant_date_end and grant_date > grant_date_end:
        return False

    return True


# Helper functions using parameter object pattern
def _build_query_from_params(
    query: str = "",
    art_unit: Optional[str] = None,
    examiner_name: Optional[str] = None,
    applicant_name: Optional[str] = None,
    customer_number: Optional[str] = None,
    status_code: Optional[str] = None,
    filing_date_start: Optional[str] = None,
    filing_date_end: Optional[str] = None,
    grant_date_start: Optional[str] = None,
    grant_date_end: Optional[str] = None
) -> str:
    """
    Build Lucene query string from convenience parameters.

    Centralizes query building logic to eliminate duplication across
    search_applications, search_applications_minimal, and search_applications_balanced.

    This function applies field name mapping and escaping to build a complete
    Lucene query string from user-friendly convenience parameters.

    Args:
        query: Base query string (may include field:value syntax)
        art_unit: Art unit number filter
        examiner_name: Examiner name filter
        applicant_name: Applicant name filter
        customer_number: Customer number filter
        status_code: Application status code filter
        filing_date_start: Filing date range start (YYYY-MM-DD)
        filing_date_end: Filing date range end (YYYY-MM-DD)
        grant_date_start: Grant date range start (YYYY-MM-DD)
        grant_date_end: Grant date range end (YYYY-MM-DD)

    Returns:
        Final Lucene query string with all parts combined with AND

    Raises:
        ValidationError: If no search criteria provided
    """
    query_parts = []

    if query and query.strip():
        # Map user-friendly field names to API field names (e.g., patentNumber -> applicationMetaData.patentNumber)
        mapped_query = map_query_field_names(query.strip())
        # Then escape special characters in the VALUES
        escaped_query = escape_lucene_query_term(mapped_query)
        # No parentheses - API examples show queries without them
        query_parts.append(escaped_query)

    if art_unit:
        escaped_art_unit = escape_lucene_query_term(str(art_unit))
        query_parts.append(f"applicationMetaData.groupArtUnitNumber:{escaped_art_unit}")

    if examiner_name:
        escaped_examiner = escape_lucene_query_term(examiner_name)
        query_parts.append(f'applicationMetaData.examinerNameText:"{escaped_examiner}"')

    if applicant_name:
        escaped_applicant = escape_lucene_query_term(applicant_name)
        query_parts.append(f'applicationMetaData.firstApplicantName:"{escaped_applicant}"')

    if customer_number:
        escaped_customer = escape_lucene_query_term(str(customer_number))
        query_parts.append(f"applicationMetaData.customerNumber:{escaped_customer}")

    if status_code:
        escaped_status = escape_lucene_query_term(str(status_code))
        query_parts.append(f"applicationMetaData.applicationStatusCode:{escaped_status}")

    if filing_date_start or filing_date_end:
        # Dates are NOT escaped - they're in known format (YYYY-MM-DD) for structured range queries
        start = filing_date_start if filing_date_start else "*"
        end = filing_date_end if filing_date_end else "*"
        query_parts.append(f"applicationMetaData.filingDate:[{start} TO {end}]")

    if grant_date_start or grant_date_end:
        # Dates are NOT escaped - they're in known format (YYYY-MM-DD) for structured range queries
        start = grant_date_start if grant_date_start else "*"
        end = grant_date_end if grant_date_end else "*"
        query_parts.append(f"applicationMetaData.grantDate:[{start} TO {end}]")

    # Validate we have at least one search criterion
    if not query_parts:
        from ..exceptions import ValidationError
        raise ValidationError("Must provide either 'query' parameter or at least one convenience parameter")

    # Combine all query parts with AND
    return " AND ".join(query_parts)


async def _search_applications_with_params(params: SearchParameters) -> Dict[str, Any]:
    """
    Internal helper function using SearchParameters object

    This function implements the parameter object pattern to reduce
    the number of parameters in function signatures while maintaining
    full functionality.
    """
    try:
        api_client = _client()

        # Build query from convenience parameters using centralized helper
        final_query = _build_query_from_params(
            params.query, params.art_unit, params.examiner_name, params.applicant_name,
            params.customer_number, params.status_code, params.filing_date_start,
            params.filing_date_end, params.grant_date_start, params.grant_date_end
        )

        # Input validation
        if len(final_query) > EnhancedPatentClient.MAX_QUERY_LENGTH:
            return create_error_response("query_too_long",
                custom_message=f"Query too long (max {EnhancedPatentClient.MAX_QUERY_LENGTH} characters)")

        fields = params.fields
        if fields is None:
            fields = [
                "applicationNumberText",
                "applicationMetaData.inventionTitle",
                "applicationMetaData.filingDate",
                "applicationMetaData.patentNumber",
                "applicationMetaData.groupArtUnitNumber",
                "applicationMetaData.examinerNameText"
            ]

        result = await api_client.search_applications(final_query, params.limit, params.offset, fields)

        # Add query info metadata
        if result.get('success'):
            estimated_chars = len(str(result.get('applications', [])))
            result['context_info'] = {
                'fields_used': fields,
                'estimated_response_size_chars': estimated_chars
            }
            result['query_info'] = {
                'constructed_query': final_query,
                'convenience_parameters_used': {
                    'art_unit': params.art_unit,
                    'examiner_name': params.examiner_name,
                    'applicant_name': params.applicant_name,
                    'customer_number': params.customer_number,
                    'status_code': params.status_code,
                    'filing_date_range': f"{params.filing_date_start or '*'} to {params.filing_date_end or '*'}",
                    'grant_date_range': f"{params.grant_date_start or '*'} to {params.grant_date_end or '*'}"
                },
                'search_tier': 'full (custom fields)',
                'recommendation': 'Consider using pfw_search_applications_minimal for token efficiency'
            }

        return result
    except Exception as e:
        return format_error_response(f"Search failed: {str(e)}")


async def _search_inventor_with_params(params: InventorSearchParameters) -> Dict[str, Any]:
    """
    Internal helper function using InventorSearchParameters object

    This function implements the parameter object pattern for inventor searches.
    """
    try:
        fields = params.fields
        if fields is None:
            fields = [
                "applicationNumberText",
                "applicationMetaData.inventionTitle",
                "applicationMetaData.filingDate",
                "applicationMetaData.patentNumber",
                "applicationMetaData.inventorBag.inventorNameText",
                "applicationMetaData.firstInventorName"
            ]

        result = await _client().search_inventor(params.name, params.strategy, params.limit, fields)

        # Add search info metadata
        if result.get('success'):
            estimated_chars = len(str(result.get('applications', [])))
            result['context_info'] = {
                'fields_used': fields,
                'estimated_response_size_chars': estimated_chars
            }

        return result
    except Exception as e:
        return format_error_response(f"Inventor search failed: {str(e)}")



def register(mcp) -> None:
    """Register the six search tools."""
    @mcp.tool(name="search_applications", app=AppConfig(resource_uri=_SEARCH_URI), annotations={"defer_loading": True, "readOnlyHint": True})
    @mcp_error_handler
    async def pfw_search_applications(
        query: str = "",
        limit: int = 10,
        offset: int = 0,
        fields: Optional[List[str]] = None,
        # NEW: Convenience parameters for attorney-friendly searches
        art_unit: Optional[str] = None,
        examiner_name: Optional[str] = None,
        applicant_name: Optional[str] = None,
        customer_number: Optional[str] = None,
        status_code: Optional[str] = None,
        filing_date_start: Optional[str] = None,
        filing_date_end: Optional[str] = None,
        grant_date_start: Optional[str] = None,
        grant_date_end: Optional[str] = None
    ) -> Dict[str, Any]:
        """Full-featured search with all convenience parameters and custom field selection.

    **RECOMMENDATION: Use pfw_search_applications_minimal instead for most searches (95-99% token reduction).**
    This tool provides all search capabilities including convenience parameters and custom field selection.

    **Convenience parameters - see pfw_search_applications_minimal for details:**
    - `art_unit`, `examiner_name`, `applicant_name`, `customer_number`, `status_code`, `filing_date_start/end`, `grant_date_start/end`

    **Examples:**
    ```python
    # Art unit search with custom fields
    pfw_search_applications(art_unit='2128', fields=['applicationNumberText', 'inventionTitle'], limit=50)

    # Hybrid: keywords + convenience + custom fields
    pfw_search_applications(query='artificial intelligence', art_unit='2128', fields=['applicationNumberText', 'patentNumber', 'inventionTitle'], limit=50)
    ```

    For complex search strategies and cross-MCP workflows, use pfw_get_guidance (see quick reference chart for section selection)."""

        # Create SearchParameters object and delegate to helper function
        try:
            params = SearchParameters(
                query=query,
                limit=limit,
                offset=offset,
                fields=fields,
                art_unit=art_unit,
                examiner_name=examiner_name,
                applicant_name=applicant_name,
                customer_number=customer_number,
                status_code=status_code,
                filing_date_start=filing_date_start,
                filing_date_end=filing_date_end,
                grant_date_start=grant_date_start,
                grant_date_end=grant_date_end
            )
            return await _search_applications_with_params(params)
        except ParameterValidationError as e:
            # Typed field mapping (audit F24 — no more substring-matching the
            # exception text, which misfiled e.g. "rate limit exceeded")
            template = {"limit": "invalid_limit", "offset": "invalid_offset"}.get(e.field, "empty_query")
            return create_error_response(template, custom_message=str(e))
        except Exception as e:
            return format_error_response(f"Search failed: {str(e)}", error_type="search_error")


    @mcp.tool(name="search_inventor", app=AppConfig(resource_uri=_SEARCH_URI), annotations={"defer_loading": True, "readOnlyHint": True})
    @mcp_error_handler
    async def pfw_search_inventor(
        name: str,
        strategy: str = "comprehensive",
        limit: int = 10,
        fields: Optional[List[str]] = None,
        # NEW: Convenience parameters for attorney-friendly searches
        art_unit: Optional[str] = None,
        examiner_name: Optional[str] = None,
        applicant_name: Optional[str] = None,
        customer_number: Optional[str] = None,
        status_code: Optional[str] = None,
        filing_date_start: Optional[str] = None,
        filing_date_end: Optional[str] = None,
        grant_date_start: Optional[str] = None,
        grant_date_end: Optional[str] = None
    ) -> Dict[str, Any]:
        """Custom field selection inventor search for power users who need non-preset field combinations.

    **RECOMMENDATION: Use pfw_search_inventor_minimal instead for most searches (95-99% token reduction).**

    Supports exact, fuzzy, and comprehensive name matching strategies. Returns customizable field sets.

    **Convenience parameters - see pfw_search_inventor_minimal for details:**
    - `art_unit`, `examiner_name`, `applicant_name`, `customer_number`, `status_code`, `filing_date_start/end`, `grant_date_start/end`

    **Examples:**
    ```python
    # Inventor in specific art unit with custom fields
    pfw_search_inventor(name='Smith', art_unit='2128', fields=['applicationNumberText', 'inventionTitle'], limit=50)

    # Inventor's granted patents only with specific fields
    pfw_search_inventor(name='John Smith', status_code='150', fields=['applicationNumberText', 'patentNumber'], limit=20)
    ```

    For advanced inventor analysis and cross-MCP workflows, use pfw_get_guidance (see quick reference chart for section selection)."""
        try:
            # Input validation
            if not name or len(name.strip()) == 0:
                return format_error_response("Inventor name cannot be empty", 400)
            if len(name) > EnhancedPatentClient.MAX_NAME_LENGTH:
                return format_error_response(f"Inventor name too long (max {EnhancedPatentClient.MAX_NAME_LENGTH} characters)", 400)
            if not SearchStrategy.is_valid(strategy):
                return format_error_response(f"Strategy must be one of: {', '.join(SearchStrategy.all())}", 400)
            if limit < 1 or limit > EnhancedPatentClient.MAX_SEARCH_LIMIT:
                return format_error_response(f"Limit must be between 1 and {EnhancedPatentClient.MAX_SEARCH_LIMIT}", 400)

            if fields is None:
                fields = ["applicationNumberText", "applicationMetaData.inventionTitle",
                         "applicationMetaData.filingDate", "applicationMetaData.patentNumber",
                         "applicationMetaData.groupArtUnitNumber", "applicationMetaData.examinerNameText"]

            # Get base inventor search results
            result = await _client().search_inventor(name, strategy, limit, fields)

            # Apply convenience parameter filtering if any are specified
            if result.get('success') and result.get('unique_applications') and any([
                art_unit, examiner_name, applicant_name, customer_number, status_code,
                filing_date_start, filing_date_end, grant_date_start, grant_date_end
            ]):
                # Filter the results based on convenience parameters
                original_count = len(result['unique_applications'])
                filtered_apps = []

                for app in result['unique_applications']:
                    # Get metadata for comparison
                    metadata = app.get('applicationMetaData', {})

                    # Check each filter condition using helper functions for readability
                    if not _matches_art_unit(metadata, art_unit):
                        continue
                    if not _matches_examiner(metadata, examiner_name):
                        continue
                    if not _matches_applicant(metadata, applicant_name):
                        continue
                    if not _matches_customer_number(metadata, customer_number):
                        continue
                    if not _matches_status_code(metadata, status_code):
                        continue
                    if not _matches_filing_date_range(metadata, filing_date_start, filing_date_end):
                        continue
                    if not _matches_grant_date_range(metadata, grant_date_start, grant_date_end):
                        continue

                    # Passed all filters
                    filtered_apps.append(app)

                # Update result with filtered applications
                result['unique_applications'] = filtered_apps
                result['total_unique_applications'] = len(filtered_apps)
                result['query_info'] = {
                    'inventor_search': name,
                    'strategy': strategy,
                    'convenience_filters_applied': {
                        'art_unit': art_unit,
                        'examiner_name': examiner_name,
                        'applicant_name': applicant_name,
                        'customer_number': customer_number,
                        'status_code': status_code,
                        'filing_date_range': f"{filing_date_start or '*'} to {filing_date_end or '*'}",
                        'grant_date_range': f"{grant_date_start or '*'} to {grant_date_end or '*'}"
                    },
                    'filtering_method': 'Post-search filtering on returned results',
                    'results_before_filter': original_count,
                    'results_after_filter': len(filtered_apps)
                }

            return result
        except Exception as e:
            return format_error_response(f"Inventor search failed: {str(e)}")


    @mcp.tool(name="search_applications_minimal", app=AppConfig(resource_uri=_SEARCH_URI), annotations={"defer_loading": False, "readOnlyHint": True})
    @mcp_error_handler
    async def pfw_search_applications_minimal(
        query: str = "",
        limit: int = 10,
        offset: int = 0,
        fields: Optional[List[str]] = None,
        # NEW: Convenience parameters for attorney-friendly searches
        art_unit: Optional[str] = None,
        examiner_name: Optional[str] = None,
        applicant_name: Optional[str] = None,
        customer_number: Optional[str] = None,
        status_code: Optional[str] = None,
        filing_date_start: Optional[str] = None,
        filing_date_end: Optional[str] = None,
        grant_date_start: Optional[str] = None,
        grant_date_end: Optional[str] = None
    ) -> Dict[str, Any]:
        """Ultra-fast discovery search returning only essential fields (95-99% context reduction).

    **RECOMMENDED: Use this tool first with convenience parameters for high-volume discovery.**

    Use for high-volume discovery (20-50 results) when exploring broad topics or finding
    applications to analyze in detail later. Default returns 15 core fields from field_configs.yaml:
    application number, title, inventors, applicant, USPTO and Cooperative Patent Classifications, patent number, parent
    patents, XML metadata (for use with pfw_get_patent_or_application_xml), art unit, examiner name, filing/grant dates, customer number, status.

    **NEW: Custom Fields Override (Ultra-Minimal Mode - 99% reduction)**
    Use for high-volume discovery (50-200 results) when exploring broad topics or finding
    applications to analyze in detail later.
    - `fields`: Optional list of specific fields to return (e.g., ['applicationNumberText', 'examinerNameText'])
    - If provided: Returns ONLY those fields (ultra-minimal, 2-3 fields for maximum token efficiency)

    **Convenience parameters for attorney-friendly searches:**
    - `art_unit`: Search by art unit (e.g., '2128', '3600')
    - `examiner_name`: Search by examiner (e.g., 'SMITH, EMILIE ALINE')
    - `applicant_name`: Search by applicant/assignee (e.g., 'Apple Inc.')
    - `customer_number`: Search by customer number (e.g., '26285')
    - `status_code`: Search by status (e.g., '150' = granted)
    - `filing_date_start/end`: Filing date range (YYYY-MM-DD)
    - `grant_date_start/end`: Grant date range (YYYY-MM-DD)

    **Examples:**
    ```python
    # Examiner portfolio analysis (preset 15 fields)
    pfw_search_applications_minimal(examiner_name='SMITH, EMILIE ALINE', limit=20)

    # Ultra-minimal: only 2 specific fields for citation analysis (50-200 results)
    pfw_search_applications_minimal(
        examiner_name='SMITH, EMILIE ALINE',
        fields=['applicationNumberText', 'examinerNameText'],
        limit=100
    )

    # Hybrid: keywords + convenience + custom fields (ultra-minimal mode)
    pfw_search_applications_minimal(
        query='artificial intelligence',
        art_unit='2128',
        status_code='150',
        fields=['applicationNumberText', 'inventionTitle', 'patentNumber'],
        limit=150
    )
    ```

    **Progressive Disclosure Workflow:**
    1. Use THIS TOOL for discovery with convenience params (20-50 results or Ultra-Minimal Mode 50-200 results)
    2. Present top results to user for selection
    3. Use pfw_search_applications_balanced for detailed analysis (10-20 selected)
    4. Use pfw_get_application_documents for document access (1-5 applications)

    For complex workflows and cross-MCP integration, use pfw_get_guidance (see quick reference chart for section selection)."""
        try:
            # Build query from convenience parameters using centralized helper
            final_query = _build_query_from_params(
                query, art_unit, examiner_name, applicant_name, customer_number,
                status_code, filing_date_start, filing_date_end, grant_date_start, grant_date_end
            )

            # Input validation
            if len(final_query) > EnhancedPatentClient.MAX_QUERY_LENGTH:
                return create_error_response("query_too_long",
                    custom_message=f"Query too long (max {EnhancedPatentClient.MAX_QUERY_LENGTH} characters)")
            if limit < 1 or limit > EnhancedPatentClient.MAX_SEARCH_LIMIT:
                return format_error_response(
                    f"Limit must be between 1 and {EnhancedPatentClient.MAX_SEARCH_LIMIT}",
                    400
                )
            if offset < 0:
                return format_error_response("Offset must be non-negative", 400)

            # Get field set: use custom fields if provided, otherwise use preset minimal fields
            use_fields = fields if fields is not None else field_manager.get_field_set("applications_minimal")

            # Execute search
            search_results = await pfw_search_applications(
                query=final_query,
                limit=limit,
                offset=offset,
                fields=use_fields
            )

            # Enhance with associated documents if in field set
            if "associatedDocuments" in use_fields and search_results.get("success"):
                enhanced_results = await _client().enhance_search_results_with_associated_docs(search_results)
            else:
                enhanced_results = search_results

            # Add query metadata for transparency
            if enhanced_results.get('success'):
                enhanced_results['query_info'] = {
                    'constructed_query': final_query,
                    'requested_fields': fields,
                    'convenience_parameters_used': {
                        'art_unit': art_unit,
                        'examiner_name': examiner_name,
                        'applicant_name': applicant_name,
                        'customer_number': customer_number,
                        'status_code': status_code,
                        'filing_date_range': f"{filing_date_start or '*'} to {filing_date_end or '*'}",
                        'grant_date_range': f"{grant_date_start or '*'} to {grant_date_end or '*'}"
                    },
                    'search_tier': 'minimal',
                    'recommended_workflow': {
                        'full_analysis': 'minimal → pfw_get_patent_or_application_xml',
                        'claims_analysis': 'minimal → get_application_documents(document_code=CLM) → PFW_get_document_content_with_ocr (both initial and final claims)',
                        'office_action_analysis': 'minimal → get_application_documents(document_code=CTFR|CTNF) → PFW_get_document_content_with_ocr',
                        'examiner_citations': 'minimal → get_application_documents(document_code=892) → PFW_get_document_content_with_ocr',
                        'applicant_citations': 'minimal → get_application_documents(document_code=IDS|1449) → PFW_get_document_content_with_ocr (for Citations MCP)',
                        'noa_analysis': 'minimal → get_application_documents(document_code=NOA) → PFW_get_document_content_with_ocr',
                        'user_downloads': 'minimal → get_application_documents(document_code=NOA|CTFR) → get_document_download OR get_granted_patent_documents_download',
                        'cross_mcp': 'minimal → balanced → PTAB/FPD/Citations MCPs'
                    }
                }

            return enhanced_results

        except Exception as e:
            return format_error_response(f"Minimal search failed: {str(e)}")

    @mcp.tool(name="search_applications_balanced", app=AppConfig(resource_uri=_SEARCH_URI), annotations={"defer_loading": True, "readOnlyHint": True})
    @mcp_error_handler
    async def pfw_search_applications_balanced(
        query: str = "",
        limit: int = 10,
        offset: int = 0,
        fields: Optional[List[str]] = None,
        # NEW: Convenience parameters for attorney-friendly searches
        art_unit: Optional[str] = None,
        examiner_name: Optional[str] = None,
        applicant_name: Optional[str] = None,
        customer_number: Optional[str] = None,
        status_code: Optional[str] = None,
        filing_date_start: Optional[str] = None,
        filing_date_end: Optional[str] = None,
        grant_date_start: Optional[str] = None,
        grant_date_end: Optional[str] = None
    ) -> Dict[str, Any]:
        """Balanced search returning 18 key fields for detailed analysis (85-95% context reduction).

    **Use after minimal search for analyzing selected applications (10-20 results).**

    Returns 18 key fields including all minimal fields plus applicantBag, assignmentBag,
    and application status description for detailed analysis.

    **NEW: Custom Fields Override - same as minimal tier**
    - `fields`: Optional list of specific fields to return.

    **Convenience parameters - same as minimal tier:**
    - `art_unit`, `examiner_name`, `applicant_name`, etc.

    **Typical Workflow:**
    1. Discovery: pfw_search_applications_minimal(art_unit='2128', limit=100, fields=["applicationNumberText", "inventionTitle", "groupArtUnitNumber"])
    2. User selects 10 interesting applications
    3. Optional Get additional fields: pfw_search_applications_balanced(query='applicationNumberText:X OR ...', limit=10)
    4. Analysis - Use cross-reference fields for other USPTO MCP integrations or pfw_get_patent_or_application_xml to pull the text of the application or patent into context for Analysis

    For complex workflows and cross-MCP integration, use pfw_get_guidance (see quick reference chart for section selection)."""
        try:
            # Build query from convenience parameters using centralized helper
            final_query = _build_query_from_params(
                query, art_unit, examiner_name, applicant_name, customer_number,
                status_code, filing_date_start, filing_date_end, grant_date_start, grant_date_end
            )

            # Validation (same as minimal)
            if len(final_query) > EnhancedPatentClient.MAX_QUERY_LENGTH:
                return format_error_response(
                    f"Query too long (max {EnhancedPatentClient.MAX_QUERY_LENGTH} characters)",
                    400
                )
            if limit < 1 or limit > EnhancedPatentClient.MAX_SEARCH_LIMIT:
                return format_error_response(
                    f"Limit must be between 1 and {EnhancedPatentClient.MAX_SEARCH_LIMIT}",
                    400
                )

            # Get field set: use custom fields if provided, otherwise use preset balanced fields
            use_fields = fields if fields is not None else field_manager.get_field_set("applications_balanced")

            # Execute search
            search_results = await pfw_search_applications(
                query=final_query,
                limit=limit,
                offset=offset,
                fields=use_fields
            )

            # Enhance with associated documents
            if search_results.get("success"):
                enhanced_results = await _client().enhance_search_results_with_associated_docs(search_results)

                # Add metadata
                enhanced_results["documentBagsIncluded"] = False
                enhanced_results["prosecutionDocsGuidance"] = {
                    "access_method": "Use pfw_get_application_documents(applicationNumberText) for prosecution documents",
                    "optimization": "DocumentBag removed to prevent token explosion",
                    "workflow": "Discovery → Analysis (you are here) → Documents (targeted access)"
                }

                # Add query info
                enhanced_results['query_info'] = {
                    'constructed_query': final_query,
                    'requested_fields': fields,
                    'convenience_parameters_used': {
                        'art_unit': art_unit,
                        'examiner_name': examiner_name,
                        'applicant_name': applicant_name,
                        'customer_number': customer_number,
                        'status_code': status_code
                    },
                    'search_tier': 'balanced'
                }

                return enhanced_results
            else:
                return search_results

        except Exception as e:
            return format_error_response(f"Balanced search failed: {str(e)}")

    @mcp.tool(name="search_inventor_minimal", app=AppConfig(resource_uri=_SEARCH_URI), annotations={"defer_loading": True, "readOnlyHint": True})
    @mcp_error_handler
    async def pfw_search_inventor_minimal(
        name: str,
        strategy: str = "comprehensive",
        limit: int = 10,
        fields: Optional[List[str]] = None,
        # NEW: Convenience parameters for attorney-friendly searches
        art_unit: Optional[str] = None,
        examiner_name: Optional[str] = None,
        applicant_name: Optional[str] = None,
        customer_number: Optional[str] = None,
        status_code: Optional[str] = None,
        filing_date_start: Optional[str] = None,
        filing_date_end: Optional[str] = None,
        grant_date_start: Optional[str] = None,
        grant_date_end: Optional[str] = None
    ) -> Dict[str, Any]:
        """Ultra-fast inventor search returning only essential fields (95-99% context reduction).

    **RECOMMENDED: Use this tool first with convenience parameters for high-volume inventor discovery.**

    Use for high-volume inventor discovery (20-50 results) when exploring inventor portfolios
    or finding applications to analyze in detail later. Default returns 15 core fields per application
    from field_configs.yaml: application number, title, inventors, applicant, USPTO and Cooperative Patent Classifications,
    patent number, parent patents, XML metadata (for use with pfw_get_patent_or_application_xml), art unit, examiner name, filing/grant dates,
    customer number, status.

    **NEW: Custom Fields Override (Ultra-Minimal Mode - 99% reduction)**
    Use for very high-volume inventor discovery (50-200 results) when you need targeted field extraction.
    - `fields`: Optional list of specific fields to return (e.g., ['applicationNumberText', 'examinerNameText'])
    - If provided: Returns ONLY those fields (ultra-minimal, 2-3 fields for maximum token efficiency)

    **Convenience parameters for filtering:**
    - `art_unit`: Filter by art unit (e.g., '2128', '3600')
    - `examiner_name`: Filter by examiner (e.g., 'SMITH, EMILIE ALINE')
    - `applicant_name`: Filter by applicant/assignee (e.g., 'Apple Inc.')
    - `customer_number`: Filter by customer number (e.g., '26285')
    - `status_code`: Filter by status (e.g., '150' = granted)
    - `filing_date_start/end`: Filing date range (YYYY-MM-DD)
    - `grant_date_start/end`: Grant date range (YYYY-MM-DD)

    **Examples:**
    ```python
    # Inventor's granted patents only (preset 15 fields)
    pfw_search_inventor_minimal(name='John Smith', status_code='150', limit=20)

    # Ultra-minimal: only 2 specific fields for portfolio analysis (50-200 results)
    pfw_search_inventor_minimal(
        name='Smith',
        fields=['applicationNumberText', 'examinerNameText'],
        limit=100
    )

    # Hybrid: inventor + convenience + custom fields (ultra-minimal mode)
    pfw_search_inventor_minimal(
        name='Smith',
        art_unit='2128',
        status_code='150',
        fields=['applicationNumberText', 'inventionTitle', 'patentNumber'],
        limit=150
    )
    ```

    **Progressive Disclosure Workflow:**
    1. Use THIS TOOL for inventor discovery with convenience params (20-50 results or Ultra-Minimal Mode 50-200 results)
    2. Present top results to user for selection
    3. Use pfw_search_inventor_balanced for detailed analysis (10-20 selected)
    4. Use pfw_get_application_documents for document access (1-5 applications)

    For advanced inventor research workflows, use pfw_get_guidance (see quick reference chart for section selection)."""
        try:
            # Get field set: use custom fields if provided, otherwise use preset inventor_minimal fields
            use_fields = fields if fields is not None else field_manager.get_field_set("inventor_minimal")

            # Get basic search results
            search_results = await pfw_search_inventor(
                name=name,
                strategy=strategy,
                limit=limit,
                fields=use_fields,
                art_unit=art_unit,
                examiner_name=examiner_name,
                applicant_name=applicant_name,
                customer_number=customer_number,
                status_code=status_code,
                filing_date_start=filing_date_start,
                filing_date_end=filing_date_end,
                grant_date_start=grant_date_start,
                grant_date_end=grant_date_end
            )

            # If associatedDocuments field is requested, enhance results with associated documents
            if "associatedDocuments" in use_fields:
                # For inventor searches, we need to enhance unique_applications if they exist
                if "unique_applications" in search_results and search_results["unique_applications"]:
                    # Create a temporary structure that looks like application search results
                    temp_results = {
                        "success": True,  # Required by enhancement function
                        "applications": search_results["unique_applications"],
                        "recordTotalQuantity": len(search_results["unique_applications"])
                    }

                    # Enhance with associated documents
                    enhanced_temp = await _client().enhance_search_results_with_associated_docs(temp_results)

                    # Merge back into original inventor search format
                    search_results["unique_applications"] = enhanced_temp.get("applications", [])
                    search_results["associatedDocumentsIncluded"] = enhanced_temp.get("associatedDocumentsIncluded", False)
                    search_results["llmGuidance"] = enhanced_temp.get("llmGuidance", {})

            # Add search tier metadata and context info
            if search_results.get('success'):
                # Add context_info with fields used
                estimated_chars = len(str(search_results.get('unique_applications', [])))
                search_results['context_info'] = {
                    'fields_used': use_fields,
                    'estimated_response_size_chars': estimated_chars
                }

                # Add query_info
                if 'query_info' not in search_results:
                    search_results['query_info'] = {}
                search_results['query_info']['search_tier'] = 'inventor_minimal'

            return search_results

        except Exception as e:
            return format_error_response(f"Minimal inventor search failed: {str(e)}")

    @mcp.tool(name="search_inventor_balanced", app=AppConfig(resource_uri=_SEARCH_URI), annotations={"defer_loading": True, "readOnlyHint": True})
    @mcp_error_handler
    async def pfw_search_inventor_balanced(
        name: str,
        strategy: str = "comprehensive",
        limit: int = 10,
        fields: Optional[List[str]] = None,
        # NEW: Convenience parameters for attorney-friendly searches
        art_unit: Optional[str] = None,
        examiner_name: Optional[str] = None,
        applicant_name: Optional[str] = None,
        customer_number: Optional[str] = None,
        status_code: Optional[str] = None,
        filing_date_start: Optional[str] = None,
        filing_date_end: Optional[str] = None,
        grant_date_start: Optional[str] = None,
        grant_date_end: Optional[str] = None
    ) -> Dict[str, Any]:
        """Balanced inventor search returning 18 key fields per application (85-95% context reduction).

    **Use for detailed inventor portfolio analysis after minimal search.**

    Returns 18 key fields including all minimal fields plus applicantBag, assignmentBag, and application
    status description for detailed portfolio analysis.

    **NEW: Custom Fields Override - same as minimal tier**
    - `fields`: Optional list of specific fields to return.

    **Convenience parameters - same as minimal tier:**
    - `art_unit`, `examiner_name`, `applicant_name`, etc.

    **Typical Workflow:**
    1. Discovery: pfw_search_inventor_minimal(name='John Smith', limit=50, fields=["applicationNumberText", "inventionTitle"])
    2. User selects 10 interesting applications
    3. Optional Get additional fields: pfw_search_inventor_balanced(name='John Smith', limit=10)
    4. Analysis - Use cross-reference fields for other USPTO MCP integrations or pfw_get_patent_or_application_xml to pull the text of the application or patent into context for Analysis

    For complex workflows and cross-MCP integration, use pfw_get_guidance (see quick reference chart for section selection)."""
        try:
            # Get field set: use custom fields if provided, otherwise use preset inventor_balanced fields
            use_fields = fields if fields is not None else field_manager.get_field_set("inventor_balanced")

            # First get regular search results
            search_results = await pfw_search_inventor(
                name=name,
                strategy=strategy,
                limit=limit,
                fields=use_fields,
                art_unit=art_unit,
                examiner_name=examiner_name,
                applicant_name=applicant_name,
                customer_number=customer_number,
                status_code=status_code,
                filing_date_start=filing_date_start,
                filing_date_end=filing_date_end,
                grant_date_start=grant_date_start,
                grant_date_end=grant_date_end
            )

            # Enhance with BOTH document bags AND associated documents if we have applications
            if search_results.get("success") and search_results.get("unique_applications"):
                # Convert to the format expected by enhance methods
                temp_results = {
                    "success": True,
                    "applications": search_results["unique_applications"]
                }

                # Session 4 Change: Remove document bag enhancement to prevent token explosion
                # Use pfw_get_application_documents for targeted document access instead

                # Add associated documents (XML files for content analysis)
                enhanced_temp = await _client().enhance_search_results_with_associated_docs(temp_results)

                # Merge back into original inventor search format
                search_results["unique_applications"] = enhanced_temp.get("applications", [])
                search_results["associatedDocumentsIncluded"] = enhanced_temp.get("associatedDocumentsIncluded", False)
                search_results["llmGuidance"] = enhanced_temp.get("llmGuidance", {})

            # Add search tier metadata and context info
            if search_results.get('success'):
                # Add context_info with fields used
                estimated_chars = len(str(search_results.get('unique_applications', [])))
                search_results['context_info'] = {
                    'fields_used': use_fields,
                    'estimated_response_size_chars': estimated_chars
                }

                # Add query_info
                if 'query_info' not in search_results:
                    search_results['query_info'] = {}
                search_results['query_info']['search_tier'] = 'inventor_balanced'

            return search_results

        except Exception as e:
            return format_error_response(f"Enhanced inventor balanced search failed: {str(e)}")

