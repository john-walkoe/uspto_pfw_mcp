"""
Helper functions for Patent File Wrapper MCP
"""
import re
import uuid
from typing import Dict, Any, List, Optional

from ..exceptions import ValidationError
from .field_constants import USPTOFields
from ..shared.safe_logger import get_safe_logger
from ..models.search_params import MAX_SEARCH_LIMIT as _MAX_SEARCH_LIMIT

logger = get_safe_logger(__name__)

def validate_app_number(app_number: str) -> str:
    """
    Validate and normalize application number

    Args:
        app_number: Raw application number

    Returns:
        Normalized application number

    Raises:
        ValidationError: If application number is invalid
    """
    if not app_number:
        raise ValidationError("Application number cannot be empty")

    # Remove common prefixes and clean up
    app_number = str(app_number).strip()
    app_number = re.sub(r'^(US|us)', '', app_number)
    app_number = re.sub(r'[^\d]', '', app_number)  # Keep only digits

    if not app_number:
        raise ValidationError("Application number must contain digits")

    if len(app_number) < 6:
        raise ValidationError("Application number too short")

    return app_number


def escape_lucene_query_term(term: str) -> str:
    """
    Escape special characters for Lucene query terms to prevent query injection.

    Lucene query syntax characters: + - && || ! ( ) { } [ ] ^ ~ * ? : " \

    Characters NOT escaped (safe in value positions):
    - Colon (:) - Used for field:value syntax. User input only in VALUE positions.
    - Quotes (") - We add quotes externally for phrase queries. Escaping would break them.
    - Brackets [, ] - Used for range queries. Safe in values (e.g., dates).
    - Dash (-) - Used in dates and ranges. Safe in values (e.g., "2024-01-01").
    - Asterisk (*) - Wildcard operator. If user wants wildcard, it's intentional.
    - Question mark (?) - Single-char wildcard. If user wants it, it's intentional.

    Args:
        term: User input term to be used in a Lucene query VALUE (not field name)

    Returns:
        Escaped term safe for use in Lucene queries
    """
    if not term:
        return term

    # Escape Lucene special characters by prefixing with backslash
    # Note: Backslash itself needs to be escaped first
    # Many characters are NOT escaped because they're legitimate query syntax or safe in values
    specials = r'[\\\+&|\!\(\)\{\}\^~]'
    escaped = re.sub(specials, lambda m: '\\' + m.group(0), str(term))

    # Additional validation - limit length to prevent DoS
    if len(escaped) > 1000:
        raise ValidationError(f"Query term too long after escaping: {len(escaped)} characters")

    return escaped


def sanitize_traceback(tb_str: str) -> str:
    """
    Remove sensitive information from tracebacks

    Sanitizes:
    - File paths (replaces usernames)
    - API keys and tokens
    - Environment variables that might contain secrets

    Args:
        tb_str: Original traceback string

    Returns:
        Sanitized traceback safe for logging
    """
    import re

    # Remove file paths - replace username
    tb_str = re.sub(r'/home/[^/]+/', '/home/USER/', tb_str)
    tb_str = re.sub(r'/Users/[^/]+/', '/Users/USER/', tb_str)
    tb_str = re.sub(r'C:\\Users\\[^\\]+\\', r'C:\\Users\\USER\\', tb_str)

    # Remove API keys (pattern: key=value with alphanumeric)
    tb_str = re.sub(
        r'(api[_-]?key|token|password|secret|auth)[=\s:][\'"]?[\w-]+',
        r'\1=***REDACTED***',
        tb_str,
        flags=re.IGNORECASE
    )

    # Remove environment variables that might contain keys
    tb_str = re.sub(
        r'(USPTO_API_KEY|MISTRAL_API_KEY|API_KEY)[=\s:][\'"]?[^\s\'",]+',
        r'\1=***REDACTED***',
        tb_str
    )

    return tb_str


def format_error_response(
    message: str,
    status_code: int = 500,
    request_id: Optional[str] = None,
    error_type: Optional[str] = None,
    actionable_guidance: Optional[str] = None,
    exception: Optional[Exception] = None
) -> Dict[str, Any]:
    """
    Format a consistent error response with environment-aware detail levels

    Provides different detail levels for development vs production:
    - Production: User-friendly message, guidance, request ID
    - Development: Same + exception details, sanitized traceback

    Args:
        message: Error message
        status_code: HTTP-style status code for error categorization
        request_id: Optional request ID for tracing
        error_type: Optional error type categorization
        actionable_guidance: Optional guidance on how to resolve the error
        exception: Optional exception for debug information (dev only)

    Returns:
        Formatted error response with enhanced metadata
    """

    if request_id is None:
        request_id = generate_request_id()

    response = {
        "error": True,
        "success": False,
        "status_code": status_code,
        "message": message,
        "request_id": request_id,
        "timestamp": import_time().strftime('%Y-%m-%dT%H:%M:%SZ', import_time().gmtime())
    }

    if error_type:
        response["error_type"] = error_type

    if actionable_guidance:
        response["guidance"] = actionable_guidance

    # Add debug info only in development
    if is_development() and exception:
        import traceback
        tb_str = traceback.format_exc()
        sanitized_tb = sanitize_traceback(tb_str)

        response["debug"] = {
            "exception_type": type(exception).__name__,
            "exception_args": str(exception.args),
            "traceback": sanitized_tb
        }

    return response


def import_time():
    """Import time module to avoid circular imports"""
    import time
    return time


def is_development() -> bool:
    """Single owner of the dev/prod switch (audit F27): controls whether
    error responses include debug detail. Anything not explicitly a dev
    environment is treated as production."""
    import os
    return os.getenv("ENVIRONMENT", "production").lower() in ["development", "dev", "local"]


# Error message templates with actionable guidance
#: Interpolated, not restated. `invalid_limit` said "between 1 and 500"
#: against a real ceiling of 100 (it went 1000 -> 100 in the 2026-08-21 bounds
#: pass and this string was not updated), and `invalid_inventor_name` said
#: "under 100 characters" against MAX_NAME_LENGTH = 200. guidance.py already
#: interpolates rather than restating; these two were the only holdouts
#: (audit D-10, R-6).
_MAX_NAME_LENGTH = 200  # mirrors EnhancedPatentClient.MAX_NAME_LENGTH

ERROR_TEMPLATES = {
    "invalid_app_number": {
        "message": "Invalid application number format",
        "guidance": "Application numbers should be 6+ digits (e.g., '17896175'). Remove any prefixes like 'US'."
    },
    "query_too_long": {
        "message": "Search query exceeds maximum length",
        "guidance": "Simplify your search query or use more specific terms. Consider using convenience parameters instead."
    },
    "invalid_limit": {
        "message": "Invalid limit parameter",
        "guidance": (
            f"Limit must be between 1 and {_MAX_SEARCH_LIMIT}. Values above the "
            "ceiling are clamped rather than rejected; see `limit_clamped` in "
            "the response. Use smaller values for faster responses."
        ),
    },
    "invalid_offset": {
        "message": "Invalid offset parameter",
        "guidance": "Offset must be non-negative. Start with offset=0 for the first page of results."
    },
    "empty_query": {
        "message": "No search criteria provided",
        "guidance": "Provide either a 'query' parameter or at least one convenience parameter (art_unit, examiner_name, etc.)"
    },
    "api_auth_failed": {
        "message": "USPTO API authentication failed",
        "guidance": "Check your USPTO_API_KEY environment variable. Get a free API key from developer.uspto.gov"
    },
    "api_timeout": {
        "message": "USPTO API request timed out",
        "guidance": "Try again with a smaller limit or simpler query. The USPTO API may be experiencing high load."
    },
    "invalid_inventor_name": {
        "message": "Invalid inventor name",
        "guidance": (
            f"Inventor name cannot be empty and must be under {_MAX_NAME_LENGTH} "
            "characters. Use format: 'Last, First' or 'First Last'."
        ),
    },
    "invalid_strategy": {
        "message": "Invalid search strategy",
        "guidance": "Strategy must be 'exact', 'fuzzy', or 'comprehensive'. Use 'comprehensive' for best results."
    },
    "rate_limit_exceeded": {
        "message": "Rate limit exceeded",
        "guidance": "Wait before making another request. USPTO allows 5 downloads per 10 seconds."
    },
    "document_not_found": {
        "message": "Document not found",
        "guidance": "Verify the application number and document identifier. The document may not be publicly available."
    },
    "validation_error": {
        "message": "Request validation failed",
        "guidance": (
            "Check the parameter named in the message against the tool's "
            "schema. Identifiers accept a serial (with or without the slash, "
            "e.g. 11/752,072) or a patent number; dates are YYYY-MM-DD."
        ),
    },
    "missing_field": {
        "message": "Required field missing",
        "guidance": (
            "The message names the field. If it names a USPTO response field "
            "rather than one of your parameters, this is a server-side "
            "problem, not a problem with your request."
        ),
    },
}


def create_error_response(error_key: str, custom_message: Optional[str] = None,
                         status_code: int = 400, request_id: Optional[str] = None,
                         additional_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Create standardized error response using predefined templates

    Args:
        error_key: Key for error template
        custom_message: Optional custom message to override template
        status_code: HTTP-style status code
        request_id: Request ID for tracing
        additional_context: Additional context to include in error

    Returns:
        Formatted error response with guidance
    """
    template = ERROR_TEMPLATES.get(error_key, {
        "message": "An error occurred",
        "guidance": "Please check your request parameters and try again."
    })

    message = custom_message or template["message"]
    guidance = template.get("guidance")

    response = format_error_response(
        message=message,
        status_code=status_code,
        request_id=request_id,
        error_type=error_key,
        actionable_guidance=guidance
    )

    if additional_context:
        response.update(additional_context)

    return response

def generate_request_id() -> str:
    """Generate a unique request ID for tracing"""
    return str(uuid.uuid4())[:8]  # Short UUID for readability

#: How many of the generated name-variant queries the inventor fan-out will
#: actually execute. A "comprehensive" search on a 3-part name generates up to
#: 14 unique variants, so the cap silently dropped 4 of them — a RECALL bug:
#: applications matched only by a dropped variant never appeared, and nothing
#: in the response said so. The cap itself is kept (each variant is a separate
#: USPTO round trip under a shared per-key rate limit); what changed is that
#: `create_inventor_queries(..., with_totals=True)` now also returns how many
#: were GENERATED, so search_inventor can report queries_generated vs
#: queries_executed instead of hiding the gap.
MAX_INVENTOR_QUERIES = 10


def create_inventor_queries(
    name: str, strategy: str = "comprehensive", with_totals: bool = False
):
    """
    Create multiple search queries for inventor name using Patent File Wrapper API fields

    Args:
        name: Inventor name
        strategy: Search strategy
        with_totals: When True, return ``(queries, queries_generated)`` where
            ``queries_generated`` is the pre-cap count of unique variants, so
            the caller can report the recall gap. Default False keeps the
            historical ``List[str]`` return.

    Returns:
        List of search queries to try, or ``(queries, queries_generated)``
    """
    queries = []

    # Clean up the name and escape it for Lucene queries
    clean_name = name.strip()
    escaped_name = escape_lucene_query_term(clean_name)

    if strategy == "exact":
        queries = [
            f'{USPTOFields.INVENTOR_NAME_TEXT}:"{escaped_name}"',
            f'{USPTOFields.FIRST_INVENTOR_NAME}:"{escaped_name}"'
        ]
    elif strategy == "fuzzy":
        # Create variations
        name_parts = clean_name.split()
        escaped_parts = [escape_lucene_query_term(part) for part in name_parts]

        queries = [
            f'{USPTOFields.INVENTOR_NAME_TEXT}:{escaped_name}',
            f'{USPTOFields.FIRST_INVENTOR_NAME}:{escaped_name}',
        ]

        # Add wildcard variations
        if len(escaped_parts) >= 2:
            queries.extend([
                f'{USPTOFields.INVENTOR_NAME_TEXT}:{escaped_parts[0]}* AND {escaped_parts[-1]}*',
                f'{USPTOFields.INVENTOR_NAME_TEXT}:({" OR ".join(escaped_parts)})',
            ])

    else:  # comprehensive
        name_parts = clean_name.split()
        escaped_parts = [escape_lucene_query_term(part) for part in name_parts]

        queries = [
            # Exact matches with quotes
            f'{USPTOFields.INVENTOR_NAME_TEXT}:"{escaped_name}"',
            f'{USPTOFields.FIRST_INVENTOR_NAME}:"{escaped_name}"',

            # Partial matches without quotes
            f'{USPTOFields.INVENTOR_NAME_TEXT}:{escaped_name}',
            f'{USPTOFields.FIRST_INVENTOR_NAME}:{escaped_name}',
        ]

        # Add name variations
        if len(escaped_parts) >= 2:
            first_name = escaped_parts[0]
            last_name = escaped_parts[-1]

            # Try different name orders and combinations
            queries.extend([
                f'{USPTOFields.INVENTOR_NAME_TEXT}:{first_name}* AND {last_name}*',
                f'{USPTOFields.INVENTOR_NAME_TEXT}:"{first_name} {last_name}"',
                f'{USPTOFields.FIRST_INVENTOR_NAME}:"{first_name} {last_name}"',
                f'{USPTOFields.INVENTOR_NAME_TEXT}:{last_name}* AND {first_name}*',
            ])

            # Add middle initial variations if there are 3+ parts
            if len(name_parts) >= 3:
                middle = name_parts[1]
                queries.extend([
                    f'{USPTOFields.INVENTOR_NAME_TEXT}:"{first_name} {middle} {last_name}"',
                    f'{USPTOFields.INVENTOR_NAME_TEXT}:"{first_name} {middle[0]}. {last_name}"',
                ])

        # Add wildcard searches
        if clean_name:
            queries.append(f'{USPTOFields.INVENTOR_NAME_TEXT}:{clean_name}*')

    # Remove duplicates while preserving order
    seen = set()
    unique_queries = []
    for query in queries:
        if query not in seen:
            seen.add(query)
            unique_queries.append(query)

    executed = unique_queries[:MAX_INVENTOR_QUERIES]
    if with_totals:
        return executed, len(unique_queries)
    return executed

def format_application_summary(app_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format application data into a readable summary for Patent File Wrapper data

    Args:
        app_data: Raw application data from Patent File Wrapper API

    Returns:
        Formatted summary
    """
    try:
        metadata = app_data.get('applicationMetaData', {})

        summary = {
            "application_number": app_data.get('applicationNumberText', 'N/A'),
            "patent_number": metadata.get('patentNumber', 'N/A'),
            "title": metadata.get('inventionTitle', 'N/A'),
            "filing_date": metadata.get('filingDate', 'N/A'),
            "grant_date": metadata.get('grantDate', 'N/A'),
            "status": metadata.get('applicationStatusDescriptionText', 'N/A'),
            "status_code": metadata.get('applicationStatusCode', 'N/A'),
            "first_inventor": metadata.get('firstInventorName', 'N/A'),
            "inventors": [],
            "applicants": [],
            "classification": {
                "uspc": metadata.get('uspcSymbolText', 'N/A'),
                "cpc": metadata.get('cpcClassificationBag', [])
            },
            "entity_status": metadata.get('entityStatusData', {}).get('businessEntityStatusCategory', 'N/A'),
            "customer_number": metadata.get('customerNumber', 'N/A'),
            "examiner": metadata.get('examinerNameText', 'N/A'),
            "group_art_unit": metadata.get('groupArtUnitNumber', 'N/A')
        }

        # Extract inventors
        inventor_bag = metadata.get('inventorBag', [])
        for inventor in inventor_bag:
            if isinstance(inventor, dict):
                name = inventor.get('inventorNameText', 'N/A')
                summary["inventors"].append(name)

        # Extract applicants
        applicant_bag = metadata.get('applicantBag', [])
        for applicant in applicant_bag:
            if isinstance(applicant, dict):
                name = applicant.get('applicantNameText', 'N/A')
                summary["applicants"].append(name)

        # Add publication info if available
        if metadata.get('publicationDateBag'):
            summary["publication_date"] = metadata.get('publicationDateBag', [])[0] if metadata.get('publicationDateBag') else 'N/A'
            summary["publication_number"] = metadata.get('earliestPublicationNumber', 'N/A')

        return summary

    except Exception as e:
        logger.warning(f"Error formatting application summary: {e}")
        return {"error": f"Failed to format summary: {str(e)}"}

# =============================================================================
# Family (continuity + foreign priority) normalization
#
# The ODP /continuity response is two raw bags (parentContinuityBag,
# childContinuityBag) that repeat the same application numbers with different
# key names per direction. These helpers turn one or more of those responses
# into a single compact node/edge graph the family tool and its MCP App view
# both consume, and are the unit-testable home of that logic.
# =============================================================================

def _clean_continuity_number(value: Any) -> Optional[str]:
    """Normalize an application number out of a continuity bag entry."""
    if value is None:
        return None
    text = re.sub(r'[^\d]', '', str(value))
    return text or None


def _family_node(application_number: str, is_queried: bool = False) -> Dict[str, Any]:
    """Empty node skeleton — fields fill in as continuity entries are read."""
    return {
        "application_number": application_number,
        "patent_number": None,
        "filing_date": None,
        "status": None,
        "status_code": None,
        "is_queried": is_queried,
    }


def _merge_node_fields(node: Dict[str, Any], **fields: Any) -> None:
    """Fill only the empty fields — the first non-null value observed wins,
    so a depth-2 expansion enriches a node without overwriting depth-1 data."""
    for key, value in fields.items():
        if value not in (None, "") and node.get(key) in (None, ""):
            node[key] = value


def _add_family_edge(
    edges: Dict[tuple, Dict[str, Any]],
    parent_app: str,
    child_app: str,
    entry: Dict[str, Any],
) -> None:
    """Record one parent->child continuity relation, de-duplicated on
    (parent, child, claimParentageTypeCode)."""
    code = entry.get('claimParentageTypeCode')
    code = str(code).strip().upper() if code else None
    key = (parent_app, child_app, code)
    if key in edges:
        return
    edges[key] = {
        "parent_app": parent_app,
        "child_app": child_app,
        "relation_type": code,
        "claim_parentage_type_code": entry.get('claimParentageTypeCode'),
        "description": entry.get('claimParentageTypeCodeDescriptionText'),
    }


def _walk_to_roots(start: str, parents_of: Dict[str, set]) -> List[str]:
    """Walk parent edges from `start` up to the EARLIEST ancestors present in
    the graph — every node with no parent edge of its own.

    The naive predecessor of this helper took parent_continuity[0] as the
    family root, which is wrong twice over: a bag can list several parents
    (a CIP claiming benefit of two applications) and the first entry is not
    ordered by filing date. Cycles cannot occur in real continuity data but
    the visited set makes malformed data terminate anyway.
    """
    roots: List[str] = []
    seen = {start}
    queue = [start]
    while queue:
        current = queue.pop(0)
        parents = parents_of.get(current) or set()
        if not parents:
            if current not in roots:
                roots.append(current)
            continue
        for parent in sorted(parents):
            if parent not in seen:
                seen.add(parent)
                queue.append(parent)
    return roots


def normalize_foreign_priority(bag: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Flatten an ODP foreignPriorityBag to {country, application_number, filing_date}."""
    normalized = []
    for entry in bag or []:
        if not isinstance(entry, dict):
            continue
        normalized.append({
            "country": entry.get('ipOfficeName'),
            "application_number": entry.get('applicationNumberText'),
            "filing_date": entry.get('filingDate'),
        })
    return normalized


class _FamilyAccumulator:
    """Collects nodes, edges and adjacency while continuity records are read.

    Both ODP bags describe the SAME parent->child relation under different key
    names, so each direction is read with its own key map into one shared graph.
    """

    # (bag key, id key for this side, id key for the other side, node field map)
    _PARENT_SIDE = (
        'parent_continuity_bag',
        'parentApplicationNumberText',
        'childApplicationNumberText',
        {
            "patent_number": 'parentPatentNumber',
            "filing_date": 'parentApplicationFilingDate',
            "status": 'parentApplicationStatusDescriptionText',
            "status_code": 'parentApplicationStatusCode',
        },
    )
    _CHILD_SIDE = (
        'child_continuity_bag',
        'childApplicationNumberText',
        'parentApplicationNumberText',
        {
            "patent_number": 'childPatentNumber',
            "filing_date": 'childApplicationFilingDate',
            "status": 'childApplicationStatusDescriptionText',
            "status_code": 'childApplicationStatusCode',
        },
    )

    def __init__(self, queried_application: str):
        self.queried_application = queried_application
        self.nodes: Dict[str, Dict[str, Any]] = {
            queried_application: _family_node(queried_application, is_queried=True)
        }
        self.edges: Dict[tuple, Dict[str, Any]] = {}
        self.parents_of: Dict[str, set] = {}
        self.children_of: Dict[str, set] = {}

    def node(self, app_number: str) -> Dict[str, Any]:
        if app_number not in self.nodes:
            self.nodes[app_number] = _family_node(app_number)
        return self.nodes[app_number]

    def ingest(self, record: Any) -> None:
        """Read one get_continuity() response into the graph."""
        if not isinstance(record, dict):
            return
        record_app = _clean_continuity_number(record.get('application_number'))
        self._ingest_side(record, record_app, self._PARENT_SIDE, described_is_parent=True)
        self._ingest_side(record, record_app, self._CHILD_SIDE, described_is_parent=False)

    def _ingest_side(self, record, record_app, side, described_is_parent: bool) -> None:
        bag_key, self_key, other_key, field_map = side
        for entry in record.get(bag_key) or []:
            if not isinstance(entry, dict):
                continue
            described = _clean_continuity_number(entry.get(self_key))
            counterpart = _clean_continuity_number(entry.get(other_key)) or record_app
            if not described or not counterpart:
                continue

            _merge_node_fields(
                self.node(described),
                **{field: entry.get(key) for field, key in field_map.items()},
            )
            self.node(counterpart)

            parent_app = described if described_is_parent else counterpart
            child_app = counterpart if described_is_parent else described
            _add_family_edge(self.edges, parent_app, child_app, entry)
            self.parents_of.setdefault(child_app, set()).add(parent_app)
            self.children_of.setdefault(parent_app, set()).add(child_app)


def _family_direction_notes(
    queried_application: str,
    queried_record: Optional[Dict[str, Any]],
    direct_parents: List[str],
    direct_children: List[str],
) -> List[str]:
    """State each empty direction explicitly, distinguishing an ABSENT bag
    (a real "no parents"/"no children" answer) from an empty one."""
    notes = []
    if not direct_parents:
        if queried_record is not None and not queried_record.get('parent_bag_present'):
            notes.append(
                f"parents: none — USPTO returned no parentContinuityBag for {queried_application}. "
                "This application claims no domestic benefit of an earlier US application; "
                "it is an answer, not missing data."
            )
        else:
            notes.append(
                f"parents: none — parentContinuityBag was empty for {queried_application}."
            )
    if not direct_children:
        if queried_record is not None and not queried_record.get('child_bag_present'):
            notes.append(
                f"children: none — USPTO returned no childContinuityBag for {queried_application}. "
                "No continuation, divisional or CIP claims benefit of it; it is an answer, "
                "not missing data."
            )
        else:
            notes.append(
                f"children: none — childContinuityBag was empty for {queried_application}."
            )
    return notes


def _foreign_priority_notes(
    queried_application: str,
    foreign_priority: List[Dict[str, Any]],
    requested: bool,
    available: bool,
) -> List[str]:
    """Distinguish "not asked for" and "call failed" from "none claimed"."""
    if not requested:
        return [
            "foreign_priority: not requested (include_foreign_priority=False) — "
            "absence here says nothing about whether foreign priority is claimed."
        ]
    if not available:
        return [
            "foreign_priority: unavailable — the /foreign-priority call did not succeed. "
            "Absence here says nothing about whether foreign priority is claimed."
        ]
    if not foreign_priority:
        return [
            f"foreign_priority: none — USPTO reports no foreign priority claim for "
            f"{queried_application}."
        ]
    return []


def build_family_graph(
    queried_application: str,
    continuity_records: List[Dict[str, Any]],
    foreign_priority_bag: Optional[List[Dict[str, Any]]] = None,
    foreign_priority_requested: bool = True,
    foreign_priority_available: bool = True,
) -> Dict[str, Any]:
    """
    Normalize one or more ODP /continuity responses into a compact family graph.

    Args:
        queried_application: The application the caller asked about (normalized digits)
        continuity_records: One dict per /continuity call, each shaped like
            EnhancedPatentClient.get_continuity's success response
            (application_number, parent_continuity_bag, child_continuity_bag,
            parent_bag_present, child_bag_present)
        foreign_priority_bag: Raw foreignPriorityBag entries, if fetched
        foreign_priority_requested: False when the caller opted out
        foreign_priority_available: False when the fetch failed

    Returns:
        Dict with nodes, edges, direct parents/children, roots, foreign_priority
        and per-direction emptiness notes.
    """
    graph = _FamilyAccumulator(queried_application)
    for record in continuity_records or []:
        graph.ingest(record)

    nodes = graph.nodes
    edges = graph.edges
    parents_of = graph.parents_of

    direct_parents = sorted(graph.parents_of.get(queried_application, set()))
    direct_children = sorted(graph.children_of.get(queried_application, set()))

    # Per-direction emptiness, taken from the QUERIED application's own record:
    # an absent bag is a real answer ("no parents"), not missing data.
    queried_record = next(
        (r for r in (continuity_records or [])
         if isinstance(r, dict)
         and _clean_continuity_number(r.get('application_number')) == queried_application),
        None,
    )
    notes = _family_direction_notes(
        queried_application, queried_record, direct_parents, direct_children
    )

    foreign_priority = normalize_foreign_priority(foreign_priority_bag)
    notes.extend(_foreign_priority_notes(
        queried_application, foreign_priority, foreign_priority_requested, foreign_priority_available
    ))

    # Roots first, then the queried application, then the rest — a stable order
    # that reads top-down as a generation list.
    roots = _walk_to_roots(queried_application, parents_of)
    ordered: List[Dict[str, Any]] = []
    for app_number in roots:
        ordered.append(nodes[app_number])
    if queried_application not in roots:
        ordered.append(nodes[queried_application])
    for app_number in sorted(nodes):
        if nodes[app_number] not in ordered:
            ordered.append(nodes[app_number])

    return {
        "queried_application": queried_application,
        "nodes": ordered,
        "edges": list(edges.values()),
        "parents": direct_parents,
        "children": direct_children,
        "roots": roots,
        "foreign_priority": foreign_priority,
        "counts": {
            "nodes": len(ordered),
            "edges": len(edges),
            "parents": len(direct_parents),
            "children": len(direct_children),
            "foreign_priority": len(foreign_priority),
        },
        "notes": notes,
    }


# =============================================================================
# Earliest priority date (OPEN_ITEMS #13)
#
# `applicationMetaData.effectiveFilingDate` is NOT the earliest priority date.
# Live-verified 2026-08-30: application 13975827 (US 9,135,462) reports
# effectiveFilingDate 2013-08-26, its own filing date, while its
# parentContinuityBag carries provisional 61/694,492 filed 2012-08-29 — almost
# a year earlier. For a 371 national-stage entry it is the entry date, and for
# a continuation it is the child's own filing date. Any AIA / prior-art
# qualification built on it inverts, so the earliest date is computed here from
# the priority chain itself and reported with the basis that produced it.
# =============================================================================

_ISO_DATE_RE = re.compile(r'^(\d{4}-\d{2}-\d{2})')

#: claimParentageTypeCode values that mean the parent is a provisional.
PROVISIONAL_PARENTAGE_CODES = {"PRO", "PRO/PCT"}


def normalize_priority_date(value: Any) -> Optional[str]:
    """An ISO date string (YYYY-MM-DD) from a USPTO date value, or None."""
    if not value:
        return None
    match = _ISO_DATE_RE.match(str(value).strip())
    return match.group(1) if match else None


def compute_earliest_priority(
    own_filing_date: Any = None,
    own_application_number: Optional[str] = None,
    parent_entries: Optional[List[Dict[str, Any]]] = None,
    foreign_priority: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Earliest date in the priority chain, and what produced it.

    Args:
        own_filing_date: the application's own filingDate
        own_application_number: for the basis string
        parent_entries: [{application_number, filing_date, relation_type}] — the
            domestic benefit chain, provisionals included
        foreign_priority: [{country, application_number, filing_date}]

    Returns:
        {earliest_priority_date, priority_basis, priority_candidates,
         priority_sources, priority_note}. `earliest_priority_date` is None when
        no date was available at all, and `priority_basis` says so — it is never
        silently filled from effectiveFilingDate.
    """
    candidates: List[Dict[str, Any]] = []

    own = normalize_priority_date(own_filing_date)
    if own:
        candidates.append({
            "date": own,
            "source": "own filing date",
            "application_number": own_application_number,
            "relation_type": None,
        })

    for entry in parent_entries or []:
        date = normalize_priority_date(entry.get("filing_date"))
        if not date:
            continue
        code = (entry.get("relation_type") or "").upper() or None
        kind = "provisional parent" if code in PROVISIONAL_PARENTAGE_CODES else "parent application"
        candidates.append({
            "date": date,
            "source": f"parentContinuityBag ({kind})",
            "application_number": entry.get("application_number"),
            "relation_type": code,
        })

    for entry in foreign_priority or []:
        date = normalize_priority_date(entry.get("filing_date"))
        if not date:
            continue
        candidates.append({
            "date": date,
            "source": f"foreignPriorityBag ({entry.get('country') or 'foreign'})",
            "application_number": entry.get("application_number"),
            "relation_type": None,
        })

    candidates.sort(key=lambda c: c["date"])
    note = (
        "earliest_priority_date is the MINIMUM over the foreign priority bag, the "
        "domestic parent continuity bag (provisionals included) and the application's "
        "own filing date. It is NOT applicationMetaData.effectiveFilingDate, which is "
        "the 371 national-stage ENTRY date for a national-stage case and the child's "
        "own filing date for a continuation, and therefore inverts AIA and prior-art "
        "qualification built on it. It is computed only from the chain links present "
        "in this response: a benefit claim USPTO did not return cannot be counted."
    )

    if not candidates:
        return {
            "earliest_priority_date": None,
            "priority_basis": "no filing or priority date was available to compute from",
            "priority_candidates": [],
            "priority_sources": [],
            "priority_note": note,
        }

    winner = candidates[0]
    where = f" {winner['application_number']}" if winner.get("application_number") else ""
    basis = f"{winner['source']}{where} filed {winner['date']}"
    return {
        "earliest_priority_date": winner["date"],
        "priority_basis": basis,
        "priority_candidates": candidates,
        "priority_sources": sorted({c["source"] for c in candidates}),
        "priority_note": note,
    }


def annotate_earliest_priority(applications: Optional[List[Dict[str, Any]]]) -> int:
    """Attach earliest_priority_date / priority_basis to each search hit.

    Reads only what the balanced field sets already request:
    applicationMetaData.filingDate, parentContinuityBag (application number,
    filing date, parentage code) and the TOP-LEVEL foreignPriorityBag. Returns
    how many records were annotated; a record with none of those fields is left
    untouched rather than annotated with a guess.
    """
    annotated = 0
    for app in applications or []:
        if not isinstance(app, dict):
            continue
        metadata = app.get('applicationMetaData') or {}
        parent_entries = [
            {
                "application_number": entry.get('parentApplicationNumberText'),
                "filing_date": entry.get('parentApplicationFilingDate'),
                "relation_type": entry.get('claimParentageTypeCode'),
            }
            for entry in (app.get('parentContinuityBag') or [])
            if isinstance(entry, dict)
        ]
        foreign = normalize_foreign_priority(app.get('foreignPriorityBag'))
        if not metadata.get('filingDate') and not parent_entries and not foreign:
            continue
        priority = compute_earliest_priority(
            own_filing_date=metadata.get('filingDate'),
            own_application_number=app.get('applicationNumberText'),
            parent_entries=parent_entries,
            foreign_priority=foreign,
        )
        app['earliest_priority_date'] = priority['earliest_priority_date']
        app['priority_basis'] = priority['priority_basis']
        annotated += 1
    return annotated


def _collect_parent_links(
    app: Dict[str, Any], app_number: str, parents_of: Dict[str, set]
) -> None:
    """Record child -> parent links from BOTH continuity bags of one search hit."""
    for bag_key, described_is_parent in (
        ('parentContinuityBag', True),
        ('childContinuityBag', False),
    ):
        for entry in app.get(bag_key) or []:
            if not isinstance(entry, dict):
                continue
            parent = _clean_continuity_number(entry.get('parentApplicationNumberText'))
            child = _clean_continuity_number(entry.get('childApplicationNumberText'))
            if described_is_parent:
                child = child or app_number
            else:
                parent = parent or app_number
            if parent and child:
                parents_of.setdefault(child, set()).add(parent)


def extract_patent_families(applications: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Group applications by patent family, keyed on the family's earliest ancestor.

    Root selection walks the parent chain across the supplied applications to
    the earliest ancestor rather than taking parentContinuityBag[0], which is
    neither the only parent nor ordered by filing date.

    Args:
        applications: List of application data from Patent File Wrapper API
            (each may carry parentContinuityBag / childContinuityBag)

    Returns:
        Dictionary of family root application number -> member applications
    """
    parents_of: Dict[str, set] = {}
    app_numbers: List[Optional[str]] = []

    for app in applications:
        try:
            app_number = _clean_continuity_number(app.get('applicationNumberText'))
            app_numbers.append(app_number)
            if app_number:
                _collect_parent_links(app, app_number, parents_of)
        except Exception as e:
            logger.warning(f"Error reading continuity data for family grouping: {e}")
            app_numbers.append(None)

    families: Dict[str, List[Dict[str, Any]]] = {}
    for app, app_number in zip(applications, app_numbers):
        if not app_number:
            families.setdefault('unknown', []).append(app)
            continue
        roots = _walk_to_roots(app_number, parents_of)
        family_id = roots[0] if roots else app_number
        families.setdefault(family_id, []).append(app)

    return families


PTA_HISTORY_DEFAULT_CAP = 20


def normalize_term_adjustment(
    adjustment_data: Optional[Dict[str, Any]],
    max_events: int = PTA_HISTORY_DEFAULT_CAP,
) -> Dict[str, Any]:
    """
    Flatten ODP patentTermAdjustmentData into a readable summary plus a capped
    event history.

    Field names are the ones the live ODP /adjustment endpoint returns:
    adjustmentTotalQuantity, aDelayQuantity, bDelayQuantity, cDelayQuantity,
    applicantDayDelayQuantity, overlappingDayQuantity, nonOverlappingDayDelayQuantity,
    ipOfficeAdjustmentDelayQuantity, and patentTermAdjustmentHistoryDataBag entries of
    eventDate / eventDescriptionText / eventSequenceNumber / originatingEventSequenceNumber /
    ptaPTECode / applicantDayDelayQuantity / ipOfficeDayDelayQuantity.

    No expiration date is computed — see PFW_get_term_adjustment's docstring.

    Args:
        adjustment_data: Raw patentTermAdjustmentData object (may be empty)
        max_events: Cap on returned history events (most recent first)

    Returns:
        Dict with an `adjustment` summary, `history` (capped), history counts and a note
    """
    data = adjustment_data if isinstance(adjustment_data, dict) else {}
    cap = max(1, int(max_events))

    summary = {
        "adjustment_total_days": data.get('adjustmentTotalQuantity'),
        "a_delay_days": data.get('aDelayQuantity'),
        "b_delay_days": data.get('bDelayQuantity'),
        "c_delay_days": data.get('cDelayQuantity'),
        "applicant_delay_days": data.get('applicantDayDelayQuantity'),
        "overlapping_days": data.get('overlappingDayQuantity'),
        "non_overlapping_delay_days": data.get('nonOverlappingDayDelayQuantity'),
        "ip_office_adjustment_delay_days": data.get('ipOfficeAdjustmentDelayQuantity'),
    }

    raw_history = [
        e for e in (data.get('patentTermAdjustmentHistoryDataBag') or [])
        if isinstance(e, dict)
    ]
    # ODP already returns newest-first; sort defensively so the cap always
    # keeps the most recent events whatever order the API used.
    ordered_history = sorted(
        raw_history,
        key=lambda e: (str(e.get('eventDate') or ''), _as_float(e.get('eventSequenceNumber'))),
        reverse=True,
    )

    history = [
        {
            "event_date": e.get('eventDate'),
            "description": e.get('eventDescriptionText'),
            "event_sequence_number": e.get('eventSequenceNumber'),
            "originating_event_sequence_number": e.get('originatingEventSequenceNumber'),
            "pta_pte_code": e.get('ptaPTECode'),
            "applicant_delay_days": e.get('applicantDayDelayQuantity'),
            "ip_office_delay_days": e.get('ipOfficeDayDelayQuantity'),
        }
        for e in ordered_history[:cap]
    ]

    result = {
        "adjustment": summary,
        "history": history,
        "history_returned": len(history),
        "history_total": len(ordered_history),
        "history_truncated": len(ordered_history) > len(history),
    }

    if result["history_truncated"]:
        result["history_note"] = (
            f"Showing the {len(history)} most recent of {len(ordered_history)} PTA history "
            "events. The full history exists at the USPTO ODP /adjustment endpoint; raise "
            "max_events to pull more."
        )
    if not data:
        result["note"] = (
            "USPTO returned no patentTermAdjustmentData for this application. PTA is "
            "computed at issuance, so pending and abandoned applications normally have none."
        )

    return result


def _as_float(value: Any) -> float:
    """Best-effort float for sorting PTA sequence numbers."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0

def format_document_summary(document: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format document data into a readable summary

    Args:
        document: Raw document data from Patent File Wrapper API

    Returns:
        Formatted document summary
    """
    try:
        download_options = document.get('downloadOptionBag', [])
        pdf_available = any(opt.get('mimeTypeIdentifier') == 'PDF' for opt in download_options)

        summary = {
            "document_code": document.get('documentCode', 'Unknown'),
            "description": document.get('documentCodeDescriptionText', ''),
            "official_date": document.get('officialDate', ''),
            "document_identifier": document.get('documentIdentifier', ''),
            "direction": document.get('directionCategory', ''),
            "pdf_available": pdf_available,
            "total_options": len(download_options),
            "page_count": None
        }

        # Get page count from PDF option if available
        for option in download_options:
            if option.get('mimeTypeIdentifier') == 'PDF':
                summary["page_count"] = option.get('pageTotalQuantity', 0)
                break

        return summary

    except Exception as e:
        logger.warning(f"Error formatting document summary: {e}")
        return {"error": f"Failed to format document summary: {str(e)}"}

def get_query_field_mapping() -> Dict[str, str]:
    """
    Get the mapping of user-friendly field names to USPTO API field names
    for use in both query construction and field selection.

    Returns:
        Dictionary mapping user-friendly names to API field names
    """
    return {
        # Top-level fields (no prefix needed)
        "applicationNumberText": USPTOFields.APPLICATION_NUMBER_TEXT,

        # ApplicationMetaData fields (need applicationMetaData. prefix)
        "inventionTitle": USPTOFields.INVENTION_TITLE,
        "patentNumber": USPTOFields.PATENT_NUMBER,
        "filingDate": USPTOFields.FILING_DATE,
        "grantDate": USPTOFields.GRANT_DATE,
        "applicationStatusDescriptionText": USPTOFields.APPLICATION_STATUS_DESCRIPTION_TEXT,
        "applicationStatusCode": USPTOFields.APPLICATION_STATUS_CODE,
        "firstInventorName": USPTOFields.FIRST_INVENTOR_NAME,
        "examinerNameText": USPTOFields.EXAMINER_NAME_TEXT,
        "groupArtUnitNumber": USPTOFields.GROUP_ART_UNIT_NUMBER,
        "customerNumber": USPTOFields.CUSTOMER_NUMBER,
        "entityStatusData": USPTOFields.ENTITY_STATUS_DATA,
        "inventorBag": USPTOFields.INVENTOR_BAG,
        "applicantBag": USPTOFields.APPLICANT_BAG,
        "assigneeBag": USPTOFields.ASSIGNEE_BAG,
        "uspcSymbolText": USPTOFields.USPC_SYMBOL_TEXT,
        "cpcClassificationBag": USPTOFields.CPC_CLASSIFICATION_BAG,
        "applicationTypeCode": USPTOFields.APPLICATION_TYPE_CODE,
        "applicationTypeLabelName": USPTOFields.APPLICATION_TYPE_LABEL_NAME,
        "earliestPublicationNumber": USPTOFields.EARLIEST_PUBLICATION_NUMBER,
        "publicationDateBag": USPTOFields.PUBLICATION_DATE_BAG,

        # High Priority Fields for Patent Analysis
        "applicationStatusDate": USPTOFields.APPLICATION_STATUS_DATE,
        "firstApplicantName": USPTOFields.FIRST_APPLICANT_NAME,
        "applicationConfirmationNumber": USPTOFields.APPLICATION_CONFIRMATION_NUMBER,
        "docketNumber": USPTOFields.DOCKET_NUMBER,
        "effectiveFilingDate": USPTOFields.EFFECTIVE_FILING_DATE,
        "nationalStageIndicator": USPTOFields.NATIONAL_STAGE_INDICATOR,

        # Medium Priority Fields for Enhanced Analysis
        "earliestPublicationDate": USPTOFields.EARLIEST_PUBLICATION_DATE,
        "firstInventorToFileIndicator": USPTOFields.FIRST_INVENTOR_TO_FILE_INDICATOR,
        "pctPublicationNumber": USPTOFields.PCT_PUBLICATION_NUMBER,
        "pctPublicationDate": USPTOFields.PCT_PUBLICATION_DATE,
        "class": USPTOFields.CLASS,
        "subclass": USPTOFields.SUBCLASS,
        "applicationTypeCategory": USPTOFields.APPLICATION_TYPE_CATEGORY,
        "publicationSequenceNumberBag": USPTOFields.PUBLICATION_SEQUENCE_NUMBER_BAG,
        "publicationCategoryBag": USPTOFields.PUBLICATION_CATEGORY_BAG,
        "internationalRegistrationNumber": USPTOFields.INTERNATIONAL_REGISTRATION_NUMBER,
        "internationalRegistrationPublicationDate": USPTOFields.INTERNATIONAL_REGISTRATION_PUBLICATION_DATE,

        # Parent/Child continuity fields
        "parentPatentNumber": USPTOFields.PARENT_PATENT_NUMBER,
        "parentApplicationNumberText": USPTOFields.PARENT_APPLICATION_NUMBER_TEXT,
        "childApplicationNumberText": USPTOFields.CHILD_APPLICATION_NUMBER_TEXT,
        "parentApplicationFilingDate": USPTOFields.PARENT_APPLICATION_FILING_DATE,
        "childApplicationFilingDate": USPTOFields.CHILD_APPLICATION_FILING_DATE,
        # claimParentageTypeCode exists in BOTH continuity bags; the bare name
        # resolves to the parent bag. Use the fully-qualified
        # childContinuityBag.claimParentageTypeCode for the child side.
        "claimParentageTypeCode": USPTOFields.PARENT_CLAIM_PARENTAGE_TYPE_CODE,

        # Family / term fields that are TOP-LEVEL in the ODP response
        "foreignPriorityBag": USPTOFields.FOREIGN_PRIORITY_BAG,
        "patentTermAdjustmentData": USPTOFields.PATENT_TERM_ADJUSTMENT_DATA,

        # Document fields
        "documentBag": USPTOFields.DOCUMENT_BAG,
        "associatedDocuments": USPTOFields.ASSOCIATED_DOCUMENTS,
        # Already-prefixed API names need no entries: both call sites fall
        # back to the input name via .get(field, field).
    }


def map_query_field_names(query: str) -> str:
    """
    Map user-friendly field names in a Lucene query to USPTO API field names.

    This allows users to write queries with friendly field names like:
        patentNumber:7971071

    Which get automatically converted to API field names:
        applicationMetaData.patentNumber:7971071

    Args:
        query: Lucene query string with user-friendly or API field names

    Returns:
        Query string with all field names converted to API field names

    Examples:
        >>> map_query_field_names('patentNumber:7971071')
        'applicationMetaData.patentNumber:7971071'

        >>> map_query_field_names('inventionTitle:"machine learning"')
        'applicationMetaData.inventionTitle:"machine learning"'

        >>> map_query_field_names('examinerNameText:SMITH AND patentNumber:7971071')
        'applicationMetaData.examinerNameText:SMITH AND applicationMetaData.patentNumber:7971071'
    """
    if not query or not query.strip():
        return query

    field_mapping = get_query_field_mapping()

    # Pattern to match field:value pairs in Lucene queries
    # Matches: fieldName:value or fieldName:"quoted value" or fieldName:[range]
    # Handles: field:value, field:"phrase", field:[start TO end], field:(a OR b)
    field_pattern = r'(\w+(?:\.\w+)*)\s*:'

    def replace_field(match):
        field_name = match.group(1)

        # If already an API field name (has dot), pass through
        if '.' in field_name:
            return match.group(0)

        # Map user-friendly name to API name
        api_field = field_mapping.get(field_name, field_name)

        # Return the mapped field with the colon
        return f"{api_field}:"

    # Replace all field names in the query
    mapped_query = re.sub(field_pattern, replace_field, query)

    # Shape only — the query text is user search intent (work-product)
    logger.debug(f"Mapped query fields ({len(query)} -> {len(mapped_query)} chars)")

    return mapped_query


def map_user_fields_to_api_fields(user_fields: List[str]) -> List[str]:
    """
    Map user-friendly field names to USPTO API field names

    Args:
        user_fields: List of user-friendly field names

    Returns:
        List of API field names
    """
    # Use the shared field mapping
    field_mapping = get_query_field_mapping()

    mapped_fields = []
    for field in user_fields:
        mapped_field = field_mapping.get(field, field)  # Default to original if not found
        mapped_fields.append(mapped_field)

        # Log unmapped fields for debugging
        if mapped_field == field and field not in field_mapping:
            logger.debug(f"Field '{field}' not found in mapping, using as-is")

    return mapped_fields

def get_document_priority_order() -> List[str]:
    """
    Return document codes in priority order for downloading

    Returns:
        List of document codes in priority order
    """
    return [
        'SPEC',      # Specification
        'CLM',       # Claims
        'ABST',      # Abstract
        'DRW',       # Drawings
        'NOA',       # Notice of Allowance
        'CTFR',      # Final Rejection
        'CTNF',      # Non-Final Rejection
        'IFEE',      # Issue Fee Payment
        'OATH',      # Oath or Declaration
        'IDS',       # Information Disclosure Statement
        'A...',      # Amendment
        'RCEX',      # Request for Continued Examination
        'PA..',      # Power of Attorney
        'EXIN',      # Examiner Interview Summary
        'PET.',      # Petition
        'APP.FILE.REC'  # Filing Receipt
    ]

def generate_safe_filename(app_number: str, invention_title: str, doc_code: str,
                          patent_number: str = None, max_title_length: int = 40) -> str:
    """
    Generate a safe filename using invention title and optional patent number.

    Args:
        app_number: Patent application number
        invention_title: Invention title from applicationMetaData.inventionTitle
        doc_code: Document code (e.g., 'ABST', 'CLM', 'SPEC')
        patent_number: Patent number from applicationMetaData.patentNumber (if application was granted)
        max_title_length: Maximum length for title portion (default: 40)

    Returns:
        Safe filename in format: APP-{app_number}_PAT-{patent_number}_{safe_title}_{doc_code}.pdf
        or APP-{app_number}_{safe_title}_{doc_code}.pdf if no patent granted

    Examples:
        generate_safe_filename("11752072", "Integrated Delivery System", "ABST", "7971071")
        -> "APP-11752072_PAT-7971071_INTEGRATED_DELIVERY_SYSTEM_ABST.pdf"

        generate_safe_filename("17896175", "Communication Method and Apparatus", "ABST")
        -> "APP-17896175_COMMUNICATION_METHOD_AND_APPARATUS_ABST.pdf"
    """
    import hashlib

    # Handle empty or None title
    if not invention_title or invention_title.strip() == "":
        safe_title = "UNTITLED"
    else:
        # Clean up the title
        title = invention_title.strip()

        # Convert to uppercase and replace spaces with underscores
        title = title.upper().replace(' ', '_')

        # Remove or replace problematic characters for cross-platform compatibility
        # Keep only alphanumeric, underscores, and hyphens
        title = re.sub(r'[^A-Z0-9_\-]', '', title)

        # Remove multiple consecutive underscores
        title = re.sub(r'_+', '_', title)

        # Remove leading/trailing underscores
        title = title.strip('_')

        # Truncate to max length
        if len(title) > max_title_length:
            title = title[:max_title_length]
            # Try to break at word boundary (underscore) if possible
            last_underscore = title.rfind('_')
            if last_underscore > max_title_length // 2:  # Only if we're not cutting too much
                title = title[:last_underscore]

        # Ensure we have something after all the cleaning
        safe_title = title if title else "UNTITLED"

    # Add a short hash suffix when truncating to prevent filename collisions.
    # Use a hash of the full original title + doc_code to ensure uniqueness.
    if len(invention_title or '') > max_title_length:
        hash_input = f"{app_number}{invention_title}{doc_code}"
        short_hash = hashlib.md5(hash_input.encode('utf-8')).hexdigest()[:6].upper()
        safe_title = f"{safe_title}_{short_hash}"

    # Construct the filename with APP- prefix and optional PAT- prefix
    if patent_number and patent_number.strip():
        # Clean patent number (remove any non-alphanumeric except hyphens)
        clean_patent = re.sub(r'[^A-Z0-9\-]', '', str(patent_number).strip().upper())
        filename = f"APP-{app_number}_PAT-{clean_patent}_{safe_title}_{doc_code}.pdf"
    else:
        filename = f"APP-{app_number}_{safe_title}_{doc_code}.pdf"

    # Final safety check - ensure total filename isn't too long
    if len(filename) > 100:  # Conservative limit for most filesystems
        # Calculate space available for title
        base_length = len(f"APP-{app_number}_{doc_code}.pdf")
        if patent_number and patent_number.strip():
            clean_patent = re.sub(r'[^A-Z0-9\-]', '', str(patent_number).strip().upper())
            base_length = len(f"APP-{app_number}_PAT-{clean_patent}_{doc_code}.pdf")

        max_title_for_length = 100 - base_length - 1  # 1 for underscore before title
        if max_title_for_length > 5:  # Minimum reasonable title length
            return generate_safe_filename(app_number, invention_title, doc_code, patent_number, max_title_for_length)
        else:
            # Fallback to minimal format with prefixes
            if patent_number and patent_number.strip():
                clean_patent = re.sub(r'[^A-Z0-9\-]', '', str(patent_number).strip().upper())
                return f"APP-{app_number}_PAT-{clean_patent}_{doc_code}.pdf"
            else:
                return f"APP-{app_number}_{doc_code}.pdf"

    return filename

def extract_patent_number(app_data: Dict[str, Any]) -> Optional[str]:
    """
    Extract patent number from application data (the application's own granted patent).

    Patent numbers are found in:
    applicationMetaData.patentNumber (when the application has been granted)

    Args:
        app_data: Application data from USPTO API

    Returns:
        Patent number as string, or None if application hasn't been granted
    """
    try:
        # Check if this application itself has been granted
        metadata = app_data.get('applicationMetaData', {})
        patent_number = metadata.get('patentNumber')

        if patent_number and str(patent_number).strip():
            return str(patent_number).strip()

        return None

    except Exception as e:
        logger.warning(f"Error extracting patent number: {e}")
        return None
