"""USPTO Office Action Text Retrieval API client (v1)

Provides full-text content of public office actions starting with 12-series applications.
Dataset refreshed daily.
"""
import os
from typing import Any, Dict, Optional

from ..shared.safe_logger import get_safe_logger
from .oa_base import OAClientBase

logger = get_safe_logger(__name__)

BASE_URL = "https://api.uspto.gov/api/v1/patent/oa/oa_actions/v1"

# Fields that contain the actual rejection text (sections sub-documents)
SECTION_FIELD_MAP = {
    "101": "sections.section101RejectionText",
    "102": "sections.section102RejectionText",
    "103": "sections.section103RejectionText",
    "112": "sections.section112RejectionText",
}


class OATextClient(OAClientBase):
    """Client for the USPTO Office Action Text Retrieval API v1.

    Auth, timeout, and bounded retry come from OAClientBase (audits
    F19/F23). Body text responses are large, so the default timeout is
    60s unless USPTO_OA_TIMEOUT overrides it.
    """

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(
            api_key,
            timeout=float(os.getenv("USPTO_OA_TIMEOUT", "60.0")),
        )

    async def get_fields(self) -> Dict[str, Any]:
        """Return available searchable fields for the OA text dataset."""
        return await self._request_json("GET", f"{BASE_URL}/fields")

    async def search(
        self,
        criteria: str,
        start: int = 0,
        rows: int = 10,
    ) -> Dict[str, Any]:
        """Search OA text records using Lucene/Solr query syntax.

        Args:
            criteria: Lucene query string, e.g. 'patentApplicationNumber:15992176'
            start: Starting record index (0-based)
            rows: Number of records to return

        Returns:
            Raw API response dict with 'response.docs' list.
            Each doc contains 'bodyText' (list with one element — the full OA text),
            'inventionTitle', 'submissionDate', 'legacyDocumentCodeIdentifier', etc.
        """
        return await self._request_json(
            "POST",
            f"{BASE_URL}/records",
            data={"criteria": criteria, "start": start, "rows": rows},
        )

    def extract_body_text(self, doc: Dict[str, Any]) -> str:
        """Extract bodyText string from a response doc (bodyText is returned as a list)."""
        body = doc.get("bodyText", [])
        if isinstance(body, list):
            return "\n".join(body)
        return str(body) if body else ""

    def extract_section_text(self, doc: Dict[str, Any], section: str) -> str:
        """Extract a specific rejection section text from a doc.

        Args:
            doc: A document from response.docs
            section: One of '101', '102', '103', '112'

        Returns:
            Section rejection text, or empty string if not present
        """
        field = SECTION_FIELD_MAP.get(section)
        if not field:
            return ""
        value = doc.get(field, [])
        if isinstance(value, list):
            return "\n".join(value)
        return str(value) if value else ""
