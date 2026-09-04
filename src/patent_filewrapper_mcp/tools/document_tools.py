"""Document tools: OCR content, downloads, documentBag, XML, granted-patent
package (audit F2 split from main.py)."""

import os
from typing import Any, Dict, List, Optional, Union

from fastmcp import Context
from fastmcp.apps import AppConfig

from ..api.helpers import (
    format_error_response,
    validate_app_number,
)
from ..client_registry import _client
from ..models.constants import DocumentDirection
from ..shared import response_bounds
from ..shared.injection_scan import RETRIEVED_TEXT_NOTE, _WARNING_NOTE, scan_text
from ..shared.response_bounds import apply_text_window, content_char_budget
from ..shared.safe_logger import get_safe_logger
from ..util.error_handlers import mcp_error_handler
from ..util.identifier_resolution import content_type_error_message, resolve_or_error
from ..app_uris import _DOWNLOADS_URI, _XML_URI
from ..server_bootstrap import _ensure_proxy_server_running

logger = get_safe_logger(__name__)

# Max documents returnable by PFW_get_application_documents (audit F37)
MAX_DOCUMENT_LIMIT = 200


def _resolve_proxy_port(proxy_port: Optional[int]) -> int:
    """PFW_PROXY_PORT first (MCP-specific), then PROXY_PORT, then 8080."""
    if proxy_port is not None:
        return proxy_port
    return int(os.getenv('PFW_PROXY_PORT', os.getenv('PROXY_PORT', 8080)))


async def _resolve_target_document(client, app_number: str, document_identifier: str):
    """Find a document and its PDF download option in the application's
    documentBag. Returns (target_doc, pdf_option) or an error dict."""
    docs_result = await client.get_documents(app_number)
    if docs_result.get('error'):
        return docs_result

    target_doc = None
    for doc in docs_result.get('documentBag', []):
        if doc.get('documentIdentifier') == document_identifier:
            target_doc = doc
            break
    if not target_doc:
        return format_error_response(f"Document with identifier '{document_identifier}' not found")

    pdf_option = None
    for option in target_doc.get('downloadOptionBag', []):
        if option.get('mimeTypeIdentifier') == 'PDF':
            pdf_option = option
            break
    if not pdf_option:
        return format_error_response("PDF not available for this document")

    return target_doc, pdf_option


def _build_download_link(
    app_number: str, document_identifier: str, proxy_port: int, generate_persistent_link: bool
) -> str:
    """Immediate or persistent (7-day encrypted) proxy download URL.
    PFW_PROXY_BASE_URL overrides the base for external deployments."""
    proxy_base = os.getenv("PFW_PROXY_BASE_URL", f"http://localhost:{proxy_port}")
    if generate_persistent_link:
        from ..proxy.secure_link_cache import get_link_cache
        return get_link_cache().generate_persistent_link(app_number, document_identifier, proxy_base)
    return f"{proxy_base}/download/{app_number}/{document_identifier}"


async def _get_title_and_patent_number(client, app_number: str):
    """Best-effort (invention_title, patent_number) lookup for filename
    enrichment; returns (None, None) on any failure."""
    try:
        search_result = await client.search_applications(
            f"applicationNumberText:{app_number}",
            limit=1,
            offset=0,
            fields=["applicationMetaData.inventionTitle", "applicationMetaData.patentNumber"]
        )
        if search_result.get('success'):
            apps = search_result.get('patentFileWrapperDataBag') or search_result.get('applications')
            if apps:
                from ..api.helpers import extract_patent_number
                title = apps[0].get('applicationMetaData', {}).get('inventionTitle')
                return title, extract_patent_number(apps[0])
    except Exception as e:
        logger.warning(f"Could not fetch application metadata for {app_number}: {e}")
    return None, None



def _iter_strings(value):
    """Yield every string leaf in a nested dict/list structure (used to scan
    structured_content regardless of the exact claims/description shape)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _iter_strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _iter_strings(v)


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


# Soft ceiling for the PFW_get_application_documents response. claude.ai replaces
# any tool result much past ~50K chars with a client-side truncation error the
# server never sees, so an oversized response reaches the model as nothing at
# all. Default limit=50 lands near 13K, but limit=200 on a heavily-prosecuted
# application measured ~90K (2026-08-16) — mostly downloadOptionBag entries for
# MS_WORD/XML variants this MCP never downloads. Slim first, truncate second,
# and always say what happened so the model can narrow instead of retrying blind.
#
# The ceiling and the truncation stage now come from the shared guard
# (shared/response_bounds.py), so this tool speaks the same `_bounds` vocabulary
# as every other tool in the FPD/PTAB/PFW suite; the legacy documents_returned /
# documents_total / documents_note keys are preserved as ALIASES.
_DOCUMENTS_MIN_DOCS = 10
_PDF_OPTION_FIELDS = ("downloadUrl", "pageTotalQuantity")

#: Kept as a module constant for the existing tests and any external reader;
#: the live value is USPTO_MAX_RESPONSE_CHARS (same 40,000 default).
_DOCUMENTS_SOFT_CHAR_LIMIT = response_bounds.DEFAULT_MAX_RESPONSE_CHARS

_DOCUMENT_BAG_SPEC = {
    "path": ["documentBag"],
    "keep_fields": (),  # the PDF-option pre-slim below is this tool's stage 1
    "min_items": _DOCUMENTS_MIN_DOCS,
    "label": "documentBag",
}

#: Canonical `_bounds` sub-key -> this repo's pre-existing top-level key.
_DOCUMENT_ALIASES = {
    "items_returned": "documents_returned",
    "items_total": "documents_total",
    "note": "documents_note",
}

_DOCUMENTS_NOTE = (
    "downloadOptionBag was slimmed to the PDF option (downloadUrl + page count) "
    "on every document to stay under the client response-size limit — a larger "
    "response would have been replaced by an unrecoverable truncation error. "
    "Downloads and OCR need only document_identifier: "
    "PFW_get_document_download(app_number=..., document_identifier=...) or "
    "PFW_get_document_content_with_ocr(...). To narrow the list itself, filter "
    "with document_code (NOA, CTNF, CTFR, 892, CLM) or "
    "direction_category (INCOMING/OUTGOING/INTERNAL), or lower limit. When "
    "records were also dropped, `_bounds.items_returned` / `items_total` "
    "(documents_returned / documents_total) give the counts."
)


def _bound_documents_response(result: Dict[str, Any]) -> Dict[str, Any]:
    """Keep a PFW_get_application_documents response under the response budget.

    Stage 1 is this tool's own: every documentBag entry's downloadOptionBag is
    reduced to the PDF option alone (PFW_get_document_download /
    PFW_get_document_content_with_ocr resolve their own download URL from a
    documentIdentifier, so the other MIME variants are pure payload). That
    PDF-SELECTION is why it cannot be expressed as a shared `keep_fields` spec —
    keeping "the PDF one" is a filter, not a projection.

    Stage 2 (halving the bag toward _DOCUMENTS_MIN_DOCS) and the whole marker
    contract are delegated to shared/response_bounds.py. summary /
    key_documents / guidance are left untouched — they are the cheap part and
    the model needs the bookkeeping. Returns the response object unmodified,
    byte-identical and with no `_bounds` key, when it already fits.
    """
    limit = response_bounds.response_char_budget()
    if response_bounds.measure_chars(result) <= limit:
        return result
    bag = result.get('documentBag') or []
    if not bag:
        return result
    total = len(bag)

    # Copy-on-slim rather than mutate in place: these entries can be the same
    # dicts the client keeps in its stale-response cache.
    slimmed = []
    for doc in bag:
        if not isinstance(doc, dict):
            slimmed.append(doc)
            continue
        options = doc.get('downloadOptionBag') or []
        slimmed.append({**doc, 'downloadOptionBag': [
            {k: opt[k] for k in _PDF_OPTION_FIELDS if k in opt}
            for opt in options
            if isinstance(opt, dict) and opt.get('mimeTypeIdentifier') == 'PDF'
        ]})
    result['documentBag'] = slimmed

    bounded = response_bounds.bound_structured_response(
        result,
        bags=(_DOCUMENT_BAG_SPEC,),
        limit=limit,
        note=_DOCUMENTS_NOTE,
        aliases=_DOCUMENT_ALIASES,
        text_fallback=True,
    )
    if response_bounds.BOUNDS_KEY not in bounded:
        # The PDF pre-slim alone brought it under budget, so the shared guard
        # was a no-op — but the payload DID change, and an unmarked change is
        # exactly what this work exists to eliminate. Attach the same marker
        # vocabulary for the stage this module performed itself.
        _attach_preslim_bounds(bounded, kept=total, total=total, limit=limit)
    return bounded


def _attach_preslim_bounds(
    payload: Dict[str, Any], *, kept: int, total: int, limit: int
) -> None:
    """`_bounds` for the PDF-option pre-slim, in the shared vocabulary."""
    marker = {
        "applied": True,
        "reason": response_bounds.REASON_SIZE,
        "size_chars": 0,
        "size_limit": limit,
        "stages": [response_bounds.STAGE_SLIMMED],
        "slimmed_fields": ["downloadOptionBag"],
        "items_returned": kept,
        "items_total": total,
        "note": _DOCUMENTS_NOTE,
    }
    payload[response_bounds.BOUNDS_KEY] = marker
    for canonical, legacy in _DOCUMENT_ALIASES.items():
        payload[legacy] = marker[canonical]
    marker["size_chars"] = response_bounds.measure_chars(payload)


#: Recovery text embedded in `_window.note` — names the exact tool and
#: parameter that fetches the remainder.
_CONTENT_WINDOW_NOTE = (
    "Only part of the extracted text is shown. Re-call "
    "PFW_get_document_content_with_ocr(app_number='{app_number}', "
    "document_identifier='{document_identifier}', char_offset=<_window.next_offset>) "
    "to continue from where this window ended; raise max_chars to widen it."
)

#: Canonical marker sub-key -> this repo's pre-existing top-level key. The OCR
#: page cap (services/ocr_service.py) and the pypdf page cap already set
#: `truncated` / `truncation_note`; aligning the window on the same keys keeps
#: one vocabulary for "you are not holding all of it".
_CONTENT_WINDOW_ALIASES = {"applied": "truncated", "note": "truncation_note"}


def _window_extracted_content(
    result: Dict[str, Any],
    app_number: str,
    document_identifier: str,
    char_offset: int,
    max_chars: Optional[int],
) -> None:
    """Put a cursor over the extracted text.

    The caller explicitly asked for document text, so the ceiling is the higher
    CONTENT budget — the guard is against pathological size, and the cursor
    makes the remainder REACHABLE instead of lost. A document that already fits
    is left untouched (no `_window` key). Windows snap to `=== PAGE N ===`
    markers, which both extraction tiers now emit.
    """
    if not isinstance(result.get("extracted_content"), str):
        return
    result["content_total_chars"] = len(result["extracted_content"])
    prior_truncation_note = result.get("truncation_note")
    apply_text_window(
        result,
        "extracted_content",
        offset=char_offset,
        max_chars=min(max_chars, content_char_budget()) if max_chars else None,
        note=_CONTENT_WINDOW_NOTE.format(
            app_number=app_number, document_identifier=document_identifier
        ),
        aliases=_CONTENT_WINDOW_ALIASES,
    )
    result["content_returned_chars"] = len(result["extracted_content"])
    if prior_truncation_note and result.get("truncation_note") != prior_truncation_note:
        # A page cap AND a text window both applied — report both, because they
        # mean different things (pages never extracted vs text not yet read).
        result["truncation_note"] = f"{prior_truncation_note} {result['truncation_note']}"


async def _register_download_via_proxy(port: int, title: str, doc_type: str, app_number: str, proxy_url: str, filename: str = "") -> None:
    """POST a download registration to the proxy server.

    Works whether the proxy is in-process (asyncio task) or a separately running
    instance (e.g. ENABLE_ALWAYS_ON_PROXY=true carries over across sessions).
    Silently ignores failures so it never blocks tool output.
    """
    try:
        import httpx

        # Import the token directly from the proxy module — same process, same token.
        # In HTTP mode the proxy runs as a daemon thread in this process, so
        # _get_proxy_token() returns the same value the proxy server validates against.
        from ..proxy.server import _get_proxy_token
        proxy_token = _get_proxy_token()

        headers = {"X-Proxy-Token": proxy_token}
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(
                f"http://localhost:{port}/api/register-download",
                json={
                    "title": title,
                    "doc_type": doc_type,
                    "app_number": app_number,
                    "proxy_url": proxy_url,
                    "filename": filename or "",
                },
                headers=headers,
            )
            resp.raise_for_status()
            logger.info("Registered download '%s' via proxy (HTTP %s)", title, resp.status_code)
    except Exception as e:
        logger.warning(f"Could not register download via proxy endpoint (port {port}): {e}")




def _upgrade_component_links(result: Dict[str, Any], app_number: str, proxy_port: int) -> None:
    """Replace each granted-patent component's proxy URL with a persistent
    encrypted link. Best effort: a link-cache failure leaves the plain proxy
    URLs in place rather than failing the package."""
    proxy_base = os.getenv("PFW_PROXY_BASE_URL", f"http://localhost:{proxy_port}")
    try:
        from ..proxy.secure_link_cache import get_link_cache
        link_cache = get_link_cache()
        for comp_data in result.get("granted_patent_components", {}).values():
            doc_id = comp_data.get("document_identifier")
            if doc_id:
                comp_data["proxy_download_url"] = link_cache.generate_persistent_link(
                    app_number, doc_id, proxy_base
                )
    except Exception as link_err:
        logger.debug(f"Could not generate persistent links for granted package: {link_err}")


#: `max_pages` is a parameter this tool has never had. It was reached for
#: anyway (skill QA ledger, 2026-09-03), and an unknown keyword failed with a
#: schema error that named nothing useful. It is accepted here for the sole
#: purpose of answering with the parameters that DO exist.
_MAX_PAGES_ERROR = (
    "max_pages is not a parameter of PFW_get_document_content_with_ocr. To "
    "bound what comes back, use char_offset= and max_chars= (a CHARACTER "
    "window over the extracted text, with a `_window.next_offset` cursor), or "
    "page_from= and page_to= (a 1-based inclusive PAGE range, applied to the "
    "PDF before extraction so an extraction tier's own page cap applies to the "
    "window rather than to the whole document). The per-tier page caps "
    "themselves are server settings (PYPDF_MAX_PAGES, MISTRAL_OCR_MAX_PAGES), "
    "not call parameters."
)


def _validate_content_window(char_offset, max_chars, page_from, page_to, max_pages=None):
    """Validate the char-window and page-window parameters of
    PFW_get_document_content_with_ocr. Returns an error response or None."""
    if max_pages is not None:
        return format_error_response(_MAX_PAGES_ERROR, 400)
    if char_offset < 0:
        return format_error_response("char_offset must be non-negative", 400)
    if max_chars is not None and max_chars < 1:
        return format_error_response("max_chars must be at least 1", 400)
    if page_from < 1:
        return format_error_response("page_from must be 1 or greater (pages are 1-based)", 400)
    if page_to is not None and page_to < page_from:
        return format_error_response(
            f"page_to ({page_to}) must be greater than or equal to page_from ({page_from})", 400
        )
    return None


def register(mcp) -> None:
    """Register the five document tools."""
    @mcp.tool(name="PFW_get_document_content_with_ocr", annotations={"defer_loading": True, "readOnlyHint": True})
    @mcp_error_handler
    async def pfw_get_document_content(
        app_number: str,
        document_identifier: str,
        auto_optimize: bool = True,
        char_offset: int = 0,
        max_chars: Optional[int] = None,
        page_from: int = 1,
        page_to: Optional[int] = None,
        max_pages: Optional[int] = None,
        ctx: Context = None
    ) -> Dict[str, Any]:
        """Extract full text from USPTO prosecution documents with intelligent hybrid extraction (text variants first, then pypdf, then OCR).
    Read, extract, text, contents, full document, OCR, quote from a filing, amendment, remarks, IDS, declaration, or specification.
    PREREQUISITE: First use PFW_get_application_documents to get document_identifier from documentBag.
    Auto-optimizes extraction, in order: the text variants the USPTO API serves alongside the PDF
    render (.docx -> xmlarchive -> as-uploaded PDF text layer; USPTO-authored papers such as office
    actions, reexam orders and NIRCs, and e-filed claims/remarks/IDS almost always have one), then
    pypdf on the PDF render, then OCR only for true scans.
    MISTRAL_API_KEY is optional - without it, the other tiers are still available.
    Returns: extracted_content, extraction_method ("docx variant", "xmlarchive (USPTO OCR)",
    "xmlarchive (USPTO XML)", "as-uploaded pdf text layer", "PyPDF2", "Mistral OCR ...", "Docling OCR"),
    application_number_verified (variants are checked against the requested application; a mismatch
    is rejected), and free_text_variants (what was tried and why it was or was not used).

    PAGING LONG DOCUMENTS — nothing is discarded, long text is WINDOWED:
    - char_offset (default 0): where to start reading in the extracted text
    - max_chars (default USPTO_MAX_CONTENT_CHARS, 120,000): window size
    When the text is longer than one window the response carries a `_window`
    block {unit, offset, returned, total, has_more, next_offset}; pass
    `_window.next_offset` back as char_offset to read the next window. Windows
    snap to `=== PAGE N ===` boundaries when the extraction emitted them, so a
    page is never split. Separately, `pages_truncated` / `truncation_note` mean
    pages were never EXTRACTED at all (a PYPDF_MAX_PAGES or MISTRAL_OCR_MAX_PAGES
    cap) — that text is not reachable by CHAR paging. Use the page range for those.

    PAGE RANGE — for pages an extraction cap never reached:
    - page_from (default 1) / page_to (default: end of document), 1-based inclusive
    The PDF is SLICED to that window before extraction, so each tier's page cap
    (PYPDF_MAX_PAGES 200, MISTRAL_OCR_MAX_PAGES 50) applies to the window instead of
    to the whole document: a 104-page scan whose OCR stopped at page 50 is finished
    with page_from=51. The response carries `page_window`
    {applied, page_from, page_to, pages_in_window, page_count_total, note}.
    A page range does NOT apply to the text-variant tier (.docx / xmlarchive have
    no page structure) — `page_window.applied` is then False and says so.

    There is no `max_pages` parameter: bound the response with max_chars (characters)
    or page_from / page_to (pages). Passing max_pages returns a 400 naming those four.

    ⚠️ TEXT VARIANTS OMIT FORM PAGES. The text variants carry the BODY text only: the
    .docx variant of an order or office action omits USPTO form pages the PDF carries
    (observed 2026-08-30 — a reexam order's PTOL-471G page, carrying the response
    deadline and the no-statement consequence, is in the PDF and absent from the .docx),
    and `downloadOptionBag` gives no hint. Check `extraction_method`: anything other than
    "PyPDF2", "Mistral OCR ..." or "Docling OCR" means you are holding a text variant and
    any form page is missing. When a deadline, form paragraph or signature block matters,
    take the PDF via PFW_get_document_download.

    Example workflow:
    1. PFW_get_application_documents(app_number='17/896,175') → get doc IDs
    2. PFW_get_document_content_with_ocr(app_number='17/896,175', document_identifier='ABC123XYZ')
    3. If _window.has_more: re-call with char_offset=_window.next_offset
    For document selection and extraction strategies, use PFW_get_guidance (see quick reference chart for section selection)."""
        window_error = _validate_content_window(
            char_offset, max_chars, page_from, page_to, max_pages
        )
        if window_error:
            return window_error
        try:
            api_client = _client()

            async def _progress(progress: float, total: float, message: str):
                if ctx:
                    await ctx.report_progress(progress, total, message)

            result = await api_client.extract_document_content_hybrid(
                app_number, document_identifier, auto_optimize, progress_cb=_progress,
                page_from=page_from, page_to=page_to,
            )
            # Provenance labeling + detection-only injection scan of the
            # extracted text (kind labels only, text served verbatim — see
            # shared/injection_scan.py). `injection_scan` is ABSENT when clean.
            if isinstance(result, dict) and result.get("success"):
                result["provenance_note"] = RETRIEVED_TEXT_NOTE
                # The injection scan deliberately runs on the FULL text, before
                # the window, so a later window's content is flagged up front.
                kinds = scan_text(result.get("extracted_content") or "")
                if kinds:
                    result["injection_scan"] = {
                        "flagged": [{
                            "application_number": result.get("application_number", app_number),
                            "document_identifier": result.get("document_identifier", document_identifier),
                            "kinds": kinds,
                        }],
                        "note": _WARNING_NOTE,
                    }
                _window_extracted_content(
                    result, app_number, document_identifier, char_offset, max_chars
                )
            return result
        except RuntimeError as e:
            # Catch async lifecycle errors specifically
            error_msg = str(e)
            if "cannot schedule new futures" in error_msg or "interpreter shutdown" in error_msg:
                logger.error(f"Async lifecycle error in document extraction: {error_msg}")
                return format_error_response(
                    "Document extraction failed due to async runtime issue. This may be an environment-specific problem. "
                    "Try restarting the MCP server or check if MISTRAL_API_KEY is properly configured. "
                    f"Technical details: {error_msg}"
                )
            else:
                return format_error_response(f"Runtime error during document extraction: {str(e)}")
        except Exception as e:
            logger.exception("Unexpected error in document content extraction")
            return format_error_response(f"Failed to extract document content: {str(e)}")

    # --- download-tool helpers (extracted from PFW_get_document_download; audit:
    # --- the tool body was ~140 logic lines doing 6 jobs at complexity ~12-14) ---


    @mcp.tool(name="PFW_get_document_download", app=AppConfig(resource_uri=_DOWNLOADS_URI), annotations={"defer_loading": True, "readOnlyHint": True})
    @mcp_error_handler
    async def pfw_get_document_download(app_number: str, document_identifier: str, proxy_port: Optional[int] = None, generate_persistent_link: bool = True) -> Dict[str, Any]:
        """Generate secure browser-accessible download URLs for USPTO prosecution documents (PDFs).
    Download, PDF, file, link, URL, save, open in a browser, get a copy of a prosecution paper.
    PREREQUISITE: First use PFW_get_application_documents to get document_identifier from documentBag.
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

    CRITICAL RESPONSE FORMAT - Always format with BOTH clickable link and raw URL:
    **📁 [Download {DocumentType} ({PageCount} pages)]({proxy_url})** | Raw URL: `{proxy_url}`

    Why both formats?
    - Clickable links work in Claude Desktop and most clients
    - Raw URLs enable copy/paste in Msty and other clients where links aren't clickable

    Example workflow for multiple downloads:
    1. PFW_get_application_documents(app_number='17/896,175') → get doc IDs
    2. PFW_get_document_download(app_number='17/896,175', document_identifier='ABC123XYZ') → GENERATES PERSISTENT LINK
    3. Format ALL download links as clickable markdown (links work immediately and remain valid for 7 days)
    4. Optional: Use generate_persistent_link=false for immediate-only links (requires proxy to stay running)

    For document selection strategies and multi-document workflows, use PFW_get_guidance (see quick reference chart for section selection)."""
        try:
            api_client = _client()

            proxy_port = _resolve_proxy_port(proxy_port)
            app_number = validate_app_number(app_number)

            # Start proxy server if not already running
            await _ensure_proxy_server_running(proxy_port)

            resolved = await _resolve_target_document(api_client, app_number, document_identifier)
            if isinstance(resolved, dict):  # error response
                return resolved
            target_doc, pdf_option = resolved

            proxy_download_url = _build_download_link(
                app_number, document_identifier, proxy_port, generate_persistent_link
            )
            original_download_url = pdf_option.get('downloadUrl', '')

            invention_title, patent_number = await _get_title_and_patent_number(api_client, app_number)

            # Generate expected filename for user reference
            expected_filename = "Legacy format used (metadata unavailable)"
            if invention_title:
                from ..api.helpers import generate_safe_filename
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

            # Register in recent downloads store for the MCP App panel (via proxy endpoint)
            await _register_download_via_proxy(
                port=proxy_port,
                title=document_info.get("document_description") or document_info.get("document_code") or "Document",
                doc_type=document_info.get("document_code", ""),
                app_number=app_number,
                proxy_url=proxy_download_url,
                filename=expected_filename if isinstance(expected_filename, str) and expected_filename != "Legacy format used (metadata unavailable)" else "",
            )

            return {
                "success": True,
                "proxy_download_url": proxy_download_url,
                "original_download_url": original_download_url,
                "document_info": document_info,
                "application_number": app_number,
                "document_identifier": document_identifier,

                # LLM guidance for proper response formatting
                "llm_response_guidance": {
                    "format": f"**📁 [Download {document_info.get('document_description', 'Document')} ({document_info.get('page_count', 'N/A')} pages)]({proxy_download_url})** | Raw URL: `{proxy_download_url}`",
                    "critical": "Provide clickable markdown link for browser access AND raw URL for clients like Msty where links aren't clickable",
                    "explanation": "Clickable link works in Claude Desktop, raw URL enables copy/paste in Msty and other clients"
                },
                "note": "Proxy handles authentication and rate limiting (5 downloads per 10s)"
            }

        except Exception as e:
            return format_error_response(f"Failed to create download proxy: {str(e)}")


    @mcp.tool(name="PFW_get_application_documents", annotations={"defer_loading": False, "readOnlyHint": True})
    @mcp_error_handler
    async def pfw_get_application_documents(
        app_number: str,
        limit: int = 50,
        document_code: Optional[Union[str, List[str]]] = None,
        direction_category: Optional[str] = None,
        content_type: str = "auto"
    ) -> Dict[str, Any]:
        """Get prosecution document metadata (documentBag) with SELECTIVE FILTERING to avoid context explosion.

    ⚠️ CRITICAL: For heavily-prosecuted applications with 200+ documents, ALWAYS use filtering parameters.
    Requesting all documents without filters can cause massive token usage (100K+ characters).

    🆕 FOR GRANTED PATENTS: Use PFW_get_granted_patent_documents_download for complete patent package (ABST, DRW, SPEC, CLM).

    📋 FILTERING PARAMETERS:

    **document_code** - Filter by document type. Each code is matched EXACTLY and
    case-insensitively; there is no wildcard, so 'A...' is the literal USPTO
    amendment code, not a pattern. Pass ONE code, a LIST of codes, or a
    pipe-joined string; a list or pipe string is an OR over the codes:
        document_code='CTFR'                 # one code
        document_code=['CTFR', 'CTNF']       # either (preferred form)
        document_code='CTFR|CTNF'            # same thing, pipe-joined
      Key Examiner Actions:
        - NOA: Notice of Allowance, CTNF: Non-Final Rejection, CTFR: Final Rejection, 892: Examiner Citations
      Key Applicant Responses:
        - A...: Amendment/Response, RCEX: Continued Examination, IDS: Info Disclosure, 1449: Applicant Citations
      Patent Components:
        - ABST: Abstract, CLM: Claims, SPEC: Specification, DRW: Drawings, FWCLM: Claims Index

    **direction_category** - Filter by source:
        - INCOMING: Applicant submissions, OUTGOING: USPTO examiner documents, INTERNAL: USPTO internal

    **limit** - Max documents to return (default: 50, max: 200). Applied AFTER filtering.

    📌 EXAMPLES (always use filtering):

    # Allowance reasoning for litigation
    PFW_get_application_documents(app_number='14/171,705', document_code='NOA')

    # Office action rejections
    PFW_get_application_documents(app_number='14/171,705', document_code='CTFR', limit=20)

    # Both rejection types in one call (OR over the codes)
    PFW_get_application_documents(app_number='14/171,705', document_code=['CTFR', 'CTNF'])

    # All applicant responses
    PFW_get_application_documents(app_number='14/171,705', direction_category='INCOMING', limit=100)

    # Examiner's cited prior art
    PFW_get_application_documents(app_number='14/171,705', document_code='892')

    ⚠️ AVOID: PFW_get_application_documents(app_number='...', limit=200) without filters
    ✅ DO: Always filter by document_code or direction_category

    Returns document identifiers needed for PFW_get_document_download or PFW_get_document_content_with_ocr.

    OWNERSHIP: `assignmentBag` in the balanced search tiers is frequently returned EMPTY for
    patents that ARE assigned of record (observed 2026-08-29 on US 11,333,007, Reel 048880 /
    Frame 0804). An empty bag is NOT evidence of no assignment. The working reads are
    applicationMetaData.firstApplicantName / applicantBag and the Rule 3.73(c) statement
    document in this bag.

    IDENTIFIER: app_number accepts the granted patent number too. WARNING: a bare 8-digit
    value is AMBIGUOUS. It is a valid application serial and, since patent numbers crossed
    US 10,000,000 in mid-2018, also a valid patent number, so it is resolved against the API
    patent-number-first (applicationMetaData.patentNumber, then applicationNumberText) and an
    8-digit serial can be captured by an unrelated granted patent. To FORCE the application
    lane, pass the slash-comma serial format (e.g. '11/752,072') or content_type='application'
    ('auto' is the default, 'patent' forces the patent lane). Every response reports
    identifier_resolved_as, identifier_note, identifier_lanes_tried and, when the input
    could have gone either way, identifier_ambiguous: true, the same block
    PFW_get_patent_or_application_xml returns, on the success path, the upstream-error
    path and the exception path alike. Check those before trusting the documents.

    Oversized responses are automatically slimmed (and truncated if still too large) with a `documents_note` explaining what was dropped and how to narrow.

    For cross-MCP workflows, use PFW_get_guidance (see quick reference chart)."""
        # Bound before the try so the failure path can still report WHICH
        # identifier was looked up, the question a failed document read raises.
        resolution = None
        try:
            api_client = _client()

            # Input validation
            if not app_number or len(app_number.strip()) == 0:
                return format_error_response("Application number cannot be empty", 400)
            if limit < 1 or limit > MAX_DOCUMENT_LIMIT:
                return format_error_response(f"Limit must be between 1 and {MAX_DOCUMENT_LIMIT}", 400)
            if direction_category and not DocumentDirection.is_valid(direction_category):
                return format_error_response(
                    f"direction_category must be one of: {', '.join(DocumentDirection.all())}",
                    400
                )

            # Resolve the RAW input, THEN validate — resolve_or_error does
            # both, in that order, for every identifier-taking tool. Validating
            # first strips the slash off "11/752,072", which turns an
            # unambiguous serial into an ambiguous 8-digit number and lands the
            # answer on patent 11,752,072 instead (evals finding 2026-08-31).
            # An 8-digit identifier is BOTH a valid patent number and a valid
            # application serial, so the API decides, not a heuristic
            # (OPEN_ITEMS #9).
            resolution, resolve_error = await resolve_or_error(
                api_client, app_number, content_type
            )
            if resolve_error:
                return resolve_error
            app_number = resolution.application_number

            # Get document bag from USPTO API with filtering
            docs_result = await api_client.get_documents(
                app_number,
                limit=limit,
                document_code=document_code,
                direction_category=direction_category
            )

            if docs_result.get('error'):
                return {**docs_result, **resolution.response_fields()}

            return _bound_documents_response({
                "success": True,
                **resolution.response_fields(),
                "application_number": docs_result.get('application_number'),
                "count": docs_result.get('count'),
                "documentBag": docs_result.get('documentBag', []),
                "summary": docs_result.get('summary', {}),
                "request_id": f"docs-{app_number}",
                "guidance": {
                    "office_action_shortcut": (
                        "To READ an office action (CTNF, CTFR, NOA, CTRS), do not use this bag plus "
                        "PFW_get_document_content_with_ocr. PFW_get_oa_text returns the examiner's text "
                        "in one call with no PDF and no scanning step, and PFW_get_oa_rejections triages which "
                        "OAs are worth reading. Use the bag path for office actions older than the OA text "
                        "dataset (roughly pre-2008), for non-OA documents, or when an actual PDF is needed."
                    ),
                    "workflow": [
                        "For office action TEXT, prefer PFW_get_oa_rejections (triage) then PFW_get_oa_text (full text, no OCR)",
                        "Use document_identifier with PFW_get_document_download for browser downloads",
                        "Use document_identifier with PFW_get_document_content_with_ocr for text extraction (auto pypdf/OCR) of non-OA documents",
                        "Filter with document_code (NOA, CTFR, CTNF, 892) for key documents"
                    ],
                    "filtering": {
                        "noa": "document_code='NOA' - Allowance reasoning (PFW_get_oa_text(action_type='NOA') answers in one call, with no PDF and less context)",
                        "rejections": "document_code='CTFR'/'CTNF' - Office actions (PFW_get_oa_text is the primary path)",
                        "prior_art": "document_code='892' - Examiner citations, '1449' - Applicant citations",
                        "amendments": "document_code='CLM' - Claim evolution",
                        "several_codes": (
                            "document_code takes a LIST (['CTFR', 'CTNF']) or a pipe-joined "
                            "string ('CTFR|CTNF') and OR-s the codes. Each code is matched "
                            "exactly and case-insensitively; there is no wildcard, so 'A...' "
                            "is the literal amendment code."
                        )
                    },
                    "cross_mcp": {
                        "ptab": "PTAB applicationNumberText/patentNumber → PFW minimal → PFW_get_oa_text(action_type='NOA') → compare examiner vs PTAB reasoning",
                        "fpd": "FPD applicationNumber → PFW minimal → PFW_get_oa_rejections then PFW_get_oa_text(action_type='CTFR'|'CTNF') → analyze rejection patterns",
                        "citations": "Citations applicationNumber/patentNumber → Citations_search_oa_citations_minimal (raw 892/1449 lists, broadest coverage) → PFW_get_application_documents(document_code='892'|'1449') only if the form image is needed"
                    },
                    "key_insight": "Document identifiers are ONLY valid with this specific applicationNumberText",
                    "expectation": "No single 'complete patent PDF' - must download individual documents"
                }
            })

        except Exception as e:
            return {
                "success": False,
                **(resolution.response_fields() if resolution is not None else {}),
                "application_number": app_number,
                "error": str(e),
                "documentBag": [],
                "count": 0
            }


    @mcp.tool(name="PFW_get_patent_or_application_xml", app=AppConfig(resource_uri=_XML_URI), annotations={"defer_loading": True, "readOnlyHint": True})
    @mcp_error_handler
    async def pfw_get_patent_or_application_xml(
        identifier: str,
        content_type: str = "auto",
        include_fields: Optional[List[str]] = None,
        include_raw_xml: bool = False,
        description_paragraph_from: int = 1,
        description_paragraph_to: Optional[int] = None
    ) -> Dict[str, Any]:
        """Get structured XML content for patents or applications (filed after January 1, 2001).
    Claims, claim text, abstract, description, specification, what does claim 1 say, read the patent, cited references.
    Use after finding applications via search to analyze claims, description, abstract, and citations.

    **IDENTIFIER RESOLUTION (`content_type`) — read this before passing an 8-digit number.**
    An 8-digit bare number is simultaneously a valid US patent number and a valid
    application serial (patent numbers passed 12,000,000 in 2024), so it is AMBIGUOUS.
    With the default `content_type='auto'` the API decides, not a heuristic:
    `applicationMetaData.patentNumber:<n>` is queried first, then
    `applicationNumberText:<n>`. Every response reports `identifier_resolved_as`
    ('patent' | 'application' | 'publication') and `identifier_lanes_tried`, so check
    those before trusting the content.
      - content_type='patent'      → force the patent-number lane (granted patent XML)
      - content_type='application' → force the application-serial lane (pre-grant XML)
      - content_type='auto'        → default; patent lane first, application lane second
      - any other value is rejected with a 400 (it does NOT fall back to 'auto')
    Example: identifier='12539322' resolves to PATENT 12,539,322 (application 17996652).
    Pass content_type='application' to reach application 12/539,322 instead.

    **PUBLICATION NUMBERS.** An 11-digit pre-grant publication number ('20080141381',
    or the ST.16 form 'US20080141381A1') is accepted: it is crosswalked to its
    application through applicationMetaData.earliestPublicationNumber and comes back
    with identifier_resolved_as='publication'. That identifier names the PRE-GRANT
    publication, so the XML served is APPXML; pass the granted patent number, or
    content_type='patent', when the ISSUED claims are what you need.

    **CLAIM TYPE.** Each claim carries `type_derived` (authoritative — derived from the
    claim text and the XML's <claim-ref> links) and `type_reported` (the old keyword
    guess, kept only for comparison; it mislabelled claims in both directions). `type`
    is an alias of `type_derived`. `claims_independent_count` counts the derived ones.

    **CITATIONS.** `citations_status` is 'parsed' | 'unavailable' | 'parse_failed'.
    A `citations_total` of 0 is only meaningful next to that field: 'unavailable' means
    the XML carries no references-cited block (normal for pre-grant publication XML),
    'parse_failed' means one IS present but nothing came out of it. Non-patent
    literature is counted in `npl_citations_total` and not listed.

    **PRE-2005 GRANTS.** The USPTO full-text grant XML dataset starts with patents issued
    in 2005 (probe-verified 2026-08-30). An older grant returns an explicit "not served
    for this grant year" error, not "may not be granted" — the file wrapper itself is
    still reachable via PFW_get_application_documents.

    ⚠️ DEFAULT CHANGE (2026-08-21): `include_raw_xml` now defaults to **False**.
    It defaulted to True "for backward compatibility", which put a ~50K-token
    raw XML blob into every response by default — routinely the single largest
    payload this MCP returned, and almost never read. The structured content is
    unchanged. Pass include_raw_xml=True explicitly for debugging or custom XML
    parsing.

    **DEFAULT BEHAVIOR (include_fields not specified):**
    Returns only core content fields optimized for patent analysis (~5K tokens, no raw_xml):
    - abstract: Full abstract text
    - claims: All independent and dependent claims with full text
    - description: First 5 paragraphs of detailed description/specification, with
      description_paragraphs_returned / description_paragraphs_total so you can see
      how much of the specification that is

    **DESCRIPTION PARAGRAPHS AND PINPOINTS.** Alongside the joined `description` text,
    `description_paragraphs` carries one entry per paragraph with the `id` and `num`
    attributes USPTO puts on the XML `<p>` element (the stable pinpoints a claim chart
    cites; either may be null when the XML omits it), plus `position`, the paragraph's
    1-based ordinal. Move the window with description_paragraph_from /
    description_paragraph_to (1-based, inclusive); the response echoes what it served in
    description_paragraph_from / description_paragraph_to. These pinpoints previously
    required include_raw_xml=True.

    **RAW XML (include_raw_xml=True):**
    Adds the complete source XML (~50K tokens):
    - Useful for debugging or custom parsing, not needed for most workflows
    - Everything the structured fields expose is already parsed out for you

    **AVAILABLE FIELDS (use include_fields to customize):**
    Core Content:
      - abstract: Full abstract text
      - claims: All claims with full text
      - description: First 5 paragraphs of specification

    Metadata (also available via PFW_search_applications_balanced):
      - inventors: Inventor names, sequences, and locations
      - applicants: Applicant/assignee information
      - classifications: USPTO and Cooperative Patent Classifications (CPC/IPC)
      - publication_info: Publication dates, numbers, and document information

    References:
      - citations: Backward (references-cited) patent citations, capped with
        citations_returned / citations_total / citations_status / npl_citations_total
        (consider uspto_enriched_citation_mcp for richer analysis). Forward citations
        are NOT in this XML.

    **SELECTIVE USAGE EXAMPLES:**

    1. Recommended (the new default — patent analysis without raw XML overhead):
       PFW_get_patent_or_application_xml(identifier='7971071')
       → Returns: abstract, claims, description (~5K tokens)

    2. Ultra-efficient claims only (claim construction, infringement analysis):
       PFW_get_patent_or_application_xml(identifier='7971071', include_fields=['claims'], include_raw_xml=False)
       → Returns: claims only (~1.5K tokens - 95% reduction!)

    3. Claims + citations without raw XML (prior art analysis):
       PFW_get_patent_or_application_xml(identifier='7971071', include_fields=['claims', 'citations'], include_raw_xml=False)
       → Returns: claims, citations (~2.5K tokens)

    4. Just inventors without raw XML (portfolio analysis):
       PFW_get_patent_or_application_xml(identifier='7971071', include_fields=['inventors'], include_raw_xml=False)
       → Returns: inventors only (~300 tokens - 99% reduction!)

    5. Inventors + applicants without raw XML (entity analysis):
       PFW_get_patent_or_application_xml(identifier='7971071', include_fields=['inventors', 'applicants'], include_raw_xml=False)
       → Returns: inventors, applicants (~500 tokens)

    6. Legacy shape (raw XML explicitly requested — was the default before 2026-08-21):
       PFW_get_patent_or_application_xml(identifier='7971071', include_raw_xml=True)
       → Returns: abstract, claims, description + raw_xml (~55K tokens total)

    7. Everything with raw XML (debugging or custom XML parsing):
       PFW_get_patent_or_application_xml(
           identifier='7971071',
           include_fields=['abstract', 'claims', 'description', 'inventors', 'applicants', 'classifications', 'citations', 'publication_info'],
           include_raw_xml=True
       )
       → Returns: all fields + raw_xml (~80K tokens)

    **CONTEXT OPTIMIZATION TIPS:**
    - Leave include_raw_xml at its False default (most workflows don't need raw XML)
    - For inventor/applicant reports: Add include_fields=['inventors', 'applicants'] if using minimal search
    - For metadata: Check if already available from prior PFW_search_applications_balanced call
    - For citations: Consider uspto_enriched_citation_mcp for deeper citation analysis with backward/forward citation trees
    - Request only what you need to minimize context

    For field selection guidance and token estimates, use PFW_get_guidance(section='tools')."""
        try:
            bad_content_type = content_type_error_message(content_type)
            if bad_content_type:
                return format_error_response(bad_content_type, 400)

            api_client = _client()

            result = await api_client.get_patent_or_application_xml(
                identifier, content_type, include_fields, include_raw_xml,
                description_paragraph_from, description_paragraph_to,
            )

            # Add patent_number to response so the MCP App widget can show it.
            # For PTGRXML: if the user passed a patent number (identifier != derived app_number),
            # identifier_used IS the patent number.
            if result.get("success"):
                identifier_used = result.get("identifier_used", "")
                application_number = result.get("application_number", "")
                xml_type = result.get("xml_type", "")
                if xml_type == "PTGRXML" and identifier_used and identifier_used != application_number:
                    result["patent_number"] = identifier_used
                else:
                    result["patent_number"] = ""

                # Provenance labeling + detection-only injection scan of the
                # structured content (abstract/claims/description). Kind
                # labels only, text served verbatim; `injection_scan` is
                # ABSENT when clean. See shared/injection_scan.py.
                result["provenance_note"] = RETRIEVED_TEXT_NOTE
                joined = " ".join(_iter_strings(result.get("structured_content")))
                kinds = scan_text(joined)
                if kinds:
                    result["injection_scan"] = {
                        "flagged": [{
                            "application_number": result.get("application_number", ""),
                            "identifier_used": identifier_used or identifier,
                            "kinds": kinds,
                        }],
                        "note": _WARNING_NOTE,
                    }

            return result

        except Exception as e:
            return format_error_response(f"Failed to get XML content: {str(e)}")


    @mcp.tool(name="PFW_get_granted_patent_documents_download", app=AppConfig(resource_uri=_DOWNLOADS_URI), annotations={"defer_loading": True, "readOnlyHint": True})
    @mcp_error_handler
    # NOTE (audit F33): this tool's flag is generate_persistent_links (plural —
    # one per patent component) while PFW_get_document_download uses the singular
    # generate_persistent_link. Both are deployed parameter names; do not rename.
    async def pfw_get_granted_patent_documents_download(
        app_number: str,
        include_drawings: bool = True,
        include_original_claims: bool = False,
        direction_category: Optional[str] = "INCOMING",
        proxy_port: Optional[int] = None,
        generate_persistent_links: bool = True,
        content_type: str = "auto"
    ) -> Dict[str, Any]:
        """Get complete granted patent package (Abstract, Drawings, Specification, Claims) in one call.
        Download the granted patent, issued patent PDF, drawings, figures, specification, claims, full copy, due diligence package.

        Accepts either the application number or the granted patent number.

        Perfect for: Due diligence, portfolio review, litigation preparation, or whenever an attorney
        needs the complete granted patent. Returns all 4 components with organized download links.

        ✅ ENHANCED PROXY INTEGRATION: This tool provides immediate download access!
        - Always-on proxy: Links work immediately (if ENABLE_ALWAYS_ON_PROXY=true)
        - On-demand proxy: Automatic startup when needed
        - Persistent links: Enabled by default - 7-day encrypted access (set generate_persistent_links=false to disable)
        - Download links are immediately clickable after tool execution and remain valid for 7 days

        📋 RESPONSE FORMAT: Each component includes BOTH clickable link AND raw URL:
        **📁 [Download {Component} ({Pages} pages)]({url})** | Raw URL: `{url}`
        - Clickable links work in Claude Desktop and most clients
        - Raw URLs enable copy/paste in Msty and other clients where links aren't clickable

        Args:
            app_number: Patent APPLICATION number OR the granted PATENT number (required).
                        WARNING: a bare 8-digit value is AMBIGUOUS. It is a valid
                        application serial and, since patent numbers crossed
                        US 10,000,000 in mid-2018, also a valid patent number, and
                        resolution is patent-number-first
                        (applicationMetaData.patentNumber, then applicationNumberText),
                        so an 8-digit serial can be captured by an unrelated granted
                        patent. For an application serial, use the slash-comma format
                        (e.g. '11/752,072') or pass content_type='application'. The
                        response reports identifier_resolved_as
                        ('patent'|'application'), identifier_note and
                        identifier_lanes_tried.
            include_drawings: Include drawings in response (default: True, set False to skip)
            include_original_claims: Get originally-filed claims vs. granted claims (default: False = granted)
            proxy_port: Proxy server port (default: 8080)
            content_type: 'auto' (default), 'patent' or 'application'. The two explicit
                        values force one resolution lane for a bare 8-digit identifier
                        instead of the patent-number-first probe.

        Common scenarios:
        - "Get me the granted patent for application 14/171,705"
        - "I need the complete patent package for portfolio review"
        - "Download all components of the granted patent"

        Returns structured response with all components and download links. Use PFW_get_application_documents
        for selective filtering in complex prosecutions with 200+ documents.

        For complex workflows, see PFW_get_guidance (quick reference chart available).
        """
        try:
            api_client = _client()

            proxy_port = _resolve_proxy_port(proxy_port)

            # Resolve first, validate after (resolve_or_error does both) —
            # see PFW_get_application_documents above for why the order is
            # load-bearing for a slashed serial.
            # A PATENT number is accepted here too (OPEN_ITEMS #9): this tool
            # exists to package a GRANTED patent, so a caller holding the
            # patent number is the normal case. An 8-digit value is resolved
            # against the API (patent-number lane first) rather than assumed.
            resolution, resolve_error = await resolve_or_error(
                api_client, app_number, content_type
            )
            if resolve_error:
                return resolve_error
            app_number = resolution.application_number

            # Start proxy server if not already running
            await _ensure_proxy_server_running(proxy_port)

            result = await api_client.get_granted_patent_documents_download(
                app_number=app_number,
                include_drawings=include_drawings,
                include_original_claims=include_original_claims,
                direction_category=direction_category
            )

            # Upgrade proxy URLs to persistent encrypted links if requested
            if generate_persistent_links and result.get("success"):
                _upgrade_component_links(result, app_number, proxy_port)

            # Register each component in recent downloads store for MCP App panel (via proxy endpoint)
            if result.get("success"):
                component_titles = {
                    "abstract": "Abstract",
                    "drawings": "Drawings",
                    "specification": "Specification",
                    "claims": "Claims (Granted)" if not include_original_claims else "Claims (Original)",
                }
                for comp_name, comp_data in result.get("granted_patent_components", {}).items():
                    await _register_download_via_proxy(
                        port=proxy_port,
                        title=f"{component_titles.get(comp_name, comp_name.title())} — App {app_number}",
                        doc_type=comp_name,
                        app_number=app_number,
                        proxy_url=comp_data.get("proxy_download_url", ""),
                        filename=f"{app_number}_{comp_name}.pdf",
                    )

            result.update(resolution.response_fields())
            return result

        except ValueError as ve:
            return format_error_response(str(ve), 400)
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "guidance": "Use PFW_search_applications_balanced to verify application number exists"
            }

    # REMOVED: pfw_get_tool_reflections - migrated to PFW_get_guidance for context efficiency
    # The comprehensive tool reflection functionality has been migrated to sectioned guidance
    # Use PFW_get_guidance(section='tools') for tool-specific guidance
    # Use PFW_get_guidance(section='overview') to see all available sections

