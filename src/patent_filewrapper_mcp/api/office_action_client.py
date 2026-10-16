"""USPTO ODP Office Action API client (/api/v1/patent/office-action).

Replaces the two retired Office Action clients (oa_rejections_client.py on
/api/v1/patent/oa/oa_rejections/v2/records and oa_text_client.py on
/api/v1/patent/oa/oa_actions/v1/records), which USPTO answers with an HTML 404
since about 2026-10-10.

Three routes are used, all under the fleet's ODP key (X-API-KEY):

- POST {BASE_URL}/search: office-action records for an application, filtered by
  applicationNumberText and optionally documentCode, sorted submissionDate
  desc. Records carry metadata plus `rejectionTypeBag` and a 500-character
  `officeActionText` SNIPPET, never the full text.
- GET {BASE_URL}/{officeActionRecordIdentifier}/download/officeActionText: the
  FULL text, served as text/plain (the portal documents a JSON wrapper
  `{"officeActionText": ...}`, so both are accepted).
- A search that matches nothing answers HTTP 404 with a JSON body whose
  detailedMessage says "No matching records found"; that is an empty result,
  not an error. Any other 404 (an HTML page, as the retired routes give) raises.

Live-probed 2026-10-11 (application 11752072, patent 7,971,071): 5 records,
CTNF 2010-10-13 rejectionTypeBag ["102","103","112","Other"], CTFR 2009-09-21
["103","112"]; the CTNF text download was 24,159 characters of text/plain.
Index-wide facets the same day: 19,939,490 records; submissionDate from
2007-07-27; documentCode NOA 4,759,100 (with downloadable text);
rejectionTypeBag values 103, 102, 112, Other, 101, DoublePatent.

Auth, timeout (USPTO_OA_TIMEOUT, default 60s here because the text download is
the large response), bounded retry, the 429 rule, the shared cross-process
rate limiter and the ODP usage counters all come from OAClientBase.
"""
import os
import re
from typing import Any, Dict, Iterable, List, Optional

import httpx

from ..exceptions import USPTOAPIError, ValidationError
from ..shared.safe_logger import get_safe_logger
from .oa_base import OAClientBase

logger = get_safe_logger(__name__)

BASE_URL = "https://api.uspto.gov/api/v1/patent/office-action"

#: The search endpoint's page ceiling as this client uses it.
MAX_SEARCH_LIMIT = 100

_RECORD_ID = re.compile(r"^[0-9A-Za-z-]{8,64}$")
_NO_MATCH = "no matching records"

#: Statutory rejection sections that rejectionTypeBag names.
STATUTORY_SECTIONS = ("101", "102", "103", "112")

#: Canonical spelling for double patenting (the facet value seen live).
DOUBLE_PATENTING = "DoublePatent"


def _is_no_match(resp: httpx.Response) -> bool:
    """True for the API's JSON "No matching records found" 404."""
    if "json" not in resp.headers.get("content-type", "").lower():
        return False
    try:
        body = resp.json()
    except ValueError:
        return False
    if not isinstance(body, dict):
        return False
    message = f"{body.get('detailedMessage', '')} {body.get('message', '')}".lower()
    return _NO_MATCH in message


def _not_found_error(resp: httpx.Response, route: str) -> USPTOAPIError:
    kind = "an HTML page" if "html" in resp.headers.get("content-type", "").lower() else "a 404"
    return USPTOAPIError(
        f"Office Action API {route} answered {kind} (HTTP 404) that is not the "
        "documented 'No matching records' response; the route may have moved.",
        404,
    )


def normalize_rejection_type(value: Any) -> str:
    """One rejectionTypeBag value in canonical form.

    Live values are bare ("103", "Other", "DoublePatent"); USPTO's documentation
    sample shows "35 U.S.C. 103". Both become the bare section number; any
    double-patenting spelling becomes "DoublePatent"; other values are kept.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.search(r"(?<![0-9])(101|102|103|112)(?![0-9])", text)
    if match:
        return match.group(1)
    if re.sub(r"[^a-z]", "", text.lower()) in ("doublepatent", "doublepatenting"):
        return DOUBLE_PATENTING
    return text


def normalize_rejection_types(bag: Optional[Iterable[Any]]) -> List[str]:
    """The whole bag, normalized and de-duplicated in order."""
    if bag is None:
        return []
    if isinstance(bag, (str, bytes)):
        bag = [bag]
    out: List[str] = []
    for value in bag:
        norm = normalize_rejection_type(value)
        if norm and norm not in out:
            out.append(norm)
    return out


class OfficeActionClient(OAClientBase):
    """Client for the ODP Office Action API."""

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(
            api_key,
            timeout=float(os.getenv("USPTO_OA_TIMEOUT", "60.0")),
        )

    async def search_office_actions(
        self,
        application_number: str,
        document_codes: Optional[Iterable[str]] = None,
        offset: int = 0,
        limit: int = 10,
        fields: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Office-action records for one application, newest first.

        Returns the API envelope `{count, officeActionDataBag, ...}`; a search
        that matches nothing returns `{"count": 0, "officeActionDataBag": []}`.
        """
        app = str(application_number).strip()
        if not app.isdigit():
            raise ValidationError(f"application number must be digits, got {len(app)} chars")
        limit = max(1, min(int(limit), MAX_SEARCH_LIMIT))
        filters: List[Dict[str, Any]] = [{"name": "applicationNumberText", "value": [app]}]
        codes = [str(c).strip().upper() for c in (document_codes or []) if str(c).strip()]
        if codes:
            filters.append({"name": "documentCode", "value": codes})
        body: Dict[str, Any] = {
            "filters": filters,
            "sort": [{"field": "submissionDate", "order": "desc"}],
            "pagination": {"offset": max(0, int(offset)), "limit": limit},
        }
        if fields:
            body["fields"] = list(fields)
        resp = await self._request_response(
            "POST", f"{BASE_URL}/search", json=body, allow_status=(404,)
        )
        if resp.status_code == 404:
            if _is_no_match(resp):
                return {"count": 0, "officeActionDataBag": []}
            raise _not_found_error(resp, "search")
        data = resp.json()
        if not isinstance(data, dict):
            raise USPTOAPIError("Office Action API search returned a non-object body", resp.status_code)
        data.setdefault("officeActionDataBag", [])
        if data["officeActionDataBag"] is None:
            data["officeActionDataBag"] = []
        return data

    async def get_office_action_text(self, record_id: str) -> Optional[str]:
        """The FULL text of one office action, or None when the API has no
        text for that record (its "No matching records" 404)."""
        rid = str(record_id or "").strip()
        if not _RECORD_ID.match(rid):
            raise ValidationError("officeActionRecordIdentifier is malformed")
        resp = await self._request_response(
            "GET",
            f"{BASE_URL}/{rid}/download/officeActionText",
            allow_status=(404,),
        )
        if resp.status_code == 404:
            if _is_no_match(resp):
                return None
            raise _not_found_error(resp, "text download")
        if "json" in resp.headers.get("content-type", "").lower():
            try:
                body = resp.json()
            except ValueError:
                return resp.text
            if isinstance(body, dict):
                text = body.get("officeActionText")
                if isinstance(text, list):
                    return "\n".join(str(t) for t in text)
                return "" if text is None else str(text)
        return resp.text


# ---------------------------------------------------------------------------
# Section excerpts cut from the full text
# ---------------------------------------------------------------------------

#: An office action's rejection headings, e.g. "Claim Rejections - 35 USC § 103"
#: (USPTO form-paragraph headings; the ODP text keeps them on their own line).
_SECTION_HEADING = re.compile(
    r"^[ \t]*Claim\s+Rejections?\s*[-–—:]*\s*35\s*U\.?\s*S\.?\s*C\.?\s*"
    r"(?P<sections>[^\n]{0,60})$",
    re.IGNORECASE | re.MULTILINE,
)

#: Headings that end a rejection section: the next rejection heading or one of
#: the other standard office-action headings, each alone on its line.
_STOP_HEADING = re.compile(
    r"^[ \t]*(?:Claim\s+Rejections?\b|Claim\s+Objections?\b|Double\s+Patenting\b|"
    r"Response\s+to\s+(?:Arguments|Amendment)\b|Allowable\s+Subject\s+Matter\b|"
    r"Reasons\s+for\s+Allowance\b|Conclusion\b|Election\s*/\s*Restrictions?\b|"
    r"Information\s+Disclosure\s+Statement\b|Drawings\b|Specification\b|"
    r"Priority\b|Notice\s+of\s+Pre-AIA\b)[^\n]{0,60}$",
    re.IGNORECASE | re.MULTILINE,
)


def extract_section_text(body: str, section: str) -> str:
    """The text under this office action's "Claim Rejections - 35 USC § <section>"
    heading(s), up to the next standard heading; "" when there is no such
    heading. Case and wording are the office action's own (a cut, not a
    rewrite). Several headings for the same section are joined in order."""
    if not body or section not in STATUTORY_SECTIONS:
        return ""
    pieces: List[str] = []
    for match in _SECTION_HEADING.finditer(body):
        named = re.findall(r"(?<![0-9])(\d{3})(?![0-9])", match.group("sections"))
        if section not in named:
            continue
        stop = _STOP_HEADING.search(body, match.end())
        end = stop.start() if stop else len(body)
        pieces.append(body[match.start():end].strip("\n"))
    return "\n".join(pieces)
