"""
Data models for search parameters

Implements parameter object pattern to reduce function parameter count
and improve maintainability.
"""
import re
from dataclasses import dataclass
from typing import Optional, List

#: The four date parameters are interpolated into Lucene RANGE clauses
#: unescaped and by design (`filingDate:[{start} TO {end}]`,
#: tools/search_tools.py). The comment there says they are safe because they
#: are "in known format (YYYY-MM-DD)" — but nothing checked that, so a value
#: like `2020-01-01] OR applicationMetaData.patentNumber:[* TO *` closed the
#: clause and appended a disjunction of the caller's choosing (audit M-8).
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_DATE_FIELDS = (
    "filing_date_start",
    "filing_date_end",
    "grant_date_start",
    "grant_date_end",
)


def _validate_iso_dates(params) -> None:
    """Enforce the YYYY-MM-DD shape the query builder already assumes."""
    for field in _DATE_FIELDS:
        value = getattr(params, field, None)
        if value is None:
            continue
        if not _ISO_DATE.match(str(value)):
            raise ParameterValidationError(
                field,
                f"{field} must be an ISO date in YYYY-MM-DD form, got {value!r}",
            )

#: Honest search ceiling, aligned across all three layers. The USPTO search
#: endpoint clamps `pagination.limit` to 100, so accepting 500 here (as this
#: module used to) meant a caller could be told 500 was fine and then silently
#: receive 100. Mirrors EnhancedPatentClient.MAX_SEARCH_LIMIT — kept as a
#: literal so models/ stays free of api/ imports.
MAX_SEARCH_LIMIT = 100


class ParameterValidationError(ValueError):
    """Parameter validation failure carrying the offending field name.

    Lets callers map to error templates by field instead of substring-matching
    exception text (audit F24 — 'rate limit exceeded' used to misfile as an
    invalid-limit error).
    """

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


@dataclass
class SearchParameters:
    """
    Parameter object for patent application searches

    Consolidates the many search parameters into a single object
    for better maintainability and reduced function signatures.
    """
    query: Optional[str] = None
    limit: int = 10
    offset: int = 0
    fields: Optional[List[str]] = None

    # Attorney-friendly convenience parameters
    art_unit: Optional[str] = None
    examiner_name: Optional[str] = None
    applicant_name: Optional[str] = None
    customer_number: Optional[str] = None
    status_code: Optional[str] = None
    filing_date_start: Optional[str] = None
    filing_date_end: Optional[str] = None
    grant_date_start: Optional[str] = None
    grant_date_end: Optional[str] = None

    def __post_init__(self):
        """Validate parameters after initialization"""
        if self.limit <= 0:
            raise ParameterValidationError("limit", "Limit must be positive")
        if self.offset < 0:
            raise ParameterValidationError("offset", "Offset must be non-negative")
        if self.limit > MAX_SEARCH_LIMIT:
            raise ParameterValidationError(
                "limit", f"Limit cannot exceed {MAX_SEARCH_LIMIT} (the USPTO search "
                         "endpoint's own ceiling); page with offset= for more"
            )
        # Cap free-form query length before it is forwarded to the USPTO API
        # (audit M6; mirrors the inventor path's cap in escape_lucene_query_term)
        if self.query is not None and len(self.query) > 1000:
            raise ParameterValidationError("query", "Query too long (max 1000 characters)")
        # Validated HERE, where the other invariants live, so every caller of
        # the parameter object is covered rather than each tool separately.
        _validate_iso_dates(self)


@dataclass
class InventorSearchParameters:
    """
    Parameter object for inventor searches

    Simplifies inventor search function signatures while maintaining
    flexibility for different search strategies.
    """
    name: str
    limit: int = 10
    offset: int = 0
    fields: Optional[List[str]] = None
    strategy: str = "comprehensive"  # exact, fuzzy, comprehensive

    def __post_init__(self):
        """Validate parameters after initialization"""
        if not self.name or not self.name.strip():
            raise ParameterValidationError("name", "Inventor name cannot be empty")
        if self.limit <= 0:
            raise ParameterValidationError("limit", "Limit must be positive")
        if self.offset < 0:
            raise ParameterValidationError("offset", "Offset must be non-negative")
        if self.strategy not in ["exact", "fuzzy", "comprehensive"]:
            raise ParameterValidationError("strategy", "Strategy must be 'exact', 'fuzzy', or 'comprehensive'")
        if self.limit > MAX_SEARCH_LIMIT:
            raise ParameterValidationError(
                "limit", f"Limit cannot exceed {MAX_SEARCH_LIMIT} (the USPTO search "
                         "endpoint's own ceiling); page with offset= for more"
            )
