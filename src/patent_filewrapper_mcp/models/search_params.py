"""
Data models for search parameters

Implements parameter object pattern to reduce function parameter count
and improve maintainability.
"""
from dataclasses import dataclass
from typing import Optional, List


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
            raise ValueError("Limit must be positive")
        if self.offset < 0:
            raise ValueError("Offset must be non-negative")
        if self.limit > 500:
            raise ValueError("Limit cannot exceed 500")


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
            raise ValueError("Inventor name cannot be empty")
        if self.limit <= 0:
            raise ValueError("Limit must be positive")
        if self.offset < 0:
            raise ValueError("Offset must be non-negative")
        if self.strategy not in ["exact", "fuzzy", "comprehensive"]:
            raise ValueError("Strategy must be 'exact', 'fuzzy', or 'comprehensive'")
        if self.limit > 500:
            raise ValueError("Limit cannot exceed 500")
