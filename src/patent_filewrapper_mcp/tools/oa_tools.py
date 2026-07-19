"""Office Action tools: rejections + full text (audit F2 split from main.py)."""

from typing import Any, Dict, Optional


from ..client_registry import get_api_client
from ..shared.injection_scan import RETRIEVED_TEXT_NOTE, scan_hits
from ..shared.safe_logger import get_safe_logger
from ..util.error_handlers import mcp_error_handler

logger = get_safe_logger(__name__)


# Lazy-initialized OA clients
_oa_rejection_client = None
_oa_text_client = None


def _get_oa_rejection_client():
    global _oa_rejection_client
    if _oa_rejection_client is None:
        from ..api.oa_rejections_client import OARejectionClient
        # Reuse API key from already-initialized main client (handles secure storage + env var)
        try:
            api_key = get_api_client().api_key
        except Exception:
            api_key = None
        _oa_rejection_client = OARejectionClient(api_key=api_key)
    return _oa_rejection_client


def _get_oa_text_client():
    global _oa_text_client
    if _oa_text_client is None:
        from ..api.oa_text_client import OATextClient
        # Reuse API key from already-initialized main client (handles secure storage + env var)
        try:
            api_key = get_api_client().api_key
        except Exception:
            api_key = None
        _oa_text_client = OATextClient(api_key=api_key)
    return _oa_text_client



def register(mcp) -> None:
    """Register the two OA tools."""
    @mcp.tool(name="get_oa_rejections", annotations={"defer_loading": True, "readOnlyHint": True})
    @mcp_error_handler
    async def pfw_get_oa_rejections(
        application_number: str,
        latest_only: bool = False,
        rows: int = 10,
    ) -> Dict[str, Any]:
        """Get Office Action rejection indicators for a patent application.

    Returns structured data about what types of rejections appeared in office actions:
    - 35 U.S.C. 101 (patent eligibility), 102 (novelty), 103 (obviousness), 112 (written description)
    - Alice/Mayo/Bilski/Myriad eligibility indicators
    - Citation counts (max 103 citations, citations equal to 1, citations greater than 3)
    - Quality flags: closingMissing, formParagraphMissing, headerMissing, rejectFormMissmatch

    Data covers office actions from Oct 1, 2017 to 30 days prior to current date.

    Examples:
        pfw_get_oa_rejections('15992176')              # All OA rejections for this app
        pfw_get_oa_rejections('15992176', rows=25)     # Get up to 25 records

    Use pfw_get_oa_text to fetch the full text of a specific office action.
    Use pfw_get_application_documents to get document identifiers for download.
        """
        try:
            client = _get_oa_rejection_client()
            criteria = f"patentApplicationNumber:{application_number}"
            raw = await client.search(criteria=criteria, start=0, rows=rows)
            docs = raw.get("response", {}).get("docs", [])
            num_found = raw.get("response", {}).get("numFound", 0)

            if not docs:
                return {
                    "success": True,
                    "application_number": application_number,
                    "num_found": 0,
                    "rejections": [],
                    "note": "No OA rejection data found. Coverage starts Oct 1, 2017. Application may predate coverage or have no office actions."
                }

            # Summarize rejection indicators across all OAs
            summary = {
                "has_101": any(d.get("hasRej101", 0) for d in docs),
                "has_102": any(d.get("hasRej102", 0) for d in docs),
                "has_103": any(d.get("hasRej103", 0) for d in docs),
                "has_112": any(d.get("hasRej112", 0) for d in docs),
                "has_double_patenting": any(d.get("hasRejDP", 0) for d in docs),
                "alice_indicator": any(d.get("aliceIndicator") for d in docs),
                "mayo_indicator": any(d.get("mayoIndicator") for d in docs),
                "bilski_indicator": any(d.get("bilskiIndicator") for d in docs),
                "myriad_indicator": any(d.get("myriadIndicator") for d in docs),
                "max_103_citations": max((d.get("cite103Max", 0) for d in docs), default=0),
                "office_actions_count": num_found,
            }

            return {
                "success": True,
                "application_number": application_number,
                "num_found": num_found,
                "showing": len(docs),
                "summary": summary,
                "rejections": [
                    {
                        "submission_date": d.get("submissionDate", ""),
                        "doc_code": d.get("legacyDocumentCodeIdentifier", ""),
                        "art_unit": d.get("groupArtUnitNumber", ""),
                        "has_101": bool(d.get("hasRej101", 0)),
                        "has_102": bool(d.get("hasRej102", 0)),
                        "has_103": bool(d.get("hasRej103", 0)),
                        "has_112": bool(d.get("hasRej112", 0)),
                        "alice": d.get("aliceIndicator"),
                        "mayo": d.get("mayoIndicator"),
                        "bilski": d.get("bilskiIndicator"),
                        "myriad": d.get("myriadIndicator"),
                        "cite_103_max": d.get("cite103Max", 0),
                        "allowed_claims": d.get("allowedClaimIndicator"),
                        "claims": d.get("claimNumberArrayDocument", []),
                    }
                    for d in docs
                ],
                "data_note": "Coverage: Oct 1, 2017 to 30 days prior to today. Refreshed daily."
            }

        except Exception as e:
            return {"success": False, "error": str(e), "application_number": application_number}


    @mcp.tool(name="get_oa_text", annotations={"defer_loading": True, "readOnlyHint": True})
    @mcp_error_handler
    async def pfw_get_oa_text(
        application_number: str,
        action_type: Optional[str] = None,
        latest_only: bool = True,
        section: str = "all",
    ) -> Dict[str, Any]:
        """Fetch full text of a USPTO office action (CTNF, CTFR, NOA, etc.).

    Returns the complete text of public office actions. Ideal for reading the examiner's reasoning
    in a non-final office action (CTNF), final rejection (CTFR), or notice of allowance (NOA).

    Args:
        application_number: Patent application number (e.g., '15992176')
        action_type: Filter by document code — 'CTNF' (non-final), 'CTFR' (final rejection),
                     'NOA' (notice of allowance), 'CTRS' (restriction requirement), etc.
                     If omitted, returns most recent office action of any type.
        latest_only: Return only the most recent matching OA (default: True).
                     Set to False to return all matching OAs.
        section: Which text to return:
                 'all' (default) — full bodyText (may be large for complex OAs)
                 '101' — only the § 101 eligibility rejection section
                 '102' — only the § 102 novelty rejection section
                 '103' — only the § 103 obviousness rejection section
                 '112' — only the § 112 written description rejection section

    Note: Returns text to LLM context for analysis. Data covers public office actions
    from 12-series applications onward.

    Examples:
        pfw_get_oa_text('15992176')                          # Latest OA full text
        pfw_get_oa_text('15992176', action_type='CTNF')      # Latest non-final OA
        pfw_get_oa_text('15992176', section='103')           # Only 103 rejection text
        pfw_get_oa_text('15992176', latest_only=False)       # All OAs full text
        """
        try:
            client = _get_oa_text_client()

            # Build criteria
            criteria_parts = [f"patentApplicationNumber:{application_number}"]
            if action_type:
                criteria_parts.append(f"legacyDocumentCodeIdentifier:{action_type}")
            criteria = " AND ".join(criteria_parts)

            rows = 1 if latest_only else 10
            raw = await client.search(criteria=criteria, start=0, rows=rows)
            docs = raw.get("response", {}).get("docs", [])
            num_found = raw.get("response", {}).get("numFound", 0)

            if not docs:
                return {
                    "success": True,
                    "application_number": application_number,
                    "num_found": 0,
                    "text": "",
                    "note": "No office action text found. Coverage starts with 12-series applications. "
                            "Application may not have public office actions or may predate coverage.",
                    "provenance_note": RETRIEVED_TEXT_NOTE,
                }

            results = []
            for doc in docs:
                title_raw = doc.get("inventionTitle", [])
                title = (title_raw[0] if isinstance(title_raw, list) and title_raw else title_raw) or ""
                doc_code_raw = doc.get("legacyDocumentCodeIdentifier", [])
                doc_code = (doc_code_raw[0] if isinstance(doc_code_raw, list) and doc_code_raw else doc_code_raw) or ""

                if section == "all":
                    text = client.extract_body_text(doc)
                else:
                    text = client.extract_section_text(doc, section)
                    if not text:
                        # Fall back to full body if section not separately indexed
                        text = client.extract_body_text(doc)
                    elif text and text == text.lower() and len(text) > 50:
                        # USPTO Solr indexes section-specific fields with a text analyser
                        # that lowercases all content. Body text preserves original case.
                        # Reconstruct from body text using the section text as a positional guide.
                        body = client.extract_body_text(doc)
                        if body:
                            body_lower = body.lower()
                            anchor_start = text[:120].strip()
                            pos = body_lower.find(anchor_start)
                            if pos != -1:
                                anchor_end = text[-120:].strip()
                                end_pos = body_lower.rfind(anchor_end, pos)
                                if end_pos != -1:
                                    text = body[pos:end_pos + len(anchor_end)]
                                else:
                                    text = body[pos:pos + len(text)]

                results.append({
                    "submission_date": doc.get("submissionDate", ""),
                    "doc_code": doc_code,
                    "art_unit": doc.get("groupArtUnitNumber", ""),
                    "invention_title": title,
                    "section_returned": section,
                    "text": text,
                    "text_length_chars": len(text),
                })

            # Detection-only injection scan of the returned OA text (kind
            # labels only, never matched text — see shared/injection_scan.py).
            # Per-item dicts carry no application_number (it is envelope-
            # level), so stamp it into each flagged entry for attribution.
            # `injection_scan` is ABSENT from the envelope when clean.
            provenance = {"provenance_note": RETRIEVED_TEXT_NOTE}
            injection = scan_hits(results, text_keys=("text",), id_key="doc_code")
            if injection:
                for entry in injection["flagged"]:
                    entry["application_number"] = application_number
                provenance["injection_scan"] = injection

            if latest_only and results:
                return {
                    "success": True,
                    "application_number": application_number,
                    "num_found": num_found,
                    **results[0],
                    **provenance,
                }

            return {
                "success": True,
                "application_number": application_number,
                "num_found": num_found,
                "showing": len(results),
                "office_actions": results,
                **provenance,
            }

        except Exception as e:
            return {"success": False, "error": str(e), "application_number": application_number}

