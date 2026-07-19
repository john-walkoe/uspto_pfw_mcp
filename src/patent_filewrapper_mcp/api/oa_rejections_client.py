"""USPTO Office Action Rejections API client (v2)

Provides access to document-level rejection data from office actions.
Dataset covers Oct 1, 2017 to 30 days prior to current date, refreshed daily.
"""
from typing import Any, Dict

from ..shared.safe_logger import get_safe_logger
from .oa_base import OAClientBase

logger = get_safe_logger(__name__)

BASE_URL = "https://api.uspto.gov/api/v1/patent/oa/oa_rejections/v2"


class OARejectionClient(OAClientBase):
    """Client for the USPTO Office Action Rejections API v2.

    Auth, timeout (USPTO_OA_TIMEOUT), and bounded retry come from
    OAClientBase (audits F19/F23).
    """

    async def get_fields(self) -> Dict[str, Any]:
        """Return available searchable fields for the OA rejections dataset."""
        return await self._request_json("GET", f"{BASE_URL}/fields")

    async def search(
        self,
        criteria: str,
        start: int = 0,
        rows: int = 10,
    ) -> Dict[str, Any]:
        """Search OA rejection records using Lucene/Solr query syntax.

        Args:
            criteria: Lucene query string, e.g. 'patentApplicationNumber:15992176'
            start: Starting record index (0-based)
            rows: Number of records to return (max 100)

        Returns:
            Raw API response dict with 'response.docs' list and 'response.numFound'
        """
        return await self._request_json(
            "POST",
            f"{BASE_URL}/records",
            data={"criteria": criteria, "start": start, "rows": rows},
        )
