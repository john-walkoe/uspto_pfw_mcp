"""Enhanced Patent File Wrapper MCP Server with Fields Parameter Support"""

import asyncio
import logging
import os
import sys
import threading
from typing import Dict, List, Any, Optional, Union
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent, PromptMessage, Resource
from .api.enhanced_client import EnhancedPatentClient
from .api.helpers import validate_app_number, format_error_response, escape_lucene_query_term, create_error_response, map_query_field_names
from .config.field_manager import field_manager
# Removed: from .config.tool_reflections import get_all_tool_reflections, get_tool_reflection
# These functions have been migrated to pfw_get_guidance() for context efficiency
from .models.search_params import SearchParameters, InventorSearchParameters
from .util.identifier_normalization import normalize_identifier, resolve_identifier_to_application_number, create_identifier_guidance
from .util.package_manager import PackageManager, get_claim_evolution, format_package_summary
from .models.constants import DocumentDirection, IdentifierType, SearchStrategy
from .util.input_processing import process_identifier_inputs, format_input_guidance, create_fuzzy_search_strategy

logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler(sys.stderr)])
logger = logging.getLogger(__name__)

mcp = FastMCP("patent-filewrapper-mcp")

# API client initialization with lazy loading and fallback
# This prevents entire server failure if API client initialization fails
_api_client = None
_api_client_error = None


def get_api_client() -> EnhancedPatentClient:
    """
    Get API client with lazy initialization and error handling

    This function implements lazy initialization to prevent server failure
    if the API client cannot be initialized immediately. It also caches
    initialization errors to avoid repeated failed attempts.

    Returns:
        EnhancedPatentClient instance

    Raises:
        Exception: If API client cannot be initialized (with helpful error message)
    """
    global _api_client, _api_client_error

    if _api_client is not None:
        return _api_client

    # If we've already failed once, return cached error
    if _api_client_error is not None:
        logger.error("API client initialization previously failed - check configuration")
        raise _api_client_error

    try:
        logger.info("Initializing USPTO API client...")
        _api_client = EnhancedPatentClient()
        logger.info("USPTO API client initialized successfully")
        return _api_client
    except Exception as e:
        # Cache the error to avoid repeated failed attempts
        _api_client_error = Exception(
            f"Failed to initialize USPTO API client: {str(e)}. "
            f"Please check:\n"
            f"  1. USPTO_API_KEY environment variable is set\n"
            f"  2. API key is valid (get one from developer.uspto.gov)\n"
            f"  3. Network connectivity to USPTO API\n"
            f"Original error: {type(e).__name__}: {str(e)}"
        )
        logger.exception(f"Failed to initialize API client: {e}")
        raise _api_client_error


# Get initial API client for package manager (with fallback)
try:
    api_client = get_api_client()
except Exception as e:
    logger.warning(f"Could not initialize API client at startup: {e}")
    logger.warning("API client will be initialized on first use")
    api_client = None

# Initialize package manager for enhanced document packages
# Pass None if api_client failed to initialize - PackageManager should handle this
package_manager = PackageManager(api_client) if api_client else None

# Register all prompt templates AFTER mcp object is created
# This registers all 10 comprehensive prompt templates with the MCP server
from .prompts import register_prompts
register_prompts(mcp)


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
        from .exceptions import ValidationError
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
        # Ensure API client is initialized
        global api_client
        if api_client is None:
            api_client = get_api_client()

        # Build query from convenience parameters using centralized helper
        final_query = _build_query_from_params(
            params.query, params.art_unit, params.examiner_name, params.applicant_name,
            params.customer_number, params.status_code, params.filing_date_start,
            params.filing_date_end, params.grant_date_start, params.grant_date_end
        )

        # Input validation
        if len(final_query) > api_client.MAX_QUERY_LENGTH:
            return create_error_response("query_too_long",
                custom_message=f"Query too long (max {api_client.MAX_QUERY_LENGTH} characters)")

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

        result = await api_client.search_inventor(params.name, params.strategy, params.limit, fields)

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

@mcp.tool(name="search_applications")
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
    except ValueError as e:
        # Map common validation errors to error templates
        error_msg = str(e).lower()
        if "limit" in error_msg:
            return create_error_response("invalid_limit", custom_message=str(e))
        elif "offset" in error_msg:
            return create_error_response("invalid_offset", custom_message=str(e))
        else:
            return create_error_response("empty_query", custom_message=f"Parameter validation failed: {str(e)}")
    except Exception as e:
        return format_error_response(f"Search failed: {str(e)}", error_type="search_error")


@mcp.tool(name="search_inventor")
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
        if len(name) > api_client.MAX_NAME_LENGTH:
            return format_error_response(f"Inventor name too long (max {api_client.MAX_NAME_LENGTH} characters)", 400)
        if not SearchStrategy.is_valid(strategy):
            return format_error_response(f"Strategy must be one of: {', '.join(SearchStrategy.all())}", 400)
        if limit < 1 or limit > api_client.MAX_SEARCH_LIMIT:
            return format_error_response(f"Limit must be between 1 and {api_client.MAX_SEARCH_LIMIT}", 400)

        if fields is None:
            fields = ["applicationNumberText", "applicationMetaData.inventionTitle",
                     "applicationMetaData.filingDate", "applicationMetaData.patentNumber",
                     "applicationMetaData.groupArtUnitNumber", "applicationMetaData.examinerNameText"]

        # Get base inventor search results
        result = await api_client.search_inventor(name, strategy, limit, fields)

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


@mcp.tool(name="search_applications_minimal")
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
        if len(final_query) > api_client.MAX_QUERY_LENGTH:
            return create_error_response("query_too_long",
                custom_message=f"Query too long (max {api_client.MAX_QUERY_LENGTH} characters)")
        if limit < 1 or limit > api_client.MAX_SEARCH_LIMIT:
            return format_error_response(
                f"Limit must be between 1 and {api_client.MAX_SEARCH_LIMIT}",
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
            enhanced_results = await api_client.enhance_search_results_with_associated_docs(search_results)
        else:
            enhanced_results = search_results

        # Add query metadata for transparency
        if enhanced_results.get('success'):
            enhanced_results['query_info'] = {
                'constructed_query': final_query,
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
                    'claims_analysis': 'minimal → get_application_documents(document_code=CLM) → get_document_content (both initial and final claims)',
                    'office_action_analysis': 'minimal → get_application_documents(document_code=CTFR|CTNF) → get_document_content',
                    'examiner_citations': 'minimal → get_application_documents(document_code=892) → get_document_content',
                    'applicant_citations': 'minimal → get_application_documents(document_code=IDS|1449) → get_document_content (for Citations MCP)',
                    'noa_analysis': 'minimal → get_application_documents(document_code=NOA) → get_document_content',
                    'user_downloads': 'minimal → get_application_documents(document_code=NOA|CTFR) → get_document_download OR get_granted_patent_documents_download',
                    'cross_mcp': 'minimal → balanced → PTAB/FPD/Citations MCPs'
                }
            }

        return enhanced_results

    except Exception as e:
        return format_error_response(f"Minimal search failed: {str(e)}")

@mcp.tool(name="search_applications_balanced")
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
        if len(final_query) > api_client.MAX_QUERY_LENGTH:
            return format_error_response(
                f"Query too long (max {api_client.MAX_QUERY_LENGTH} characters)",
                400
            )
        if limit < 1 or limit > api_client.MAX_SEARCH_LIMIT:
            return format_error_response(
                f"Limit must be between 1 and {api_client.MAX_SEARCH_LIMIT}",
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
            enhanced_results = await api_client.enhance_search_results_with_associated_docs(search_results)

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

@mcp.tool(name="search_inventor_minimal")
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
                enhanced_temp = await api_client.enhance_search_results_with_associated_docs(temp_results)

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

@mcp.tool(name="search_inventor_balanced")
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
            enhanced_temp = await api_client.enhance_search_results_with_associated_docs(temp_results)

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


@mcp.tool(name="PFW_get_document_content_with_mistral_ocr")
async def pfw_get_document_content(
    app_number: str,
    document_identifier: str,
    auto_optimize: bool = True
) -> Dict[str, Any]:
    """Extract full text from USPTO prosecution documents with intelligent hybrid extraction (PyPDF2 first, Mistral OCR fallback).
PREREQUISITE: First use pfw_get_application_documents to get document_identifier from documentBag.
Auto-optimizes cost: free PyPDF2 for text-based PDFs, ~$0.001/page Mistral OCR only for scanned documents.
MISTRAL_API_KEY is optional - without it, only PyPDF2 extraction is available (works well for text-based PDFs).
Returns: extracted_content, extraction_method, processing_cost_usd.
Example workflow:
1. pfw_get_application_documents(app_number='17896175') → get doc IDs
2. pfw_get_document_content(app_number='17896175', document_identifier='ABC123XYZ')
For document selection strategies and cost optimization, use pfw_get_guidance (see quick reference chart for section selection)."""
    try:
        return await api_client.extract_document_content_hybrid(
            app_number, document_identifier, auto_optimize
        )
    except Exception as e:
        return format_error_response(f"Failed to extract document content: {str(e)}")

@mcp.tool(name="PFW_get_document_download")
async def pfw_get_document_download(app_number: str, document_identifier: str, proxy_port: int = None, generate_persistent_link: bool = True) -> Dict[str, Any]:
    """Generate secure browser-accessible download URLs for USPTO prosecution documents (PDFs).
PREREQUISITE: First use pfw_get_application_documents to get document_identifier from documentBag.
Creates clickable proxy links that handle API authentication while keeping credentials secure.

🔗 LINK TYPES:
- generate_persistent_link=True: Persistent links (default) - encrypted, valid for 7 days
- generate_persistent_link=False: Immediate links - work while proxy running

🔧 ENHANCED PROXY BEHAVIOR:
- Always-on proxy: Set ENABLE_ALWAYS_ON_PROXY=true for immediate access
- On-demand proxy: Automatic startup when first download is requested
- Persistent links: Enabled by default - 7-day encrypted links (set generate_persistent_link=false to disable)
- Download links work immediately in user's browser and remain valid for 7 days

🔒 PERSISTENT LINK BENEFITS:
- Links work for 7 days without proxy restart
- Encrypted storage - no sensitive data in URLs
- Automatic cleanup of expired links
- Perfect for lawyer workflows with delayed document review

CRITICAL RESPONSE FORMAT - Always format as clickable markdown:
**📁 [Download {DocumentType} ({PageCount} pages)]({proxy_url})**

Example workflow for multiple downloads:
1. pfw_get_application_documents(app_number='17896175') → get doc IDs
2. pfw_get_document_download(app_number='17896175', document_identifier='ABC123XYZ') → GENERATES PERSISTENT LINK
3. Format ALL download links as clickable markdown (links work immediately and remain valid for 7 days)
4. Optional: Use generate_persistent_link=false for immediate-only links (requires proxy to stay running)

For document selection strategies and multi-document workflows, use pfw_get_guidance (see quick reference chart for section selection)."""
    try:
        # Use environment variable if proxy_port not specified
        if proxy_port is None:
            # Check PFW_PROXY_PORT first (MCP-specific), then PROXY_PORT (generic)
            proxy_port = int(os.getenv('PFW_PROXY_PORT', os.getenv('PROXY_PORT', 8080)))

        # Validate application number
        app_number = validate_app_number(app_number)

        # Start proxy server if not already running
        await _ensure_proxy_server_running(proxy_port)

        # Get document metadata to validate the request
        docs_result = await api_client.get_documents(app_number)
        if docs_result.get('error'):
            return docs_result

        documents = docs_result.get('documentBag', [])

        # Find the target document
        target_doc = None
        for doc in documents:
            if doc.get('documentIdentifier') == document_identifier:
                target_doc = doc
                break

        if not target_doc:
            return format_error_response(f"Document with identifier '{document_identifier}' not found")

        # Find PDF download option for metadata
        download_options = target_doc.get('downloadOptionBag', [])
        pdf_option = None

        for option in download_options:
            if option.get('mimeTypeIdentifier') == 'PDF':
                pdf_option = option
                break

        if not pdf_option:
            return format_error_response("PDF not available for this document")

        # Create proxy URL (immediate or persistent)
        if generate_persistent_link:
            # Generate encrypted persistent link valid for 7 days
            from .proxy.secure_link_cache import get_link_cache
            link_cache = get_link_cache()
            proxy_download_url = link_cache.generate_persistent_link(
                app_number,
                document_identifier,
                f"http://localhost:{proxy_port}"
            )
        else:
            # Generate immediate download link (original behavior)
            proxy_download_url = f"http://localhost:{proxy_port}/download/{app_number}/{document_identifier}"

        original_download_url = pdf_option.get('downloadUrl', '')

        # Get invention title and patent number for enhanced document info
        invention_title = None
        patent_number = None
        try:
            # Search for the application to get the title and patent number info
            search_result = await api_client.search_applications(
                f"applicationNumberText:{app_number}",
                limit=1,
                offset=0,
                fields=["applicationMetaData.inventionTitle", "applicationMetaData.patentNumber"]
            )
            if search_result.get('success'):
                apps = search_result.get('patentFileWrapperDataBag') or search_result.get('applications')
                if apps:
                    app_data = apps[0]
                    invention_title = app_data.get('applicationMetaData', {}).get('inventionTitle')
                    # Extract patent number using helper function
                    from .api.helpers import extract_patent_number
                    patent_number = extract_patent_number(app_data)
        except Exception as e:
            logger.warning(f"Could not fetch application metadata for {app_number}: {e}")

        # Generate expected filename for user reference
        expected_filename = "Legacy format used (metadata unavailable)"
        if invention_title:
            from .api.helpers import generate_safe_filename
            expected_filename = generate_safe_filename(app_number, invention_title, target_doc.get('documentCode', 'UNKNOWN'), patent_number)

        document_info = {
            "document_code": target_doc.get('documentCode', ''),
            "document_description": target_doc.get('documentCodeDescriptionText', ''),
            "official_date": target_doc.get('officialDate', ''),
            "page_count": pdf_option.get('pageTotalQuantity', 0),
            "file_size_bytes": pdf_option.get('fileSizeQuantity', 0),
            "invention_title": invention_title,
            "patent_number": patent_number,
            "expected_filename_format": expected_filename,
            "filename_enhancement": {
                "app_prefix": f"APP-{app_number}",
                "patent_prefix": f"PAT-{patent_number}" if patent_number else "No patent granted",
                "title_portion": invention_title[:40] if invention_title else "UNTITLED",
                "document_type": target_doc.get('documentCode', 'UNKNOWN')
            }
        }

        return {
            "success": True,
            "proxy_download_url": proxy_download_url,
            "original_download_url": original_download_url,
            "document_info": document_info,
            "application_number": app_number,
            "document_identifier": document_identifier,

            # LLM guidance for proper response formatting
            "llm_response_guidance": {
                "format": f"**📁 [Download {document_info.get('document_description', 'Document')} ({document_info.get('page_count', 'N/A')} pages)]({proxy_download_url})**",
                "critical": "Provide clickable markdown link for browser access"
            },
            "note": "Proxy handles authentication and rate limiting (5 downloads per 10s)"
        }

    except Exception as e:
        return format_error_response(f"Failed to create download proxy: {str(e)}")

@mcp.tool(name="get_application_documents")
async def pfw_get_application_documents(
    app_number: str,
    limit: int = 50,
    document_code: Optional[str] = None,
    direction_category: Optional[str] = None
) -> Dict[str, Any]:
    """Get prosecution document metadata (documentBag) with SELECTIVE FILTERING to avoid context explosion.

⚠️ CRITICAL: For heavily-prosecuted applications with 200+ documents, ALWAYS use filtering parameters.
Requesting all documents without filters can cause massive token usage (100K+ characters).

🆕 FOR GRANTED PATENTS: Use pfw_get_granted_patent_documents_download for complete patent package (ABST, DRW, SPEC, CLM).

📋 FILTERING PARAMETERS:

**document_code** - Filter by specific document type (case-insensitive):
  Key Examiner Actions:
    - NOA: Notice of Allowance, CTFR: Non-Final Rejection, CTNF: Final Rejection, 892: Examiner Citations
  Key Applicant Responses:
    - A...: Amendment/Response, RCEX: Continued Examination, IDS: Info Disclosure, 1449: Applicant Citations
  Patent Components:
    - ABST: Abstract, CLM: Claims, SPEC: Specification, DRW: Drawings, FWCLM: Claims Index

**direction_category** - Filter by source:
    - INCOMING: Applicant submissions, OUTGOING: USPTO examiner documents, INTERNAL: USPTO internal

**limit** - Max documents to return (default: 50, max: 200). Applied AFTER filtering.

📌 EXAMPLES (always use filtering):

# Allowance reasoning for litigation
pfw_get_application_documents(app_number='14171705', document_code='NOA')

# Office action rejections
pfw_get_application_documents(app_number='14171705', document_code='CTFR', limit=20)

# All applicant responses
pfw_get_application_documents(app_number='14171705', direction_category='INCOMING', limit=100)

# Examiner's cited prior art
pfw_get_application_documents(app_number='14171705', document_code='892')

⚠️ AVOID: pfw_get_application_documents(app_number='...', limit=200) without filters
✅ DO: Always filter by document_code or direction_category

Returns document identifiers needed for pfw_get_document_download or pfw_get_document_content.

For cross-MCP workflows, use pfw_get_guidance (see quick reference chart)."""
    try:
        # Input validation
        if not app_number or len(app_number.strip()) == 0:
            return format_error_response("Application number cannot be empty", 400)
        if limit < 1 or limit > 200:
            return format_error_response("Limit must be between 1 and 200", 400)
        if direction_category and not DocumentDirection.is_valid(direction_category):
            return format_error_response(
                f"direction_category must be one of: {', '.join(DocumentDirection.all())}",
                400
            )

        # Validate and clean app number
        app_number = validate_app_number(app_number)

        # Get document bag from USPTO API with filtering
        docs_result = await api_client.get_documents(
            app_number,
            limit=limit,
            document_code=document_code,
            direction_category=direction_category
        )

        if docs_result.get('error'):
            return docs_result

        return {
            "success": True,
            "application_number": docs_result.get('application_number'),
            "count": docs_result.get('count'),
            "documentBag": docs_result.get('documentBag', []),
            "summary": docs_result.get('summary', {}),
            "request_id": f"docs-{app_number}",
            "guidance": {
                "workflow": [
                    "Use document_identifier with pfw_get_document_download for browser downloads",
                    "Use document_identifier with pfw_get_document_content for text extraction (auto PyPDF2/OCR)",
                    "Filter with document_code (NOA, CTFR, CTNF, 892) for key documents"
                ],
                "filtering": {
                    "noa": "document_code='NOA' - Allowance reasoning",
                    "rejections": "document_code='CTFR'/'CTNF' - Office actions",
                    "prior_art": "document_code='892' - Examiner citations, '1449' - Applicant citations",
                    "amendments": "document_code='CLM' - Claim evolution"
                },
                "cross_mcp": {
                    "ptab": "PTAB applicationNumberText/patentNumber → PFW minimal → get_application_documents(document_code='NOA') → compare examiner vs PTAB reasoning",
                    "fpd": "FPD applicationNumber → PFW minimal → get_application_documents(document_code='CTFR'|'CTNF') → analyze rejection patterns",
                    "citations": "Citations applicationNumber/patentNumber → PFW minimal → get_application_documents(document_code='892'|'1449') → examiner citation analysis"
                },
                "key_insight": "Document identifiers are ONLY valid with this specific applicationNumberText",
                "expectation": "No single 'complete patent PDF' - must download individual documents"
            }
        }

    except Exception as e:
        return {
            "success": False,
            "application_number": app_number,
            "error": str(e),
            "documentBag": [],
            "count": 0
        }

def _create_document_summary(documents: List[dict]) -> Dict[str, Any]:
    """Create summary of available documents for LLM guidance"""

    if not documents:
        return {"total": 0, "types": {}, "key_documents": []}

    summary = {
        "total": len(documents),
        "document_types": {},
        "key_documents": [],
        "total_download_options": 0
    }

    # Count document types and download options
    for doc in documents:
        doc_code = doc.get("documentCode", "UNKNOWN")
        summary["document_types"][doc_code] = summary["document_types"].get(doc_code, 0) + 1
        summary["total_download_options"] += len(doc.get("downloadOptionBag", []))

    # Identify key documents for patent analysis
    key_doc_codes = ["ABST", "CLM", "SPEC", "NOA", "CTFR", "CTNF", "DRW"]
    for doc in documents:
        if doc.get("documentCode") in key_doc_codes:
            download_options = doc.get("downloadOptionBag", [])
            if download_options:
                summary["key_documents"].append({
                    "document_code": doc.get("documentCode"),
                    "document_description": doc.get("documentCodeDescriptionText", ""),
                    "official_date": doc.get("officialDate", ""),
                    "document_identifier": doc.get("documentIdentifier", ""),
                    "page_count": download_options[0].get("pageTotalQuantity", 0),
                    "download_url": download_options[0].get("downloadUrl", "")
                })

    return summary

@mcp.tool(name="get_patent_or_application_xml")
async def pfw_get_patent_or_application_xml(
    identifier: str,
    content_type: str = "auto",
    include_fields: Optional[List[str]] = None,
    include_raw_xml: bool = True
) -> Dict[str, Any]:
    """Get structured XML content for patents or applications (filed after January 1, 2001).
Use after finding applications via search to analyze claims, description, abstract, and citations.
Auto-detects patent vs application from identifier. Prefers granted patent XML (PTGRXML) over application XML (APPXML).

**DEFAULT BEHAVIOR (include_fields not specified):**
Returns only core content fields optimized for patent analysis (~5K tokens structured + ~50K raw_xml):
- abstract: Full abstract text
- claims: All independent and dependent claims with full text
- description: First 5 paragraphs of detailed description/specification

**MAXIMUM EFFICIENCY (include_raw_xml=False):**
Suppress raw XML to achieve 95% token reduction (e.g., ~1.5K tokens for claims only):
- Set include_raw_xml=False when you only need structured_content fields
- Raw XML useful for debugging or custom parsing, but not needed for most workflows

**AVAILABLE FIELDS (use include_fields to customize):**
Core Content:
  - abstract: Full abstract text
  - claims: All claims with full text
  - description: First 5 paragraphs of specification

Metadata (also available via pfw_search_applications_balanced):
  - inventors: Inventor names, sequences, and locations
  - applicants: Applicant/assignee information
  - classifications: USPTO and Cooperative Patent Classifications (CPC/IPC)
  - publication_info: Publication dates, numbers, and document information

References:
  - citations: Forward and backward citations (consider uspto_enriched_citation_mcp for richer analysis)

**SELECTIVE USAGE EXAMPLES:**

1. Recommended (patent analysis without raw XML overhead):
   pfw_get_patent_or_application_xml(identifier='7971071', include_raw_xml=False)
   → Returns: abstract, claims, description (~5K tokens - 91% reduction vs default!)

2. Ultra-efficient claims only (claim construction, infringement analysis):
   pfw_get_patent_or_application_xml(identifier='7971071', include_fields=['claims'], include_raw_xml=False)
   → Returns: claims only (~1.5K tokens - 95% reduction!)

3. Claims + citations without raw XML (prior art analysis):
   pfw_get_patent_or_application_xml(identifier='7971071', include_fields=['claims', 'citations'], include_raw_xml=False)
   → Returns: claims, citations (~2.5K tokens)

4. Just inventors without raw XML (portfolio analysis):
   pfw_get_patent_or_application_xml(identifier='7971071', include_fields=['inventors'], include_raw_xml=False)
   → Returns: inventors only (~300 tokens - 99% reduction!)

5. Inventors + applicants without raw XML (entity analysis):
   pfw_get_patent_or_application_xml(identifier='7971071', include_fields=['inventors', 'applicants'], include_raw_xml=False)
   → Returns: inventors, applicants (~500 tokens)

6. Legacy default (backward compatibility - includes raw XML):
   pfw_get_patent_or_application_xml(identifier='7971071')
   → Returns: abstract, claims, description + raw_xml (~55K tokens total)

7. Everything with raw XML (debugging or custom XML parsing):
   pfw_get_patent_or_application_xml(
       identifier='7971071',
       include_fields=['abstract', 'claims', 'description', 'inventors', 'applicants', 'classifications', 'citations', 'publication_info']
   )
   → Returns: all fields + raw_xml (~80K tokens)

**CONTEXT OPTIMIZATION TIPS:**
- For maximum efficiency: Set include_raw_xml=False (most workflows don't need raw XML)
- For inventor/applicant reports: Add include_fields=['inventors', 'applicants'] if using minimal search
- For metadata: Check if already available from prior pfw_search_applications_balanced call
- For citations: Consider uspto_enriched_citation_mcp for deeper citation analysis with backward/forward citation trees
- Request only what you need to minimize context

For field selection guidance and token estimates, use pfw_get_guidance(section='tools')."""
    try:
        return await api_client.get_patent_or_application_xml(identifier, content_type, include_fields, include_raw_xml)

    except Exception as e:
        return format_error_response(f"Failed to get XML content: {str(e)}")

@mcp.tool(name="get_granted_patent_documents_download")
async def pfw_get_granted_patent_documents_download(
    app_number: str,
    include_drawings: bool = True,
    include_original_claims: bool = False,
    direction_category: Optional[str] = "INCOMING",
    proxy_port: int = None,
    generate_persistent_links: bool = True
) -> Dict[str, Any]:
    """Get complete granted patent package (Abstract, Drawings, Specification, Claims) in one call.

    Perfect for: Due diligence, portfolio review, litigation preparation, or whenever an attorney
    needs the complete granted patent. Returns all 4 components with organized download links.

    ✅ ENHANCED PROXY INTEGRATION: This tool provides immediate download access!
    - Always-on proxy: Links work immediately (if ENABLE_ALWAYS_ON_PROXY=true)
    - On-demand proxy: Automatic startup when needed
    - Persistent links: Enabled by default - 7-day encrypted access (set generate_persistent_links=false to disable)
    - Download links are immediately clickable after tool execution and remain valid for 7 days

    Args:
        app_number: Patent application number (required)
        include_drawings: Include drawings in response (default: True, set False to skip)
        include_original_claims: Get originally-filed claims vs. granted claims (default: False = granted)
        proxy_port: Proxy server port (default: 8080)

    Common scenarios:
    - "Get me the granted patent for application 14171705"
    - "I need the complete patent package for portfolio review"
    - "Download all components of the granted patent"

    Returns structured response with all components and download links. Use pfw_get_application_documents
    for selective filtering in complex prosecutions with 200+ documents.

    For complex workflows, see pfw_get_guidance (quick reference chart available).
    """
    try:
        # Use environment variable if proxy_port not specified
        if proxy_port is None:
            # Check PFW_PROXY_PORT first (MCP-specific), then PROXY_PORT (generic)
            proxy_port = int(os.getenv('PFW_PROXY_PORT', os.getenv('PROXY_PORT', 8080)))

        # Validate app_number using the existing validation function
        app_number = validate_app_number(app_number)

        # Start proxy server if not already running
        await _ensure_proxy_server_running(proxy_port)

        result = await api_client.get_granted_patent_documents_download(
            app_number=app_number,
            include_drawings=include_drawings,
            include_original_claims=include_original_claims,
            direction_category=direction_category
        )

        return result

    except ValueError as ve:
        return format_error_response(str(ve), 400)
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "guidance": "Use pfw_search_applications_balanced to verify application number exists"
        }

# REMOVED: pfw_get_tool_reflections - migrated to pfw_get_guidance for context efficiency
# The comprehensive tool reflection functionality has been migrated to sectioned guidance
# Use pfw_get_guidance(section='tools') for tool-specific guidance
# Use pfw_get_guidance(section='overview') to see all available sections


# =============================================================================
# MCP RESOURCES for Enhanced Client Capabilities
# =============================================================================

@mcp.resource(
    "uspto://pfw/doc-codes",
    name="RESOURCE: USPTO Document Code Decoder",
    description="USPTO Document Code decoder table covering common prosecution, PTAB, and FPD document codes with descriptions and business processes",
    mime_type="text/markdown"
)
def read_doc_codes() -> str:
    """
    Read USPTO document code decoder table resource via HTTP proxy

    Returns:
        Formatted document code table from USPTO EFS-Web documentation
    """
    try:
        import httpx
        import csv
        import io

        # Use HTTP proxy to serve the document codes table
        proxy_url = "http://localhost:8080/doc-codes"

        logger.info("Requesting document codes table from proxy server")

        # Try to get from proxy server first
        try:
            response = httpx.get(proxy_url, timeout=10.0)
            if response.status_code == 200:
                logger.info(f"Retrieved document codes from proxy ({len(response.text)} characters)")
                return response.text
            else:
                logger.warning(f"Proxy server returned status {response.status_code}: {response.text[:200]}")
        except Exception as proxy_error:
            logger.warning(f"Proxy server not available, generating from local CSV: {proxy_error}")

        # Fallback to local CSV processing
        csv_path = "reference/Document_Descriptions_List.csv"

        # Check if file exists relative to current working directory
        import os
        if not os.path.exists(csv_path):
            # Try relative to script directory
            script_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.join(script_dir, "..", "..")
            csv_path = os.path.join(project_root, "reference", "Document_Descriptions_List.csv")

        if not os.path.exists(csv_path):
            raise ValueError("Document_Descriptions_List.csv not found")

        # Parse CSV and format as markdown
        output = []
        output.append("# USPTO Document Code Decoder Table")
        output.append("")
        output.append("**Source**: [USPTO EFS-Web Document Description List](https://www.uspto.gov/patents/apply/filing-online/efs-info-document-description)")
        output.append("**Updated**: April 27, 2022")
        output.append("")
        output.append("This table provides document codes used in USPTO patent prosecution, PTAB proceedings, and FPD petitions.")
        output.append("")

        # Common prosecution codes
        output.append("## Common Prosecution Document Codes")
        output.append("")
        output.append("| Code | Description | Business Process |")
        output.append("|------|-------------|------------------|")

        prosecution_codes = []
        ptab_codes = []

        # Try multiple encodings to handle the CSV file
        encodings_to_try = ['utf-8', 'utf-8-sig', 'latin1', 'cp1252', 'iso-8859-1']

        for encoding in encodings_to_try:
            try:
                logger.info(f"Trying to read CSV with encoding: {encoding}")
                with open(csv_path, 'r', encoding=encoding) as file:
                    csv_reader = csv.reader(file)
                    headers = None

                    for row in csv_reader:
                        if not headers:
                            headers = row
                            continue

                        if len(row) >= 4:
                            category = row[0].strip()
                            description = row[1].strip()
                            business_process = row[2].strip()
                            doc_code = row[3].strip()

                            if doc_code and doc_code != "DOC CODE":
                                # Clean up description and handle encoding issues
                                description = description.replace('\n', ' ').replace('\r', ' ')
                                business_process = business_process.replace('\n', ' ').replace('\r', ' ')

                                # Remove any problematic characters
                                description = ''.join(char if ord(char) < 128 else '?' for char in description)
                                business_process = ''.join(char if ord(char) < 128 else '?' for char in business_process)

                                # Limit lengths for readability
                                if len(description) > 100:
                                    description = description[:97] + "..."
                                if len(business_process) > 80:
                                    business_process = business_process[:77] + "..."

                                code_entry = {
                                    'code': doc_code,
                                    'description': description,
                                    'process': business_process,
                                    'category': category
                                }

                                if 'PTAB' in category:
                                    ptab_codes.append(code_entry)
                                else:
                                    prosecution_codes.append(code_entry)

                logger.info(f"Successfully read CSV with {encoding} encoding")
                break  # Success - exit the encoding loop

            except UnicodeDecodeError as e:
                logger.warning(f"Failed to read CSV with {encoding} encoding: {e}")
                continue
            except Exception as e:
                logger.error(f"Error reading CSV with {encoding} encoding: {e}")
                continue
        else:
            # If we get here, all encodings failed
            raise ValueError(f"Unable to read CSV file with any of the attempted encodings: {encodings_to_try}")

        # Add common prosecution codes
        for code_info in prosecution_codes[:50]:  # Limit to first 50 for readability
            output.append(f"| {code_info['code']} | {code_info['description']} | {code_info['process']} |")

        # Add PTAB codes
        if ptab_codes:
            output.append("")
            output.append("## PTAB Document Codes")
            output.append("")
            output.append("| Code | Description | Business Process |")
            output.append("|------|-------------|------------------|")

            for code_info in ptab_codes:
                output.append(f"| {code_info['code']} | {code_info['description']} | {code_info['process']} |")

        # Add footer
        output.append("")
        output.append("---")
        output.append("*This table is generated from the USPTO EFS-Web Document Description List and includes the most commonly used document codes in patent prosecution and PTAB proceedings.*")

        result = "\n".join(output)
        logger.info(f"Generated document codes table ({len(result)} characters)")
        return result

    except Exception as e:
        logger.error(f"Error reading document codes resource: {e}")
        raise ValueError(f"Failed to read document codes resource: {str(e)}")

# Note: HTTP endpoints at /reflections/* also provide the same functionality

@mcp.tool(name="PFW_get_guidance")
async def pfw_get_guidance(section: str = "overview") -> str:
    """Get selective USPTO PFW guidance sections for context-efficient workflows

    🎯 QUICK REFERENCE - What section for your question?

    🔍 "Find patents by inventor/company/art unit" → fields
    📄 "Get complete patent package/documents" → documents
    🔖 "Decode document codes (NOA, CTFR, 892, etc.)" → document_codes
    🤝 "Research IPR vs prosecution patterns" → workflows_ptab
    🚩 "Analyze petition red flags + prosecution" → workflows_fpd
    📊 "Citation analysis for examiner behavior" → workflows_citations
    🧠 "Domain-based RAG for legal framework" → workflows_pinecone
    🏢 "Complete company due diligence" → workflows_complete
    ⚙️ "Convenience parameter searches" → tools
    ❌ "Search errors or download issues" → errors
    💰 "Reduce API costs" → cost

    Available sections:
    - overview: Available sections and tool summary
    - workflows_pfw: PFW-only workflows (litigation, due diligence, prior art)
    - workflows_ptab: PFW + PTAB integration workflows
    - workflows_fpd: PFW + FPD integration workflows
    - workflows_citations: PFW + Citations integration workflows
    - workflows_pinecone: PFW + Pinecone RAG/Assistant domain-based strategic search
    - workflows_complete: Four-MCP complete lifecycle analysis
    - documents: Document downloads, codes, and selection guidance
    - document_codes: Comprehensive document code decoder (50+ codes)
    - fields: Field selection strategies and context reduction
    - tools: Tool-specific guidance and parameters
    - errors: Common error patterns and troubleshooting
    - advanced: Advanced workflows and optimization
    - cost: Cost optimization strategies

    Args:
        section: Which guidance section to retrieve (default: overview)

    Returns:
        str: Focused guidance section (1-12K chars vs 62K full content)
    """
    try:
        # Static sectioned guidance content for context-efficient access
        sections = {
            "overview": _get_overview_section(),
            "workflows_pfw": _get_workflows_pfw_section(),
            "workflows_ptab": _get_workflows_ptab_section(),
            "workflows_fpd": _get_workflows_fpd_section(),
            "workflows_citations": _get_workflows_citations_section(),
            "workflows_pinecone": _get_workflows_pinecone_section(),
            "workflows_complete": _get_workflows_complete_section(),
            "documents": _get_documents_section(),
            "document_codes": _get_document_codes_section(),
            "fields": _get_fields_section(),
            "tools": _get_tools_section(),
            "errors": _get_errors_section(),
            "advanced": _get_advanced_section(),
            "cost": _get_cost_section()
        }

        if section not in sections:
            available = ", ".join(sections.keys())
            return f"Invalid section '{section}'. Available: {available}"

        result = f"# USPTO PFW MCP Guidance - {section.title()} Section\n\n{sections[section]}"

        logger.info(f"Retrieved PFW guidance section '{section}' ({len(result)} characters)")
        return result

    except Exception as e:
        logger.error(f"Error accessing PFW guidance section '{section}': {e}")
        return format_error_response(f"Failed to access guidance section '{section}': {str(e)}")


# =============================================================================
# PROMPT TEMPLATES
# =============================================================================
# All 10 comprehensive prompt templates have been moved to src/patent_filewrapper_mcp/prompts/
# and are automatically registered via the `from . import prompts` statement above.
#
# Available prompts:
# - complete_patent_package_retrieval_PTAB_FPD
# - patent_search
# - art_unit_quality_assessment_FPD
# - litigation_research_setup_PTAB_FPD
# - inventor_portfolio_analysis
# - technology_landscape_mapping_PTAB
# - document_filtering_assistant
# - patent_explanation_for_attorneys
# - prior_art_analysis_CITATION
# - examiner_behavior_intelligence_CITATION
#
# See prompts/__init__.py for full documentation.
# =============================================================================


# Global proxy server state
_proxy_server_running = False
_proxy_server_task = None


def _handle_background_task_exception(task: asyncio.Task):
    """
    Handle exceptions from background asyncio tasks

    This prevents silent failures in background tasks by logging errors
    and ensuring proper error handling for critical async operations.

    Args:
        task: The completed asyncio Task to check for exceptions
    """
    try:
        task.result()  # This will raise if the task failed
    except asyncio.CancelledError:
        logger.info("Background task was cancelled (this is normal during shutdown)")
    except Exception as e:
        logger.exception(f"Background task failed with unhandled exception: {e}")
        # Additional error handling can be added here:
        # - Restart critical tasks
        # - Send alerts
        # - Update health status
        global _proxy_server_running
        if task == _proxy_server_task:
            _proxy_server_running = False
            logger.error("Proxy server task failed - proxy server is no longer running")


async def _ensure_proxy_server_running(port: int = 8080):
    """Ensure the proxy server is running"""
    global _proxy_server_running, _proxy_server_task

    if not _proxy_server_running:
        logger.info(f"Starting HTTP proxy server on port {port}")
        _proxy_server_task = asyncio.create_task(_run_proxy_server(port))

        # Add error handler to catch background task failures
        _proxy_server_task.add_done_callback(_handle_background_task_exception)

        _proxy_server_running = True
        # Give the server a moment to start
        await asyncio.sleep(0.5)

async def _run_proxy_server(port: int = 8080):
    """Run the FastAPI proxy server"""
    try:
        import uvicorn
        from .proxy.server import create_proxy_app

        app = create_proxy_app()
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="info",
            access_log=False  # Reduce noise in logs
        )
        server = uvicorn.Server(config)
        logger.info(f"HTTP proxy server starting on http://127.0.0.1:{port}")
        await server.serve()

    except Exception as e:
        global _proxy_server_running
        _proxy_server_running = False
        logger.error(f"Proxy server failed: {e}")
        raise

# =============================================================================
# GUIDANCE SECTION HELPERS
# =============================================================================

def _get_overview_section() -> str:
    """Overview section with available sections and quick reference"""
    return """## Available Sections and Quick Reference

### 🎯 Quick Reference Chart - What section for your question?

- 🔍 **"Find patents by inventor/company/art unit"** → `fields`
- 📄 **"Get complete patent package/documents"** → `documents`
- 🔖 **"Decode document codes (NOA, CTFR, 892, etc.)"** → `document_codes`
- 🤝 **"Research IPR vs prosecution patterns"** → `workflows_ptab`
- 🚩 **"Analyze petition red flags + prosecution"** → `workflows_fpd`
- 📊 **"Citation analysis for examiner behavior"** → `workflows_citations`
- 🧠 **"Domain-based RAG for legal framework (§101, §103, §112)"** → `workflows_pinecone`
- 🏢 **"Complete company due diligence"** → `workflows_complete`
- ⚙️ **"Tool guidance and parameters"** → `tools`
- ❌ **"Search errors or download issues"** → `errors`
- 💰 **"Reduce API costs and optimize usage"** → `cost`

### Available Sections:
- **overview**: Available sections and tool summary (this section)
- **workflows_pfw**: PFW-only workflows (litigation, due diligence, prior art)
- **workflows_ptab**: PFW + PTAB integration workflows
- **workflows_fpd**: PFW + FPD integration workflows
- **workflows_citations**: PFW + Citations integration workflows
- **workflows_pinecone**: PFW + Pinecone RAG/Assistant domain-based strategic search (9 domains: §101, §103, §112, etc.)
- **workflows_complete**: Four-MCP complete lifecycle analysis
- **documents**: Document downloads, codes, and selection guidance
- **document_codes**: Comprehensive document code decoder (50+ codes)
- **fields**: Field selection strategies and context reduction
- **tools**: Tool-specific guidance and parameters
- **errors**: Common error patterns and troubleshooting
- **advanced**: Advanced workflows and optimization
- **cost**: Cost optimization strategies

### Context Efficiency Benefits:
- **95% token reduction** (1-12KB per section vs 62KB total)
- **Targeted guidance** for specific workflows
- **Same comprehensive content** organized for efficiency
- **Backwards compatible** with MCP Resources"""

def _get_tools_section() -> str:
    """Tools section with tool-specific guidance"""
    return """## Core Tools Overview

### Search Tools
- **search_applications_minimal**: High-volume discovery (15 preset fields or custom ultra-minimal)
- **search_applications_balanced**: Detailed analysis with cross-MCP integration fields
- **search_inventor_minimal**: Efficient inventor portfolio discovery
- **search_inventor_balanced**: Comprehensive inventor analysis

### Document Tools
- **get_application_documents**: Get prosecution document metadata for strategic selection
- **PFW_get_document_content_with_mistral_ocr**: Hybrid extraction (PyPDF2 + OCR fallback)
- **PFW_get_document_download**: Secure proxy downloads for browser access
- **get_patent_or_application_xml**: Free structured XML content with configurable field selection
- **get_granted_patent_documents_download**: Complete patent package with prosecution

### Guidance Tool
- **PFW_get_guidance**: Context-efficient sectioned guidance (this tool)

## Progressive Disclosure Strategy

### Stage 1: Discovery (Minimal Search)
- Use `search_applications_minimal` for broad exploration
- 15 preset fields (~500 chars/result) OR custom fields (~100 chars/result)
- Present top results to user for selection on vague queries

### Stage 2: Analysis (Balanced Search)
- Use `search_applications_balanced` for detailed metadata
- 18+ fields including cross-MCP integration fields (~2KB/result)
- Limit to 10-20 user-selected results

### Stage 3: Documents
- Use `get_application_documents` to see document metadata
- Strategic selection of most valuable documents

### Stage 4: Content
- Try `get_patent_or_application_xml` first (free)
- Use document extraction tools for prosecution documents
- Use proxy downloads for browser access

## XML Field Selection (get_patent_or_application_xml)

### Two Parameters for Maximum Control

**1. include_fields** - Select which structured fields to return:
- Default: ["abstract", "claims", "description"]
- Available: abstract, claims, description, inventors, applicants, classifications, citations, publication_info
- Use to get surgical precision on content needed

**2. include_raw_xml** - Control raw XML inclusion:
- Default: True (backward compatibility - includes ~50K character raw XML)
- **RECOMMENDED: False** (removes raw XML overhead - most workflows don't need it)
- Raw XML useful ONLY for: debugging, custom XML parsing, or raw XML analysis
- For 95%+ of use cases: Set to False

### Why Set include_raw_xml=False?

**Problem with default:**
- Returns structured_content (~5K tokens) + raw_xml (~50K tokens) = 55K tokens total
- Raw XML is the full patent XML document (50,000+ characters)
- Wastes context unless you're doing custom XML parsing

**Solution:**
- Set include_raw_xml=False
- Get ONLY structured_content with selected fields
- Achieves 91-99% token reduction depending on field selection

### Ultra-Efficient Usage (RECOMMENDED)

**Just Claims without raw XML (~1.5K tokens - 95% reduction!):**
```python
pfw_get_patent_or_application_xml(
    identifier='7971071',
    include_fields=['claims'],
    include_raw_xml=False
)
```
Use for: Claim construction, infringement analysis, claim scope assessment

**Claims + Citations without raw XML (~2.5K tokens):**
```python
pfw_get_patent_or_application_xml(
    identifier='7971071',
    include_fields=['claims', 'citations'],
    include_raw_xml=False
)
```
Use for: Prior art analysis, claim differentiation
Note: Consider uspto_enriched_citation_mcp for deeper citation trees

**Inventors + Applicants without raw XML (~500 tokens - 99% reduction!):**
```python
pfw_get_patent_or_application_xml(
    identifier='7971071',
    include_fields=['inventors', 'applicants'],
    include_raw_xml=False
)
```
Use for: Portfolio reports, entity analysis, assignment tracking

**Default fields without raw XML (~5K tokens):**
```python
pfw_get_patent_or_application_xml(
    identifier='7971071',
    include_raw_xml=False
)
```
Use for: Standard patent analysis without raw XML overhead

### Available Fields
- **Core:** abstract, claims, description
- **Metadata:** inventors, applicants, classifications, publication_info
- **References:** citations

### Context Optimization Tips
- **Always set include_raw_xml=False unless you need raw XML for custom parsing**
- Default is optimal for field selection, but includes raw XML overhead
- Check if metadata already available from pfw_search_applications_balanced
- For inventor/applicant reports: Add include_fields=['inventors', 'applicants'] if using minimal search
- Request only what you need - each field adds tokens

## Key Parameters

### Field Customization
```python
# Ultra-minimal for discovery
fields=["applicationNumberText", "inventionTitle"]

# Cross-MCP integration
fields=["applicationNumberText", "examinerNameText", "groupArtUnitNumber"]
```

### Convenience Parameters
- `applicant_name`: Direct applicant search
- `inventor_name`: Direct inventor search
- `examiner_name`: Find by specific examiner
- `art_unit`: Filter by group art unit
- `filing_date_start/end`: Date range filtering
- `application_status`: Filter by status"""

def _get_documents_section() -> str:
    """Documents section with codes, selection, and download guidance"""
    return """## Document Selection Guide

### Most Important Document Types
- **CTFR**: Office Action (rejection/objection)
- **NOA**: Notice of Allowance (examiner's final reasoning)
- **892**: Examiner's Prior Art Citations
- **N417**: Applicant Amendment/Response
- **INTERVIEW**: Examiner Interview Summary

### Document Selection by Use Case

#### Litigation Research
**Priority:** NOA → Final CTFR → 892 → N417
**Focus:** Examiner's reasoning and prior art analysis

#### Due Diligence
**Priority:** NOA → All CTFR → Fee worksheets → Interview summaries
**Focus:** Prosecution quality and timeline issues

#### Prior Art Research
**Priority:** 892 → CTFR with 103 rejections → Search reports
**Focus:** Examiner's search methodology and citation patterns

#### Patent Prosecution Strategy
**Priority:** Interview summaries → NOA → Recent CTFRs in art unit
**Focus:** Examiner preferences and successful arguments

## Document Direction Categories
- **FROM_USPTO**: CTFR, NOA, 892, INTERVIEW (examiner to applicant)
- **FROM_APPLICANT**: N417, FEE, PETITION (applicant to USPTO)
- **SYSTEM_GENERATED**: PUB, PTX, status updates

## Secure Downloads

### Proxy Server Features
- **Browser-accessible downloads** via secure proxy
- **API key security** - keys never exposed in URLs
- **Rate limiting compliance** (5 downloads per 10 seconds)
- **Enhanced filenames** with application metadata

### Download Workflow
1. **Automatic proxy startup** when download tools are called
2. **Working links** immediately available in browser
3. **7-day encrypted access** to downloaded documents
4. **Cross-MCP document store** for FPD and PTAB integration

## Cost Optimization

### Document Extraction Hierarchy
1. **XML Content (Free)**: Try first for patents/applications
2. **PyPDF2 (Free)**: Works for 80%+ of patent documents
3. **Mistral OCR ($0.001-0.003)**: Only for scanned/poor quality

### Typical OCR Costs
- Standard office action: $0.001-0.002 (2-4 pages)
- Complex office action: $0.002-0.003 (5-8 pages)
- Notice of allowance: $0.001 (1-2 pages)
- Patent specification: $0.005-0.015 (20-50 pages)

### Smart Cost Management
- Always try XML first for patents
- Use PyPDF2 before OCR
- Reserve OCR for critical documents
- Batch document extraction when possible"""

def _get_document_codes_section() -> str:
    """Comprehensive document code decoder for documentBag responses"""
    return """## Document Code Decoder (DocumentBag Reference)

### 📋 Most Common Prosecution Document Codes

**Quick tip:** Use these codes with `pfw_get_application_documents(app_number, document_code='CODE')`

---

### 🔴 Examiner Communications (FROM USPTO)

**Office Actions:**
- **CTFR** - Office Action (Non-Final Rejection) - Main examination document
- **CTNF** - Office Action (Final Rejection) - Closes prosecution
- **NOA** - Notice of Allowance - Examiner's final approval reasoning
- **SRFW** - Restriction/Election Requirement - Examiner requires applicant to elect claims

**Citations & Search:**
- **892** - Notice of References Cited (Examiner Citations) - Prior art cited by examiner
- **SRNT** - Examiner's Search Strategy and Results - Search methodology details
- **WFEE** - Issue Fee Due - Notice to pay issue fee after allowance

**Interviews & Communications:**
- **INTERVIEW** - Examiner Interview Summary - Official record of interview discussion
- **CTFREF** - Examiner's Answer (After Appeal Brief) - Examiner's response to appeal

---

### 🔵 Applicant Responses (FROM APPLICANT)

**Amendments:**
- **A.PE** - Preliminary Amendment - Filed before first office action
- **A...** - Amendment/Response After Non-Final - Response to non-final rejection
- **A.NE** - Response After Final Action - Amendment after final rejection
- **A.NA** - Amendment After Notice of Allowance (Rule 312) - Post-allowance amendment

**Requests & Filings:**
- **RCEX** - Request for Continued Examination (RCE) - Reopens closed prosecution
- **IDS** - Information Disclosure Statement - Applicant cites prior art
- **EXT** - Extension of Time Request - Request more time to respond
- **N417** - Applicant's Response/Amendment - Generic response document

**Citations:**
- **1449** - Information Disclosure Statement (PTO-1449) - Applicant citations with PTO form

---

### 📄 Patent Components (GRANTED PATENTS)

**Core Patent Documents:**
- **ABST** - Abstract - Brief invention summary
- **CLM** - Claims - Patent claims (as-filed or amended)
- **SPEC** - Specification - Detailed invention description
- **DRW** - Drawings - Patent drawings/figures
- **FWCLM** - File Wrapper Claims - Claims index/history

**Grant Documents:**
- **ISSUE** - Issue Notification - Patent has issued
- **PTX** - Patent Grant Full Text - Complete granted patent
- **BIB** - Bibliographic Data - Patent bibliographic info

---

### 📊 Administrative & Filing Documents

**Fees & Payments:**
- **FEE** - Fee Transmittal - Fee payment documentation
- **M844** - Entity Status Form (Small/Micro) - Entity status declaration
- **WFEE** - Issue Fee Payment - Issue fee transmittal

**Priority & Continuity:**
- **CONTIN** - Continuation Data Sheet - Priority/continuity claims
- **FORP** - Foreign Priority Certificate - Foreign priority documents
- **PRIORIT** - Certified Priority Document - Priority claim certification

**Status & Administrative:**
- **APPLICAT** - Application Data Sheet (ADS) - Formal application info
- **OATH** - Declaration/Oath - Inventor declaration
- **POA** - Power of Attorney - Attorney authorization
- **SB15** - Application Size Fee Determination - Size fee calculations

---

### 📑 Prosecution History Documents

**Appeal Documents:**
- **ABRF** - Appeal Brief - Applicant's appeal arguments
- **RPLY** - Reply Brief - Reply to examiner's answer
- **FDEC** - Appeal Decision - PTAB appeal decision

**Correspondence:**
- **WDRL** - Abandonment/Withdrawal - Application abandoned
- **PAS** - Pre-Appeal Brief Conference Request - Pre-appeal review
- **EXPARTE** - Ex Parte Reexamination - Reexamination request

---

### 📌 Usage Examples

**Get examiner's key documents:**
```python
# Examiner's citations
pfw_get_application_documents(app_number, document_code='892')

# Final office actions
pfw_get_application_documents(app_number, document_code='CTFR|CTNF')

# Allowance reasoning
pfw_get_application_documents(app_number, document_code='NOA')
```

**Get applicant's responses:**
```python
# All amendments
pfw_get_application_documents(app_number, document_code='A...')  # Wildcard matches all A. codes

# IDS submissions (for Citations MCP integration)
pfw_get_application_documents(app_number, document_code='IDS|1449')

# RCE filings
pfw_get_application_documents(app_number, document_code='RCEX')
```

**Get patent components:**
```python
# Core patent documents
pfw_get_application_documents(app_number, document_code='ABST|CLM|SPEC|DRW')

# Claims evolution
pfw_get_application_documents(app_number, document_code='CLM|FWCLM')
```

---

### 📚 Document Direction Quick Reference

**INCOMING (FROM APPLICANT):** A..., IDS, RCEX, EXT, N417, 1449, FEE, POA
**OUTGOING (FROM USPTO):** CTFR, CTNF, NOA, 892, INTERVIEW, WFEE, SRFW
**SYSTEM GENERATED:** ISSUE, PTX, BIB, PUB

---

### 🔍 Finding Rare/Unlisted Codes

For comprehensive code list (3,100+ codes), see `reference/Document_Descriptions_List.csv`.

**Note:** This decoder excludes:
- Petition codes (see FPD MCP for petition-specific documents)
- PTAB codes (see PTAB MCP for trial proceedings)
- PCT/International codes (focus on US prosecution)"""

def _get_workflows_pfw_section() -> str:
    """PFW-only workflows section"""
    return """## Patent Attorney Workflows (PFW Only)

### Litigation Research Workflow
**Scenario:** Responding to validity challenge or preparing patent enforcement

**Steps:**
1. **Find target patent**: `search_applications_balanced(query='applicationNumberText:16123456')`
2. **Get prosecution docs**: `get_application_documents(app_number='16123456')`
3. **Extract examiner reasoning**: Focus on NOA and final CTFR documents
4. **Analyze prior art**: Get 892 documents for examiner's search strategy
5. **Compare arguments**: Extract N417 responses to understand prosecution strategy

**Key Intelligence:** Examiner's allowance reasoning vs. challenger's arguments

### Due Diligence Workflow
**Scenario:** M&A patent portfolio assessment

**Steps:**
1. **Portfolio discovery**: `search_applications_minimal(applicant_name='Target Company', limit=100)`
2. **Quality assessment**: Use balanced search for high-value patents
3. **Red flag detection**: Look for multiple rejections, long prosecution, revival petitions
4. **Document analysis**: Extract NOAs and office actions for prosecution quality
5. **Risk scoring**: Combine prosecution timeline + examiner analysis + document quality

**Risk Indicators:** Multiple CTFRs, long timeline, examiner interview frequency"""

def _get_errors_section() -> str:
    """Common error patterns and troubleshooting"""
    return """## Common Error Patterns & Solutions

### Search Errors

#### "No results found"
**Causes:**
- Incorrect application number format
- Patent not yet published or granted
- Search scope too narrow

**Solutions:**
- Use `search_applications_minimal` with broader query
- Try inventor or applicant name search
- Check application status and publication dates

#### "Field not recognized"
**Causes:**
- Incorrect field name syntax
- Custom field not in available set

**Solutions:**
- Use convenience parameters instead (applicant_name, examiner_name)
- Check field_configs.yaml for available custom fields
- Use preset field sets (minimal/balanced)

### Document Access Errors

#### "Document not available"
**Causes:**
- Document not yet digitized (pre-2001 applications)
- Access restrictions on certain document types

**Solutions:**
- Try XML content first for patents/applications
- Use document download for browser access
- Check document metadata for availability indicators

#### "Proxy links don't work"
**Cause:** Proxy server not started before generating links

**Solution:** Document download tools automatically start proxy server"""

def _get_fields_section() -> str:
    """Field selection strategies and context reduction"""
    return """## Field Selection & Context Reduction

### Progressive Disclosure Strategy

#### Stage 1: Discovery (95-99% reduction)
**Minimal Search (15 preset fields ~500 chars/result):**
- `search_applications_minimal` with default fields
- Good for 20-50 results

**Ultra-Minimal (2-3 custom fields ~100 chars/result):**
- `fields=["applicationNumberText", "inventionTitle"]`
- Perfect for 50-200 results
- 99% context reduction vs balanced

#### Stage 2: Analysis (85-95% reduction)
**Balanced Search (18+ fields ~2KB/result):**
- Cross-MCP integration fields
- Detailed metadata for user-selected applications
- Limit to 10-20 results

### Essential Field Combinations

#### Cross-MCP Integration
```python
# For PTAB integration
fields=["applicationNumberText", "patentNumber", "examinerNameText", "groupArtUnitNumber"]

# For Citations integration
fields=["applicationNumberText", "examinerNameText", "groupArtUnitNumber", "filingDate"]

# For FPD integration
fields=["applicationNumberText", "applicationStatus", "examinerNameText"]
```

### Convenience Parameters vs Custom Fields

#### Use Convenience Parameters When:
- Simple searches without complex Boolean logic
- Standard filtering (applicant, inventor, examiner, date ranges)
- New user or quick exploration

#### Use Custom Fields When:
- Ultra-minimal context usage required
- Specific workflow requirements
- Processing 50+ results efficiently"""

def _get_cost_section() -> str:
    """Cost optimization strategies"""
    return """## Cost Optimization Strategies

### Document Extraction Costs

#### Free Methods (Always Try First)
1. **XML Content**: `get_patent_or_application_xml`
   - Patents and published applications
   - Structured data with claims, description, citations
   - No cost, fastest access

2. **PyPDF2 Extraction**: Automatic fallback in document tools
   - Works for 80%+ of patent documents
   - Free text extraction from PDFs
   - No OCR costs

#### Paid OCR (Only When Necessary)
**Mistral OCR**: ~$0.001-0.003 per document
- Used only for scanned/poor quality documents
- Automatic quality detection prevents unnecessary costs
- Cost transparency before extraction

### API Call Optimization

#### Progressive Disclosure (95% cost reduction)
```python
# Instead of expensive balanced search for discovery
results = search_applications_balanced(query="AI healthcare", limit=50)  # 100KB context

# Do efficient progressive disclosure
discovery = search_applications_minimal(query="AI healthcare", limit=50)  # 25KB context
# User selects 5 results
detailed = search_applications_balanced(selected_apps, limit=5)  # 10KB context
# Total: 35KB vs 100KB (65% reduction)
```

### Strategic Document Selection
1. **NOA** (Notice of Allowance): Examiner's final reasoning
2. **Final CTFR**: Last office action with complete analysis
3. **892** (Examiner Citations): Prior art search methodology
4. **Key N417**: Critical applicant responses"""

def _get_workflows_ptab_section() -> str:
    """PTAB integration workflows"""
    return """## PTAB Integration Workflows

### PTAB to PFW Linking
**Scenario:** Starting from PTAB proceeding, need prosecution history

**Workflow:**
1. **Find PTAB proceeding**: `ptab_search_proceedings_balanced(patent_number='11123456')`
2. **Extract application number** from PTAB metadata (`applicationNumberText`)
3. **Get prosecution history**: `search_applications_balanced(query='applicationNumberText:16123456')`
4. **Document analysis**: `get_application_documents(app_number='16123456')`
5. **Compare reasoning**: Extract NOA vs PTAB decision analysis

**Key Fields:** applicationNumberText, patentNumber, examinerNameText, groupArtUnitNumber"""

def _get_workflows_fpd_section() -> str:
    """FPD integration workflows"""
    return """## FPD Integration Workflows

### FPD Red Flag Detection
**Scenario:** Identify prosecution quality issues via petition history

**Workflow:**
1. **Portfolio scan**: `search_applications_minimal(applicant_name='Target', limit=100)`
2. **FPD check**: For each application, `fpd_search_petitions_by_application(app_number)`
3. **Red flag analysis**: Identify denied petitions, revival petitions, appeal petitions
4. **Prosecution correlation**: Get PFW data for applications with petition issues
5. **Risk assessment**: Combine petition history + prosecution timeline analysis

**High-Risk Indicators:**
- Denied petitions (serious prosecution issues)
- Revival petitions (missed deadlines)
- Multiple appeal petitions (examiner relationship problems)"""

def _get_workflows_citations_section() -> str:
    """Citations integration workflows"""
    return """## Citations Integration Workflows

### Citation-Enhanced Prior Art Analysis
**Scenario:** Advanced prior art research using examiner citation intelligence

**Workflow:**
1. **Technology Discovery**: `search_applications_minimal(query='autonomous vehicle', art_unit='3661', limit=50)`
2. **Citation Analysis**: For applications with office actions (2017+), get citation data
3. **Examiner Intelligence**: Focus on `examinerCitedReferenceIndicator=true` references
4. **Art Unit Patterns**: Identify frequently cited references in specific art units
5. **Effectiveness Assessment**: Correlate citation patterns with prosecution outcomes

**Enhanced Insights:** Citation patterns reveal examiner search preferences and reference effectiveness"""

def _get_workflows_complete_section() -> str:
    """Complete four-MCP lifecycle workflows"""
    return """## Complete Four-MCP Lifecycle Analysis

### Complete M&A Due Diligence
**Scenario:** Comprehensive patent intelligence across all USPTO databases

**Four-MCP Integration Workflow:**
1. **Portfolio Discovery (PFW)**: `search_applications_minimal(applicant_name='Target Company', filing_date_start='2015-01-01', limit=100)`
2. **Citation Intelligence (Citations)**: Analyze examiner citation patterns for prosecution quality (2017+ applications)
3. **FPD Risk Assessment (FPD)**: Check procedural irregularities and petition history
4. **PTAB Challenge Analysis (PTAB)**: Assess post-grant challenge exposure for granted patents
5. **Document Intelligence (PFW)**: Extract key prosecution documents for detailed analysis
6. **Comprehensive Reporting**: Integrate findings across all four data sources

**Enhanced Risk Scoring Matrix:**
- **Technical Strength**: Claim scope, prosecution quality, prior art landscape
- **Legal Enforceability**: Citation thoroughness, procedural cleanliness
- **Challenge Exposure**: PTAB proceedings history and outcomes
- **Procedural Issues**: FPD petition patterns and denial history"""

def _get_workflows_pinecone_section() -> str:
    """Pinecone RAG/Assistant domain-based strategic search integration"""
    return """## Pinecone RAG/Assistant Integration - Domain-Based Strategic Search

### Overview: Why Domain-Based Search?

**Problem with Generic Technology Searches:**
- RAG database contains MPEP, case law, examination procedures (legal framework)
- RAG does NOT contain technology-specific prior art
- Generic searches like "catalytic converter bend radius MPEP" return low-value generic guidance

**Solution: Domain-Based Legal Framework Searches:**
- Focus RAG on legal issue (§101, §103, §112) instead of technology
- Get targeted MPEP sections and case law for specific vulnerabilities
- Improved RAG value: 5-10% → 40-60% (estimated)

**Key Principle:**
- **Pinecone RAG/Assistant**: Legal framework (MPEP, case law, procedures) organized by domain
- **USPTO Citations MCP**: Technology-specific prior art

---

### 9 Patent Law Domains

#### Legal Issue Domains (Primary)

**1. section_101_eligibility** - Alice/Mayo Framework
- **When to Use**: Software patents, AI/ML inventions, business methods, abstract idea challenges
- **Search Focus**: Alice/Mayo two-step framework, technological improvement, inventive concept, judicial exceptions
- **Example Searches**: "Section 101 Alice Mayo two-step framework abstract idea", "practical application technological improvement"

**2. section_103_obviousness** - KSR/Graham Factors
- **When to Use**: Combination rejections, motivation to combine issues, mechanical/chemical patents
- **Search Focus**: KSR rationales (7 types), Graham factors, secondary considerations, teaching away
- **Example Searches**: "Section 103 KSR motivation to combine obviousness rationales", "Graham factors scope prior art differences POSITA"

**3. section_112_requirements** - Specification Requirements
- **When to Use**: Indefiniteness challenges ("substantially", "about"), enablement issues, written description
- **Search Focus**: Nautilus standard, written description possession, enablement Wands factors, means-plus-function
- **Example Searches**: "Section 112 indefiniteness Nautilus reasonable certainty", "written description possession requirement"

**4. section_102_novelty** - Anticipation
- **When to Use**: Single reference rejections, inherent disclosure arguments, anticipation challenges
- **Search Focus**: Anticipation standards, inherent disclosure, prior art effective dates (AIA vs pre-AIA)
- **Example Searches**: "Section 102 anticipation single reference prior art disclosure", "inherent disclosure anticipation"

**5. claim_construction** - Claim Interpretation
- **When to Use**: Phillips standard analysis, means-plus-function claims, functional claiming, prosecution history estoppel
- **Search Focus**: Phillips v. AWH standard, intrinsic/extrinsic evidence, prosecution history limits
- **Example Searches**: "claim construction Phillips intrinsic extrinsic evidence", "prosecution history estoppel argument-based"

**6. ptab_procedures** - PTAB Trial Standards
- **When to Use**: IPR/PGR proceedings, PTAB appeal standards, institution decisions
- **Search Focus**: IPR petition standards, BRI vs Phillips, PTAB estoppel rules
- **Example Searches**: "IPR petition institution decision preponderance evidence BRI", "PTAB claim construction broadest reasonable interpretation"

#### Technology-Specific Domains (Secondary)

**7. mechanical_patents** - Mechanical/Manufacturing
- **When to Use**: TC 3600/3700 patents, manufacturing processes, mechanical devices
- **Search Focus**: Mechanical obviousness, design-around strategies, manufacturing process examination
- **Example Searches**: "mechanical device patent obviousness design around", "manufacturing process method claims patent examination"

**8. software_patents** - Software/AI Technology
- **When to Use**: TC 2100/2400 patents, computer-implemented inventions, AI/ML systems
- **Search Focus**: Software abstract idea analysis, AI practical application, business method eligibility
- **Example Searches**: "software patent 101 abstract idea Alice framework computer-implemented", "AI machine learning patent practical application"

**9. general_patent_law** - Default/Fallback
- **When to Use**: Unknown issues, multiple vulnerabilities, comprehensive overview
- **Search Focus**: General examination procedures, broad legal framework
- **Example Searches**: "{technology} patent examination MPEP guidance", "{technology} patent law legal framework precedent"

---

### Automatic Vulnerability Detection (Patent Invalidity Prompt)

The patent invalidity analysis prompt automatically detects vulnerabilities from prosecution history and selects the appropriate domain:

**Detection Indicators:**
```python
# § 102 Anticipation: "anticipates", "anticipated by", "102", "single reference"
→ Domain: section_102_novelty

# § 103 Obviousness: "obvious", "103", "combination", "motivation to combine", "KSR"
→ Domain: section_103_obviousness

# § 101 Eligibility: "abstract idea", "software", "computer-implemented", TC 2100/2400
→ Domain: section_101_eligibility

# § 112 Indefiniteness: "substantially", "approximately", "about", "configured to"
→ Domain: section_112_requirements

# Claim Construction: "means for", "means plus function", "112(f)", "112(6)"
→ Domain: claim_construction
```

---

### Usage Examples: Before vs After Domains

#### Example 1: § 103 Obviousness (Catalytic Converter Patent)

**❌ Before (Generic Technology Search):**
```python
strategic_multi_search(
    technology='catalytic converter exhaust pipe bend radius manufacturing process patent eligibility obviousness'
)
# Returns: "catalytic converter bend radius patent examination MPEP" (not useful)
# Value: 5-10% (generic principles user already knows)
```

**✅ After (Domain-Based Legal Framework):**
```python
strategic_multi_search(
    technology='catalytic converter exhaust system',
    domain='section_103_obviousness',
    topK=5,
    rerankerTopN=2
)
# Returns:
# - "Section 103 KSR motivation to combine obviousness rationales"
# - "Graham factors scope prior art differences POSITA"
# - "Section 103 secondary considerations commercial success teaching away"
# - "Section 103 combination prior art references motivation"
# Value: 40-60% (focused legal framework for exact issue)
```

#### Example 2: § 101 Software Patent Eligibility

**✅ Domain-Based Search:**
```python
strategic_multi_search(
    technology='AI-based medical diagnosis method',
    domain='section_101_eligibility',
    topK=5
)
# Returns:
# - "Section 101 Alice Mayo two-step framework abstract idea"
# - "Section 101 practical application technological improvement"
# - "Section 101 inventive concept significantly more Alice step two"
# - "Section 101 judicial exceptions abstract idea natural phenomenon"
```

#### Example 3: § 112(b) Indefiniteness

**✅ Domain-Based Search:**
```python
strategic_multi_search(
    technology='wireless proximity zone authentication system',
    domain='section_112_requirements',
    topK=5
)
# Returns:
# - "Section 112 indefiniteness Nautilus reasonable certainty"
# - "Section 112 paragraph f means-plus-function corresponding structure"
# - "Section 112 written description possession requirement"
# - "Section 112 enablement undue experimentation Wands factors"
```

---

### Cross-Workflow Integration

**Patent Invalidity Analysis (Primary Workflow):**
1. **PFW MCP**: Get prosecution history → Detect vulnerability
2. **Pinecone RAG/Assistant**: Execute domain-specific strategic search → Get legal framework
3. **Citations MCP**: Get technology-specific prior art → Prior art landscape
4. **PTAB MCP**: Get PTAB decisions → Real-world precedents
5. **FPD MCP**: Get petition history → Procedural issues

**M&A Due Diligence with Legal Framework:**
1. **PFW**: Portfolio discovery → Identify patents
2. **Pinecone RAG**: Domain searches for each patent's primary vulnerability
3. **Citations**: Examiner search patterns
4. **PTAB**: Challenge exposure assessment

**Litigation Research with Domain Focus:**
1. **PFW**: Prosecution history → Identify legal weaknesses
2. **Pinecone RAG**: Domain-specific legal framework for vulnerability
3. **PTAB**: Find IPR decisions on similar legal issues
4. **Citations**: Examiner's prior art thoroughness

---

### Domain Selection Decision Tree

```
Start: Analyze prosecution history from PFW
│
├─ Examiner cited "abstract idea" or TC 2100/2400?
│  → Domain: section_101_eligibility
│
├─ Examiner said "obvious" or "combination" or "KSR"?
│  → Domain: section_103_obviousness
│
├─ Examiner said "anticipates" or "single reference"?
│  → Domain: section_102_novelty
│
├─ Claims use "substantially", "approximately", "about"?
│  → Domain: section_112_requirements
│
├─ Claims use "means for" or functional language?
│  → Domain: claim_construction
│
├─ Facing IPR/PGR or PTAB challenge?
│  → Domain: ptab_procedures
│
├─ Mechanical/manufacturing invention?
│  → Domain: mechanical_patents
│
├─ Software/AI invention?
│  → Domain: software_patents
│
└─ Unknown or multiple issues?
   → Domain: general_patent_law (fallback)
```

---

### Tool Integration

**Pinecone RAG MCP:**
```python
# Domain-specific strategic multi-search
strategic_multi_search(
    technology=invention_title,
    domain='section_103_obviousness',
    topK=5,
    rerankerTopN=2
)
```

**Pinecone Assistant MCP:**
```python
# Domain-specific context retrieval with strategic search
assistant_strategic_multi_search_context(
    query=invention_title,
    domain='section_103_obviousness',
    top_k=5,
    snippet_size=2048,
    max_searches=4,
    temperature=0.3
)

# Single domain-specific query
assistant_context(
    query='KSR motivation to combine predictable results',
    top_k=5,
    snippet_size=2048
)
```

---

### Benefits Summary

**Before Domain System:**
- 5-10% value from RAG
- Generic legal principles user already knows
- Technology terms don't match legal framework content
- RAG searches compete with technology prior art (Citations MCP)

**After Domain System:**
- 40-60% estimated value from RAG
- Specific MPEP sections and case law for exact legal issue
- Technology-agnostic legal framework matches RAG content
- Clear separation: RAG = legal framework, Citations = prior art

**Strategic Advantage:**
- Automatic vulnerability detection from prosecution history
- Focused legal research on primary issue
- Cross-MCP integration for complete analysis
- Scalable to new domains (appeals, litigation, etc.)"""

def _get_advanced_section() -> str:
    """Advanced workflows and optimization"""
    return """## Advanced Workflows & Optimization

### Patent Family Analysis
**Multi-application analysis for related inventions**

**Advanced Workflow:**
1. **Family Discovery**: Search by inventor, assignee, priority claims, or technology keywords
2. **Relationship Mapping**: Identify continuations, divisionals, continuations-in-part
3. **Prosecution Comparison**: Analyze different examiner approaches across family members
4. **Claim Evolution**: Track claim scope changes and strategic amendments
5. **Strategic Insights**: Identify strongest family member and optimal prosecution paths
6. **Cross-Reference Analysis**: Use PTAB/FPD data to assess family-wide vulnerabilities

**Strategic Value:** Comprehensive family strategy with prosecution pattern optimization"""

async def run_hybrid_server():
    """Run both MCP server and HTTP proxy server concurrently"""
    import os
    try:
        # Start both servers concurrently
        logger.info("Starting hybrid MCP + HTTP proxy server")

        # Check if always-on proxy is enabled (default: true)
        enable_always_on_proxy = os.getenv("ENABLE_ALWAYS_ON_PROXY", "true").lower() == "true"
        # Check PFW_PROXY_PORT first (MCP-specific), then PROXY_PORT (generic)
        proxy_port = int(os.getenv('PFW_PROXY_PORT', os.getenv('PROXY_PORT', 8080)))

        if enable_always_on_proxy:
            logger.info("Always-on proxy mode enabled - starting proxy server immediately")
            # Start proxy server immediately for Resources and persistent links
            await _ensure_proxy_server_running(proxy_port)
        else:
            logger.info("On-demand proxy mode - proxy will start when first download is requested")

        # Run MCP server in a separate task
        mcp_task = asyncio.create_task(
            asyncio.to_thread(lambda: mcp.run(transport='stdio'))
        )

        # Add error handler to catch MCP task failures
        mcp_task.add_done_callback(_handle_background_task_exception)

        # Wait for MCP server to complete (it runs indefinitely)
        await mcp_task

    except KeyboardInterrupt:
        logger.info("Shutting down servers...")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise

def _asyncio_exception_handler(loop, context):
    """
    Global exception handler for asyncio event loop

    Catches unhandled exceptions in async tasks and coroutines
    to prevent silent failures.

    Args:
        loop: The event loop where the exception occurred
        context: Dictionary with exception information
    """
    exception = context.get('exception')
    message = context.get('message', 'Unhandled exception in async task')

    if exception:
        logger.exception(
            f"Uncaught async exception: {message}",
            exc_info=(type(exception), exception, exception.__traceback__)
        )
    else:
        logger.error(f"Async error: {message}")

    # Log full context for debugging
    logger.error(f"Async error context: {context}")


def main():
    """
    Main entry point for the MCP server

    Environment Variables:
    - ENABLE_PROXY_SERVER: Enable/disable proxy functionality (default: true)
    - ENABLE_ALWAYS_ON_PROXY: Start proxy immediately vs on-demand (default: true)
    - PFW_PROXY_PORT: MCP-specific proxy server port (takes precedence)
    - PROXY_PORT: Generic proxy server port (fallback, default: 8080)
    """
    logger.info("Starting Enhanced Patent File Wrapper MCP server with proxy support")

    # Check if we should run with proxy support
    import os
    enable_proxy = os.getenv("ENABLE_PROXY_SERVER", "true").lower() == "true"

    if enable_proxy:
        # Set global exception handler for asyncio event loop
        # This must be done before asyncio.run() creates the loop
        loop = asyncio.new_event_loop()
        loop.set_exception_handler(_asyncio_exception_handler)
        asyncio.set_event_loop(loop)

        try:
            # Run hybrid server (MCP + HTTP proxy)
            loop.run_until_complete(run_hybrid_server())
        finally:
            loop.close()
    else:
        # Run MCP server only
        logger.info("Proxy server disabled via ENABLE_PROXY_SERVER=false")
        mcp.run(transport='stdio')

if __name__ == "__main__":
    main()
