"""
Enhanced USPTO Patent File Wrapper API client

This client provides access to the USPTO Patent File Wrapper API for searching
applications, getting detailed application data, retrieving documents, and
downloading PDFs.
"""
import httpx
import os
import re
# defusedxml: hardens against XXE / entity-expansion in USPTO-served XML (audit L12)
from typing import Dict, Any, List, Optional
from .helpers import validate_app_number, format_error_response, generate_request_id, create_inventor_queries, map_user_fields_to_api_fields
from .free_text_variants import (
    METHOD_UPLOADED_PDF,
    VariantEmptyError,
    VariantMismatchError,
    classify_download_options,
    extract_docx,
    extract_xmlarchive,
)
from ..exceptions import AuthenticationError, NotFoundError, ValidationError
from ..shared.safe_logger import get_safe_logger
from ..shared.uspto_shared_rate_limiter import get_shared_limiter
from ..shared.uspto_hosts import USPTO_KEY_EVENT_HOOKS

try:
    import PyPDF2  # noqa: F401 — availability probe; used lazily in extract_with_pypdf2
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

from .docling_client import DoclingClient

logger = get_safe_logger(__name__)

#: What the free PyPDF2 tier writes under a page header when the page has no
#: text layer. A rasterized IFW render yields one of these per page.
PYPDF_EMPTY_PAGE_PLACEHOLDER = "[no text recovered from this page]"
_PAGE_HEADER_RE = re.compile(r"^=== PAGE \d+ ===[ \t]*$")


def _pypdf_body_text(text: str) -> str:
    """The PyPDF2 output minus its ``=== PAGE N ===`` scaffolding and
    empty-page placeholders — i.e. what the text layer actually yielded.

    ``is_good_extraction`` must judge THIS, not the full string: a rasterized
    IFW render produces one placeholder per page, and thirty copies of an
    English sentence sail through the word-count / alphabetic-ratio heuristics.
    That was the false "PyPDF2 successful" the 2026-08-25 follow-up records —
    the desktop user was told the document was extracted when nothing was.
    """
    return "\n".join(
        line for line in text.split("\n")
        if not _PAGE_HEADER_RE.match(line) and line.strip() != PYPDF_EMPTY_PAGE_PLACEHOLDER
    )


#: Per-document page cap for the FREE PyPDF2 extraction tier. Named to match
#: the paid tier's MISTRAL_OCR_MAX_PAGES (services/ocr_service.py) and the
#: identically-named knob in the PTAB MCP. Before this cap the tier walked
#: every page of the document, so a 900-page file wrapper produced a payload
#: the client discarded whole.
_DEFAULT_PYPDF_MAX_PAGES = 200


def pypdf_max_pages() -> int:
    """PYPDF_MAX_PAGES — per-document free-tier page cap (default 200)."""
    try:
        return max(1, int(os.getenv("PYPDF_MAX_PAGES", str(_DEFAULT_PYPDF_MAX_PAGES))))
    except (TypeError, ValueError):
        logger.warning("Invalid PYPDF_MAX_PAGES; using default 200")
        return _DEFAULT_PYPDF_MAX_PAGES


#: Ceiling on a single document buffered for extraction. 100 MB by default:
#: large enough for any real file wrapper, small enough that three copies of
#: one still fit (audit M-19).
_DEFAULT_MAX_DOCUMENT_BYTES = 100_000_000


def max_document_bytes() -> int:
    """PFW_MAX_DOCUMENT_BYTES — extraction-path document ceiling."""
    try:
        return max(
            1, int(os.getenv("PFW_MAX_DOCUMENT_BYTES", str(_DEFAULT_MAX_DOCUMENT_BYTES)))
        )
    except (TypeError, ValueError):
        logger.warning("Invalid PFW_MAX_DOCUMENT_BYTES; using the default")
        return _DEFAULT_MAX_DOCUMENT_BYTES


#: The gate between the FREE PyPDF2 tier and the PAID Mistral OCR tier. Four
#: bare literals used to sit inline in is_good_extraction with only comments to
#: explain them (audit R-5): a threshold slightly too strict silently moves
#: traffic to a metered tier, and a reader could not tell which check fired
#: without adding a print. Every other cost-relevant knob in this repo is an
#: env var with a documented default, so these are too.
_MIN_EXTRACTED_CHARS = int(os.getenv("PFW_EXTRACT_MIN_CHARS", "50"))
_MIN_EXTRACTED_WORDS = int(os.getenv("PFW_EXTRACT_MIN_WORDS", "10"))
_MAX_AVG_WORD_LENGTH = float(os.getenv("PFW_EXTRACT_MAX_AVG_WORD_LEN", "20"))
_MIN_ALPHA_RATIO = float(os.getenv("PFW_EXTRACT_MIN_ALPHA_RATIO", "0.6"))


def extraction_reject_reason(text: str) -> Optional[str]:
    """None when the free-tier extraction is usable, else the failing check.

    The reason is returned rather than swallowed because a rejection here
    escalates to a metered tier.
    """
    if not text or len(text.strip()) < _MIN_EXTRACTED_CHARS:
        return f"too_short (<{_MIN_EXTRACTED_CHARS} chars)"

    words = text.split()
    if len(words) < _MIN_EXTRACTED_WORDS:
        return f"too_few_words (<{_MIN_EXTRACTED_WORDS})"

    if len(text) / len(words) > _MAX_AVG_WORD_LENGTH:
        return f"avg_word_length (>{_MAX_AVG_WORD_LENGTH})"

    if sum(1 for c in text if c.isalpha()) / len(text) < _MIN_ALPHA_RATIO:
        return f"alpha_ratio (<{_MIN_ALPHA_RATIO})"

    return None


#: Grant year at which the USPTO PTGRXML full-text dataset starts being served
#: by the ODP associated-documents endpoint. PROBE-VERIFIED 2026-08-30 against
#: api.uspto.gov: sampled grants from 2003 and 2004 (apps 10050679/6651599,
#: 29184029/D484361, 10881461/6835620, 10876438/6836370) return an
#: associated-documents record with NO grantDocumentMetaData at all, while 2005
#: grants (11194161/6979058, 11188738/6979247) and later do carry it. The old
#: error message said "application may not be granted", which is wrong and
#: misleading for a patent that plainly granted (OPEN_ITEMS #6).
PTGRXML_FIRST_SERVED_GRANT_YEAR = 2005

class AuthoredClientError(ValueError):
    """A caller-facing message this server wrote itself.

    The sanitizing catch-all (_handle_client_error, 0d81c91) is right to hide
    exception text that may embed upstream URLs, paths or provider output. It
    was wrong to hide THESE: fixed strings authored here (the pre-2005 grant
    coverage boundary, "no application XML available") that carry nothing
    sensitive and exist precisely so the caller learns why. Freddie eval
    tr-cov-43 caught the regression: the coverage message came back as a
    generic 500, which is what an agent retries. Raise this class for such
    messages and the XML error path returns them verbatim as a 404.
    """


PTGRXML_NOT_SERVED_MESSAGE = (
    "Granted patent XML (PTGRXML) is not served for this grant. The USPTO "
    f"full-text grant XML dataset starts with patents issued in "
    f"{PTGRXML_FIRST_SERVED_GRANT_YEAR} (probe-verified 2026-08-30: 2004 and "
    "earlier grants carry no grantDocumentMetaData), so this is a coverage "
    "boundary, not evidence that the application was never granted. The file "
    "wrapper itself is still available: use PFW_get_application_documents "
    "(document_code='CLM'|'SPEC'|'ABST'|'DRW') plus "
    "PFW_get_document_content_with_ocr, or read the grant face on Google Patents."
)

#: How many of the executed name-variant queries `queries_used` displays.
_INVENTOR_QUERIES_SHOWN = 5


def _build_inventor_response(
    *,
    name: str,
    strategy: str,
    limit: int,
    all_results: List[Dict[str, Any]],
    queries: List[str],
    queries_generated: int,
    queries_failed: int,
    sub_query_limit: int,
) -> Dict[str, Any]:
    """Envelope for the inventor fan-out, with counts that match their lists.

    Extracted from search_inventor (mechanical decomposition, no behavior
    change) to keep that method off ruff's C901 list.
    """
    # The count must describe the list that is actually returned:
    # `total_unique_applications` used to be computed from `all_results` BEFORE
    # the [:limit] slice, so a trimmed response advertised a count its own list
    # contradicted.
    returned = all_results[:limit]
    discovered = len(all_results)
    response: Dict[str, Any] = {
        "success": True,
        "inventor_name": name,
        "strategy": strategy,
        "total_unique_applications": len(returned),
        "unique_applications": returned,
        "unique_applications_discovered": discovered,
        "paging": {
            "limit_requested": limit,
            "limit_applied": limit,
            "offset": 0,
            "returned": len(returned),
            # The fan-out de-duplicates across several name-variant queries, so
            # there is no server-side total to report and one is never guessed.
            "total": None,
            "has_more": discovered > len(returned),
            "next_offset": None,
        },
        # Only the first few are shown; the counters say so rather than letting
        # `queries_used` imply the whole set.
        "queries_used": queries[:_INVENTOR_QUERIES_SHOWN],
        "queries_used_shown": min(_INVENTOR_QUERIES_SHOWN, len(queries)),
        "queries_generated": queries_generated,
        "queries_executed": len(queries),
        "sub_query_limit": sub_query_limit,
    }
    if queries_generated > len(queries):
        response["queries_note"] = (
            f"This inventor name generated {queries_generated} query variants; "
            f"only the first {len(queries)} were executed (MAX_INVENTOR_QUERIES). "
            "Some matching applications may be missing — narrow the name or use "
            "strategy='exact' for a deterministic set."
        )
    if sub_query_limit < limit:
        response["sub_query_limit_note"] = (
            f"Each of the {len(queries)} name-variant queries fetched at most "
            f"{sub_query_limit} applications before de-duplication, so fewer than "
            f"limit={limit} unique results does not mean the portfolio is exhausted."
        )
    # Aggregate failure reporting (audit F26): silent partial results look
    # identical to complete ones otherwise.
    if queries_failed:
        response["queries_failed"] = queries_failed
        response["partial_results_note"] = (
            f"{queries_failed} of {len(queries)} executed search queries failed; "
            "results may be incomplete."
        )
    return response


#: How many versions of each granted-patent component (ABST/DRW/SPEC/CLM) the
#: package fetch retrieves before the min()/max() date selection. Claims
#: histories routinely run past this; the fetch size is deliberately unchanged
#: (it is one round trip per component) but every component now reports
#: versions_considered / versions_available so a capped selection is visible.
GRANTED_COMPONENT_FETCH_LIMIT = 5


def _pdf_page_count(doc: Dict[str, Any]) -> int:
    """PDF page count from a document's downloadOptionBag, 0 when absent."""
    pdf = next(
        (o for o in doc.get("downloadOptionBag", []) if o.get("mimeTypeIdentifier") == "PDF"),
        None,
    )
    count = (pdf or {}).get("pageTotalQuantity")
    return count if isinstance(count, int) else 0


def _select_complete_version(documents):
    """Pick the most complete version of a multi-version component.

    Amendment papers share the component's document code (a
    replacement-paragraphs filing is coded SPEC exactly like the original
    specification), so recency is the wrong axis: the newest entry can be a
    2-page delta. The complete document is the one with the most PDF pages;
    on a page-count tie the earliest officialDate wins (the original filing).
    """
    return sorted(
        documents,
        key=lambda d: (-_pdf_page_count(d), d.get("officialDate") or "9999"),
    )[0]


def _resolve_page_count(pdf_option: Dict[str, Any], pdf_content: bytes):
    """Return ``(page_count, source)`` — never a fabricated number.

    ``pageTotalQuantity`` used to be read with a ``0`` default, so a document
    whose metadata omitted the field was reported as having zero pages, which
    also made any "did the cap fire?" comparison silently false. Order:
    the documentBag's own count, else the PDF bytes, else ``None`` with
    source ``"unknown"``.
    """
    raw = pdf_option.get('pageTotalQuantity')
    if isinstance(raw, bool):
        raw = None
    if isinstance(raw, int) and raw > 0:
        return raw, "downloadOptionBag"
    if isinstance(raw, str) and raw.strip().isdigit() and int(raw) > 0:
        return int(raw), "downloadOptionBag"
    if PDF_AVAILABLE and pdf_content:
        try:
            import io

            import PyPDF2

            return len(PyPDF2.PdfReader(io.BytesIO(pdf_content)).pages), "pdf"
        except Exception as e:  # pragma: no cover - malformed PDF
            logger.debug(f"Could not recover page count from PDF bytes: {type(e).__name__}: {e}")
    return None, "unknown"


def slice_pdf_pages(pdf_content: bytes, page_from: int, page_to: Optional[int]):
    """Return ``(sliced_bytes, first_page, last_page, total_pages)`` for the
    requested 1-based inclusive page window.

    Exists so a page RANGE is reachable at all (OPEN_ITEMS #11): the extraction
    tiers each carry their own per-document page cap (PYPDF_MAX_PAGES,
    MISTRAL_OCR_MAX_PAGES), so on a 104-page document the pages past the cap
    were unreachable by any parameter. Slicing the PDF before the tiers run
    makes the cap apply to the WINDOW, so page_from=51 reaches page 51 onward.

    Returns ``(pdf_content, None, None, total)`` unchanged when the window
    covers the whole document, and raises ValueError when the window is empty.
    """
    if not PDF_AVAILABLE:
        raise ValueError("PyPDF2 is not available, so page ranges cannot be applied")

    import io

    import PyPDF2

    reader = PyPDF2.PdfReader(io.BytesIO(pdf_content))
    total = len(reader.pages)
    first = max(1, int(page_from))
    last = total if page_to is None else min(int(page_to), total)
    if first > total:
        raise ValueError(
            f"page_from={first} is past the end of this {total}-page document"
        )
    if last < first:
        raise ValueError(f"page_to={last} is before page_from={first}")
    if first == 1 and last == total:
        return pdf_content, None, None, total

    writer = PyPDF2.PdfWriter()
    for index in range(first - 1, last):
        writer.add_page(reader.pages[index])
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue(), first, last, total


def _extraction_failure_advice(mistral_key_present: bool, docling_client, page_count) -> str:
    """What to actually DO when every extraction tier failed.

    This used to be one unconditional sentence telling the reader to set
    MISTRAL_API_KEY, and it fired even when Docling WAS configured and had
    simply refused a document for being longer than DOCLING_MAX_PAGES. That
    reads as "this deployment has no OCR" when the true answer is "ask for
    fewer pages": the advice is now conditional on what is configured, and the
    page-cap case names the two dials that solve it (`page_from`/`page_to` on
    the call, `DOCLING_MAX_PAGES` on the deployment). MISTRAL_API_KEY is
    mentioned ONLY when no Docling URL is configured — suggesting a metered
    vendor to an operator who already runs a free one is the wrong advice.
    """
    docling_configured = docling_client.is_available()
    over_page_limit = (
        docling_configured
        and isinstance(page_count, int)
        and not docling_client.within_page_limit(page_count)
    )

    if over_page_limit:
        return (
            f"Docling OCR is configured, but this document is {page_count} pages and "
            f"DOCLING_MAX_PAGES={docling_client.max_pages}, so it was skipped. Re-run "
            f"with a page window of at most {docling_client.max_pages} pages "
            f"(page_from=1, page_to={docling_client.max_pages}, then page_from="
            f"{docling_client.max_pages + 1}, ...), or raise DOCLING_MAX_PAGES on the "
            "docling deployment — EasyOCR runs roughly 10-30s per page on CPU, which is "
            "why the cap exists."
        )

    if docling_configured:
        return (
            "Docling OCR is configured but recovered no usable text from this document. "
            "A narrower page window (page_from/page_to) sometimes succeeds where the "
            "whole document does not."
        )

    advice = (
        "Set DOCLING_SERVE_URL to enable self-hosted Docling OCR "
        "(e.g. http://localhost:5001 or https://docling.[yourdomain].com); it caps at "
        f"DOCLING_MAX_PAGES={docling_client.max_pages} pages per call, so pair it with a "
        "page_from/page_to window on long documents."
    )
    if not mistral_key_present:
        advice += " Or add MISTRAL_API_KEY to enable Mistral OCR."
    return advice


def _page_window_markers(first, last, total, applied: bool, note: str) -> Dict[str, Any]:
    """What the response says about a requested page range."""
    return {
        "page_window": {
            "applied": applied,
            "page_from": first,
            "page_to": last,
            "pages_in_window": (last - first + 1) if (applied and first and last) else None,
            "page_count_total": total,
            "note": note,
        }
    }


def _page_cap_markers(
    *, pages_truncated: int, pages_returned, pages_total, note: str
) -> Dict[str, Any]:
    """Marker block for an extraction that stopped at a PAGE cap.

    A page cap means pages were never extracted at all, so it is a `_bounds`
    marker with reason "window" counting PAGES — NOT a `_window` marker, whose
    counters are contractually characters of text the caller is holding (see
    shared/response_bounds.py). The legacy `truncated`/`truncation_note` keys
    are kept alongside it for this release.
    """
    from ..shared.response_bounds import BOUNDS_KEY, REASON_WINDOW, STAGE_TRUNCATED

    return {
        "pages_truncated": pages_truncated,
        "truncated": True,
        "truncation_note": note,
        BOUNDS_KEY: {
            "applied": True,
            "reason": REASON_WINDOW,
            "size_chars": None,
            "size_limit": None,
            "stages": [STAGE_TRUNCATED],
            "slimmed_fields": [],
            "items_returned": pages_returned,
            "items_total": pages_total,
            "note": note,
        },
    }


# Resilience primitives live in api/resilience.py (audit F3); re-exported
# here for backward compatibility (tests and older imports).
from .resilience import (  # noqa: E402, F401
    CircuitBreaker,
    CircuitState,
    ResponseCache,
    RetryBudget,
)


# The USPTO PFW API signals "zero matching records" with HTTP 404 rather
# than an empty result set, so every no-results search surfaced as a raw
# error envelope instead of a normal (empty) success response. Applied at
# the search_applications chokepoint only — a 404 on a by-id lookup
# (application details, document lists, downloads) is a real error and is
# deliberately NOT touched by this helper.
#
# format_error_response() (api/helpers.py) puts "error": True (a bool, not
# text) and the API's raw response body in "message" — e.g.
# 'API error: {"error":"Not Found","errorDetails":"No matching records
# found, refine your search criteria and try again"}'. The marker check
# below must test "message" (and status_code), not "error".
_NO_MATCH_MARKER = "No matching records found"

_NO_MATCH_NOTE = (
    "No matching records for this query (the USPTO PFW API reports an "
    "empty result set as HTTP 404). Try broadening the search: use a "
    "shorter or partial applicant/inventor name, drop other filters "
    "(art_unit, examiner_name, date ranges), or double-check the "
    "application number format."
)


def _is_no_matches_error(result: Dict[str, Any]) -> bool:
    """True when a raw search_applications error response is the USPTO
    no-matching-records 404 (as opposed to a real error — auth failure,
    rate limit, malformed query, server error, etc.)."""
    return (
        isinstance(result, dict)
        and result.get("status_code") == 404
        and _NO_MATCH_MARKER in str(result.get("message", ""))
    )


def _handle_client_error(operation: str, e: Exception) -> Dict[str, Any]:
    """Log a caught exception server-side and return a SANITIZED envelope.

    Nine call sites below returned `f"{operation}: {str(e)}"` straight to the
    caller with no log line at all: the operator saw nothing, and the caller
    got whatever the exception happened to embed (upstream URLs, file paths,
    provider error text). The detail is not lost where it is wanted —
    `format_error_response` still attaches the exception type, args and a
    sanitized traceback when ENVIRONMENT is a development one.
    """
    logger.exception(f"{operation} ({type(e).__name__})")
    return format_error_response(operation, exception=e)


class EnhancedPatentClient:
    """Enhanced client for USPTO Patent File Wrapper API"""

    # Constants for better readability and maintainability
    DEFAULT_LIMIT = 10
    MIN_SEARCH_LIMIT = 1
    # The USPTO search endpoint clamps `pagination.limit` to 100 — see
    # search_applications below, which has always sent min(limit, 100). This
    # constant used to be 1000 and models/search_params.py rejected anything
    # over 500, so a caller could ask for 500, be accepted at both layers, and
    # silently receive at most 100 while the envelope echoed "limit": 500.
    # 100 is the honest ceiling because it is what the wire actually does; all
    # three layers now agree. Page past it with offset=.
    MAX_SEARCH_LIMIT = 100
    #: Per-sub-query wire limit for the inventor fan-out (search_inventor runs
    #: several name-variant queries and de-duplicates). Reported as
    #: `sub_query_limit` so a short result set is never mistaken for exhaustion.
    INVENTOR_SUBQUERY_LIMIT = 50
    MAX_CONCURRENT_REQUESTS = 10
    MAX_QUERY_LENGTH = 1000
    MAX_NAME_LENGTH = 200

    # Retry configuration
    RETRY_ATTEMPTS = 3
    RETRY_DELAY = 1.0  # Base delay in seconds
    RETRY_BACKOFF = 2  # Exponential backoff multiplier

    def __init__(self, api_key: Optional[str] = None):
        self.base_url = "https://api.uspto.gov/api/v1/patent/applications"

        # Load API key with unified secure storage support.
        # Bound BEFORE the try: it used to be assigned only inside it, so a
        # secure-store read that raised left the attribute unset and the
        # `if not self.api_key` two lines down raised AttributeError — before
        # the documented USPTO_API_KEY fallback could run at all.
        self.api_key: Optional[str] = None

        if api_key:
            self.api_key = api_key
        else:
            # Try to load from unified secure storage first, then fall back to environment
            try:
                from ..shared_secure_storage import get_uspto_api_key
                self.api_key = get_uspto_api_key()
            except Exception as e:
                # Fall back to environment variable if secure storage fails
                logger.warning(
                    f"Secure storage unavailable ({type(e).__name__}); "
                    "falling back to USPTO_API_KEY"
                )

            # If still no key, try environment variable
            if not self.api_key:
                self.api_key = os.getenv("USPTO_API_KEY")

            # Final validation
            if not self.api_key:
                raise AuthenticationError("USPTO_API_KEY is required. Set environment variable or use unified secure storage.")
        self.headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        # Configurable timeouts from environment variables (with fallbacks)
        self.default_timeout = float(os.getenv("USPTO_TIMEOUT", "30.0"))
        self.download_timeout = float(os.getenv("USPTO_DOWNLOAD_TIMEOUT", "60.0"))
        self.ocr_timeout = float(os.getenv("MISTRAL_OCR_TIMEOUT", "30.0"))
        # Mistral OCR model slug. Default `mistral-ocr-latest` tracks Mistral's
        # current GA model (= OCR 4 as of 2026-06-23); pin a dated slug
        # (e.g. mistral-ocr-2503, mistral-ocr-4-0) via MISTRAL_OCR_MODEL.
        self.mistral_ocr_model = os.getenv("MISTRAL_OCR_MODEL", "mistral-ocr-latest")
        logger.info(f"Timeout configuration: default={self.default_timeout}s, download={self.download_timeout}s, ocr={self.ocr_timeout}s")

        # Separate connection pools for bulkhead pattern (resource isolation)
        self.api_limits = httpx.Limits(
            max_keepalive_connections=5,
            max_connections=10
        )
        self.download_limits = httpx.Limits(
            max_keepalive_connections=2,
            max_connections=5
        )
        self.ocr_limits = httpx.Limits(
            max_keepalive_connections=1,
            max_connections=3
        )
        logger.info("Connection pools configured: API=10, Download=5, OCR=3")

        # HTTP call path lives in USPTOTransport (audit F3): semaphore,
        # retry loop, circuit breaker, response cache, retry budget.
        from .transport import USPTOTransport
        self.transport = USPTOTransport(
            base_url=self.base_url,
            headers=self.headers,
            default_timeout=self.default_timeout,
            api_limits=self.api_limits,
            max_retries_per_hour=int(os.getenv("USPTO_MAX_RETRIES_PER_HOUR", "100")),
        )
        # Aliases: health endpoint and existing callers read these off the client
        self.semaphore = self.transport.semaphore
        self.circuit_breaker = self.transport.circuit_breaker
        self.response_cache = self.transport.response_cache
        self.retry_budget = self.transport.retry_budget

        # Mistral OCR configuration - check unified secure storage first, then environment
        raw_mistral_key = None
        try:
            from ..shared_secure_storage import get_mistral_api_key
            raw_mistral_key = get_mistral_api_key()
        except Exception:
            # Fall back to environment variable if secure storage fails
            pass

        # If still no key, try environment variable
        if not raw_mistral_key:
            raw_mistral_key = os.getenv("MISTRAL_API_KEY")

        self.mistral_api_key = self._validate_mistral_api_key(raw_mistral_key)
        self.mistral_base_url = "https://api.mistral.ai/v1"

        # Constructed ONCE. DoclingClient re-reads DOCLING_SERVE_URL,
        # DOCLING_TIMEOUT and DOCLING_MAX_PAGES per instantiation, and it used
        # to be built separately inside extract_with_docling and
        # _run_pdf_tiers, so the "is it configured / within the page limit"
        # decision and the actual call read the environment twice and could
        # disagree (audit design-pattern F-4). It also makes the tier testable
        # without env manipulation.
        self.docling_client = DoclingClient()

        # Single Mistral OCR implementation lives in OCRService (audit F1);
        # it owns rate limiting, the model slug, and the page cap.
        from ..services.ocr_service import OCRService
        self.ocr_service = OCRService(
            api_key=self.mistral_api_key,
            model=self.mistral_ocr_model,
            timeout=self.ocr_timeout,
            limits=self.ocr_limits,
        )

    def _validate_mistral_api_key(self, raw_key: Optional[str]) -> Optional[str]:
        """Delegates to services.ocr_service.validate_mistral_api_key.

        This method used to carry its OWN placeholder list, and the two had
        already drifted: a key set to `change_me` was caught here but
        `temp_key` only at the second gate (audit D-2). One owner now.
        """
        from ..services.ocr_service import validate_mistral_api_key

        return validate_mistral_api_key(raw_key)

    async def _make_request(self, endpoint: str, method: str = "GET", **kwargs) -> Dict[str, Any]:
        """Make HTTP request to the PFW API — delegates to USPTOTransport
        (audit F3), which owns the semaphore/retry/breaker/cache/budget."""
        return await self.transport.request(endpoint, method, **kwargs)


    async def search_applications(self, query: str, limit: int = 10, offset: int = 0, fields: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Search applications using Patent File Wrapper API with optional field filtering

        Args:
            query: Search query using Patent File Wrapper syntax
            limit: Maximum number of results
            offset: Starting position
            fields: Optional list of fields to retrieve for context reduction
        """
        try:
            # The wire ceiling is authoritative: whatever the caller asked for,
            # the USPTO endpoint will not return more than MAX_SEARCH_LIMIT.
            # `limit_applied` is what the envelope reports (audit: it used to
            # echo the REQUESTED limit, actively asserting a false number).
            limit_applied = max(
                self.MIN_SEARCH_LIMIT, min(int(limit), self.MAX_SEARCH_LIMIT)
            )
            # Always use POST for the search endpoint as per USPTO API spec
            body = {
                "q": query,
                "pagination": {
                    "limit": limit_applied,
                    "offset": offset
                },
                "sort": [
                    {
                        "field": "applicationMetaData.filingDate",
                        "order": "desc"
                    }
                ]
            }

            # Add fields array if specified, with mapping to API field names
            if fields:
                api_fields = map_user_fields_to_api_fields(fields)
                body["fields"] = api_fields
                logger.debug(f"Mapped user fields {fields} to API fields {api_fields}")

            result = await self._make_request("search", method="POST", json=body)

            no_matches = False
            if result.get('error'):
                if _is_no_matches_error(result):
                    no_matches = True
                    result = {"patentFileWrapperDataBag": [], "count": 0}
                else:
                    return result

            # Extract applications from patentFileWrapperDataBag
            applications = result.get('patentFileWrapperDataBag', [])

            # Add application numbers at the top level for easier access
            for app in applications:
                if not app.get('applicationNumberText'):
                    # Try to extract from metadata
                    metadata = app.get('applicationMetaData', {})
                    app_number = None
                    # The app number might be in different places, try to find it
                    if 'applicationNumberText' in metadata:
                        app_number = metadata['applicationNumberText']
                    # Add it to the top level if found
                    if app_number:
                        app['applicationNumberText'] = app_number

            total = result.get('count', len(applications))
            has_more = isinstance(total, int) and (offset + len(applications)) < total
            response = {
                "success": True,
                "count": len(applications),
                "total": total,
                "query": query,
                "applications": applications,
                # `limit` now reports what was APPLIED, not what was requested;
                # `paging` carries both so any future drift stays visible.
                "limit": limit_applied,
                "offset": offset,
                "paging": {
                    "limit_requested": limit,
                    "limit_applied": limit_applied,
                    "offset": offset,
                    "returned": len(applications),
                    "total": total if isinstance(total, int) else None,
                    "has_more": has_more,
                    "next_offset": offset + len(applications) if has_more else None,
                },
                "request_id": result.get('requestIdentifier')
            }
            if no_matches:
                response["note"] = _NO_MATCH_NOTE
            return response

        except Exception as e:
            return _handle_client_error("Application search failed", e)

    async def search_inventor(self, name: str, strategy: str = "comprehensive", limit: int = 10, fields: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Enhanced inventor search using multiple strategies with optional field filtering

        Args:
            name: Inventor name to search for
            strategy: Search strategy - 'exact', 'fuzzy', or 'comprehensive'
            limit: Maximum number of results to return
            fields: Optional list of fields to retrieve for context reduction
        """
        try:
            queries, queries_generated = create_inventor_queries(
                name, strategy, with_totals=True
            )
            all_results = []
            seen_apps = set()
            queries_failed = 0
            sub_query_limit = max(
                self.MIN_SEARCH_LIMIT, min(int(limit), self.INVENTOR_SUBQUERY_LIMIT)
            )

            for query in queries:
                try:
                    result = await self.search_applications(query, sub_query_limit, 0, fields)

                    # search_applications catches every exception itself and
                    # returns an error ENVELOPE, so the `except` below could
                    # never fire and queries_failed was always 0: a caller
                    # could not tell "this name has no applications" from
                    # "six of eight name-variant queries failed"
                    # (audit exception-flow F-5).
                    if result.get('error'):
                        queries_failed += 1
                        continue

                    if result.get('applications'):
                        for app in result['applications']:
                            app_id = app.get('applicationNumberText')
                            if app_id and app_id not in seen_apps:
                                seen_apps.add(app_id)
                                all_results.append(app)

                            if len(all_results) >= limit:
                                break

                    if len(all_results) >= limit:
                        break

                except Exception as e:
                    # Never log the query text — user search intent is work-product
                    queries_failed += 1
                    logger.warning(f"Search query failed ({type(e).__name__}): {e}")
                    continue

            return _build_inventor_response(
                name=name,
                strategy=strategy,
                limit=limit,
                all_results=all_results,
                queries=queries,
                queries_generated=queries_generated,
                queries_failed=queries_failed,
                sub_query_limit=sub_query_limit,
            )

        except Exception as e:
            return _handle_client_error("Inventor search failed", e)

    async def enhance_search_results_with_associated_docs(self, search_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enhance search results by adding associated documents metadata for each application

        Args:
            search_results: Results from search_applications or search_inventor

        Returns:
            Enhanced results with associated documents metadata
        """
        try:
            if not search_results.get("success") or not search_results.get("applications"):
                return search_results

            enhanced_applications = []

            for app in search_results["applications"]:
                # Get application number
                app_number = app.get("applicationNumberText")
                if not app_number:
                    # Try to get from metadata
                    app_number = app.get("applicationMetaData", {}).get("applicationNumberText")

                if app_number:
                    # Get associated documents for this application
                    assoc_docs_result = await self.get_associated_documents(app_number)

                    if assoc_docs_result.get("success"):
                        app["associatedDocuments"] = {
                            "count": assoc_docs_result.get("count", 0),
                            "documents": assoc_docs_result.get("associated_documents", []),
                            "xmlContentAvailable": assoc_docs_result.get("count", 0) > 0
                        }

                        # Add convenience flags for XML availability
                        docs = assoc_docs_result.get("associated_documents", [])
                        if docs:
                            for doc in docs:
                                if doc.get("grantDocumentMetaData"):
                                    app["associatedDocuments"]["ptgrXmlAvailable"] = True
                                if doc.get("pgpubDocumentMetaData"):
                                    app["associatedDocuments"]["appXmlAvailable"] = True
                    else:
                        app["associatedDocuments"] = {
                            "count": 0,
                            "documents": [],
                            "xmlContentAvailable": False,
                            "error": "Failed to retrieve associated documents"
                        }
                else:
                    app["associatedDocuments"] = {
                        "count": 0,
                        "documents": [],
                        "xmlContentAvailable": False,
                        "error": "No application number found"
                    }

                enhanced_applications.append(app)

            # Update the search results
            enhanced_results = search_results.copy()
            enhanced_results["applications"] = enhanced_applications
            enhanced_results["associatedDocumentsIncluded"] = True
            enhanced_results["llmGuidance"] = {
                "workflowPattern": {
                    "discovery": "Use PFW_search_applications_balanced for comprehensive discovery WITHOUT prosecution docs",
                    "quickPatentLookup": "Use PFW_search_applications_minimal for optimized patent-to-app mapping + XML metadata",
                    "xmlAnalysis": "Use PFW_get_patent_or_application_xml for structured content analysis",
                    "prosecutionDocs": "Use PFW_get_application_documents for targeted document access",
                    "pdfDownloads": "Use applicationNumberText + document_identifier with PFW_get_document_*",
                    "inventorAnalysis": "Use PFW_search_inventor_minimal for portfolio analysis with XML metadata"
                },
                "criticalApplicationCentricRules": {
                    "xmlAccess": "PFW_get_patent_or_application_xml requires applicationNumberText (now via minimal search)",
                    "documentAccess": "PFW_get_application_documents requires applicationNumberText for prosecution docs",
                    "documentDownload": "PFW_get_document_download requires applicationNumberText + document_identifier from PFW_get_application_documents",
                    "ocrExtraction": "PFW_get_document_content_with_ocr requires applicationNumberText + document_identifier from PFW_get_application_documents",
                    "proxyDownload": "PFW_get_document_download requires applicationNumberText + document_identifier from PFW_get_application_documents",
                    "patentNumbers": "Patent numbers mapped to applicationNumberText via enhanced minimal search (single call)"
                },
                "optimizedWorkflowSequence": {
                    "discovery_workflow": [
                        "1. Use balanced search for discovery (20-50 applications)",
                        "2. Review results and select applications of interest",
                        "3. Use XML tool for content analysis",
                        "4. Use document tool only if prosecution docs needed"
                    ],
                    "patent_analysis_workflow": [
                        "1. Patent number → Minimal search → applicationNumberText + XML metadata",
                        "2. Use PFW_get_patent_or_application_xml for structured analysis",
                        "3. Use PFW_get_application_documents if prosecution history needed"
                    ]
                },
                "session_4_optimization": {
                    "problem_solved": "Token explosion from documentBag in discovery searches",
                    "solution": "Dedicated document tool for targeted prosecution access",
                    "efficiency_gain": "20-50x more applications can fit in discovery context",
                    "workflow_clarity": "Clear separation: discovery → analysis → documents"
                },
                "tool_selection_guidance": {
                    "for_discovery": "Use balanced search - comprehensive metadata without document noise",
                    "for_content": "Use XML tool - structured patent content for AI analysis",
                    "for_documents": "Use document tool - prosecution history when legal workflow needed"
                },
                "dataLimitation": "XML content only available for patents/applications filed after January 1, 2001"
            }

            return enhanced_results

        except Exception as e:
            logger.error(f"Failed to enhance search results with associated docs: {str(e)}")
            # Return original results if enhancement fails
            search_results["associatedDocumentsError"] = str(e)
            return search_results

    async def get_application_data(self, app_number: str) -> Dict[str, Any]:
        """
        Get complete application data including metadata

        Args:
            app_number: Patent application number
        """
        try:
            app_number = validate_app_number(app_number)

            # Get application data
            result = await self._make_request(app_number)

            if result.get('error'):
                return result

            # Extract the first (and should be only) application from the response
            applications = result.get('patentFileWrapperDataBag', [])
            if not applications:
                return format_error_response(f"No data found for application {app_number}")

            app_data = applications[0]

            # Also get documents summary
            docs_result = await self.get_documents(app_number)

            return {
                "success": True,
                "application_number": app_number,
                "application_data": app_data,
                "documents_summary": docs_result.get('summary', {}) if not docs_result.get('error') else None,
                "request_id": result.get('requestIdentifier')
            }

        except Exception as e:
            return _handle_client_error("Failed to get application data", e)

    async def get_associated_documents(self, app_number: str) -> Dict[str, Any]:
        """
        Get associated documents metadata for an application (XML files)

        Args:
            app_number: Patent application number

        Returns:
            Dict containing APPXML and PTGRXML metadata with file locations
        """
        try:
            app_number = validate_app_number(app_number)

            # Use the associated-documents endpoint
            endpoint = f"{app_number}/associated-documents"
            result = await self._make_request(endpoint)

            if result.get('error'):
                return result

            return {
                "success": True,
                "application_number": app_number,
                "count": result.get('count', 0),
                "associated_documents": result.get('patentFileWrapperDataBag', []),
                "request_id": result.get('requestIdentifier')
            }

        except Exception as e:
            return _handle_client_error("Failed to get associated documents", e)

    async def get_continuity(self, app_number: str) -> Dict[str, Any]:
        """
        Get continuity (family) data for an application

        The ODP /continuity response carries parentContinuityBag and/or
        childContinuityBag. Either bag can be ABSENT — a childless application
        returns only parentContinuityBag, a root application returns only
        childContinuityBag. The *_bag_present flags below preserve that
        distinction so callers can say "no children" instead of "no family".

        Args:
            app_number: Patent application number

        Returns:
            Dict with parent_continuity_bag / child_continuity_bag and their
            presence flags
        """
        try:
            app_number = validate_app_number(app_number)

            endpoint = f"{app_number}/continuity"
            result = await self._make_request(endpoint)

            if result.get('error'):
                return result

            wrappers = result.get('patentFileWrapperDataBag', [])
            wrapper = wrappers[0] if wrappers else {}

            return {
                "success": True,
                "application_number": app_number,
                "parent_continuity_bag": wrapper.get('parentContinuityBag', []),
                "child_continuity_bag": wrapper.get('childContinuityBag', []),
                "parent_bag_present": 'parentContinuityBag' in wrapper,
                "child_bag_present": 'childContinuityBag' in wrapper,
                "request_id": result.get('requestIdentifier'),
            }

        except Exception as e:
            return _handle_client_error("Failed to get continuity data", e)

    async def get_foreign_priority(self, app_number: str) -> Dict[str, Any]:
        """
        Get foreign priority claims for an application

        Args:
            app_number: Patent application number

        Returns:
            Dict containing the raw foreignPriorityBag entries
            (ipOfficeName / applicationNumberText / filingDate)
        """
        try:
            app_number = validate_app_number(app_number)

            endpoint = f"{app_number}/foreign-priority"
            result = await self._make_request(endpoint)

            if result.get('error'):
                return result

            wrappers = result.get('patentFileWrapperDataBag', [])
            wrapper = wrappers[0] if wrappers else {}

            return {
                "success": True,
                "application_number": app_number,
                "foreign_priority_bag": wrapper.get('foreignPriorityBag', []),
                "foreign_priority_bag_present": 'foreignPriorityBag' in wrapper,
                "request_id": result.get('requestIdentifier'),
            }

        except Exception as e:
            return _handle_client_error("Failed to get foreign priority data", e)

    async def get_term_adjustment(self, app_number: str) -> Dict[str, Any]:
        """
        Get patent term adjustment (PTA) data for an application

        Args:
            app_number: Patent application number

        Returns:
            Dict containing the raw patentTermAdjustmentData object
        """
        try:
            app_number = validate_app_number(app_number)

            endpoint = f"{app_number}/adjustment"
            result = await self._make_request(endpoint)

            if result.get('error'):
                return result

            wrappers = result.get('patentFileWrapperDataBag', [])
            wrapper = wrappers[0] if wrappers else {}

            return {
                "success": True,
                "application_number": app_number,
                "term_adjustment_data": wrapper.get('patentTermAdjustmentData', {}),
                "term_adjustment_data_present": 'patentTermAdjustmentData' in wrapper,
                "request_id": result.get('requestIdentifier'),
            }

        except Exception as e:
            return _handle_client_error("Failed to get term adjustment data", e)

    async def get_documents(
        self,
        app_number: str,
        limit: Optional[int] = None,
        document_code: Optional[str] = None,
        direction_category: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get documents list for an application with optional filtering

        Args:
            app_number: Patent application number
            limit: Maximum number of documents to return (applied AFTER filtering)
            document_code: Filter by specific document code (e.g., 'NOA', 'FWCLM', 'CTFR')
                          Case-insensitive exact match
            direction_category: Filter by document direction: 'INCOMING', 'OUTGOING', or 'INTERNAL'
                               Case-insensitive exact match
        """
        try:
            app_number = validate_app_number(app_number)

            # Fetch ALL documents from USPTO API (no server-side filtering available)
            result = await self._make_request(f"{app_number}/documents")

            if result.get('error'):
                return result

            documents = result.get('documentBag', [])

            # Track filtering for summary
            filtering_applied = []
            original_count = len(documents)

            # Apply document_code filter (client-side)
            if document_code:
                filtered_docs = [
                    doc for doc in documents
                    if doc.get('documentCode', '').upper() == document_code.upper()
                ]
                documents = filtered_docs
                filtering_applied.append(f"document_code='{document_code}'")

            # Apply direction_category filter (client-side)
            if direction_category:
                filtered_docs = [
                    doc for doc in documents
                    if doc.get('directionCategory', '').upper() == direction_category.upper()
                ]
                documents = filtered_docs
                filtering_applied.append(f"direction_category='{direction_category}'")

            # Apply limit AFTER filtering. `matched_count` is the number that
            # PASSED the filters, before the limit — without it a caller cannot
            # tell "there were exactly 5" from "we only looked at 5".
            matched_count = len(documents)
            if limit and len(documents) > limit:
                documents = documents[:limit]
                filtering_applied.append(f"limit={limit}")

            # Create summary
            doc_types = {}
            download_options = 0
            pdf_docs = []

            for doc in documents:
                doc_code = doc.get('documentCode', 'Unknown')
                doc_types[doc_code] = doc_types.get(doc_code, 0) + 1

                # Count download options and track PDF availability
                for option in doc.get('downloadOptionBag', []):
                    download_options += 1
                    if option.get('mimeTypeIdentifier') == 'PDF':
                        pdf_docs.append({
                            'document_code': doc_code,
                            'document_description': doc.get('documentCodeDescriptionText', ''),
                            'official_date': doc.get('officialDate', ''),
                            'document_identifier': doc.get('documentIdentifier', ''),
                            'page_count': option.get('pageTotalQuantity', 0),
                            'download_url': option.get('downloadUrl', '')
                        })

            # Build filtering summary message
            filter_summary = None
            if filtering_applied:
                filter_summary = {
                    "filters_applied": filtering_applied,
                    "original_document_count": original_count,
                    "matched_document_count": matched_count,
                    "filtered_document_count": len(documents),
                    "reduction_percentage": round((1 - len(documents)/original_count) * 100, 1) if original_count > 0 else 0
                }

            return {
                "success": True,
                "application_number": app_number,
                "count": len(documents),
                "matched_count": matched_count,
                "documentBag": documents,
                "summary": {
                    "total_documents": len(documents),
                    "document_types": doc_types,
                    "total_download_options": download_options,
                    "pdf_documents_count": len(pdf_docs),
                    "key_documents": [doc for doc in pdf_docs if doc['document_code'] in ['SPEC', 'CLM', 'DRW', 'ABST', 'NOA']],
                    "filtering": filter_summary  # NEW: Filtering summary
                }
            }

        except Exception as e:
            return _handle_client_error("Failed to get documents", e)

    async def lookup_identifier_lane(self, query: str) -> Optional[Dict[str, Any]]:
        """One minimal search used ONLY to decide which identifier lane an
        ambiguous number belongs to (util/identifier_resolution.py).

        Returns the first matching patentFileWrapperDataBag entry, or None when
        the lane matched nothing. A lane miss is not an error.
        """
        body = {
            "q": query,
            "pagination": {"limit": 1, "offset": 0},
            "fields": [
                "applicationNumberText",
                "applicationMetaData.patentNumber",
                "applicationMetaData.inventionTitle",
                "applicationMetaData.grantDate",
                "applicationMetaData.filingDate",
                "applicationMetaData.effectiveFilingDate",
            ],
        }
        result = await self._make_request("search", method="POST", json=body)
        if result.get("error"):
            return None
        applications = result.get("patentFileWrapperDataBag") or []
        return applications[0] if applications else None

    async def find_application_for_patent(self, patent_number: str) -> tuple[str, dict]:
        """
        Find the application number that led to a granted patent using direct API calls.

        Args:
            patent_number: Patent number (e.g., '7971071')

        Returns:
            Tuple of (application_number, associated_documents)
        """
        try:
            # Use direct API search to avoid circular imports
            queries = [
                f"applicationMetaData.patentNumber:{patent_number}",
                f"parentPatentNumber:{patent_number}",
                "applicationMetaData.applicationStatusCode:Patent"
            ]

            for i, query in enumerate(queries):
                limit = 10 if i < 2 else 100  # Use higher limit for broader search

                # Direct API call using the same pattern as search_applications
                body = {
                    "q": query,
                    "pagination": {
                        "limit": limit,
                        "offset": 0
                    },
                    "fields": [
                        "applicationNumberText",
                        "applicationMetaData.patentNumber",
                        "parentPatentNumber",
                        "parentContinuityBag",
                        "associatedDocuments"  # Try to get this directly
                    ]
                }

                result = await self._make_request("search", method="POST", json=body)

                if result.get('error'):
                    continue

                applications = result.get('patentFileWrapperDataBag', [])

                if i < 2:  # Direct searches
                    if applications:
                        app = applications[0]
                        return app["applicationNumberText"], app.get("associatedDocuments")
                else:  # Broader search - need to scan
                    for app in applications:
                        app_meta = app.get("applicationMetaData", {})
                        if (app_meta.get("patentNumber") == patent_number or
                            any(parent.get("parentPatentNumber") == patent_number
                                for parent in app.get("parentContinuityBag", []))):
                            return app["applicationNumberText"], app.get("associatedDocuments")

            raise ValueError(f"No application found for patent {patent_number}")

        except Exception as e:
            raise ValueError(f"Failed to find application for patent {patent_number}: {str(e)}")

    def detect_content_type(self, identifier: str) -> str:
        """
        Auto-detect patent vs application based on identifier format.

        Uses the comprehensive identifier normalization logic that handles:
        - Patent kind codes (B2, A1, etc.)
        - 8M threshold for ambiguous 8-digit numbers
        - Publication numbers

        Rules:
        - Patent numbers: Usually 7 digits (e.g., 7971071) or with suffixes (US7971071B2)
        - Application numbers: Usually 8+ digits >= 8M (e.g., 11752072, 16/123456)
        """
        from ..util.identifier_normalization import normalize_identifier

        # Use the comprehensive identifier normalization
        identifier_info = normalize_identifier(identifier)

        # Map identifier types to content types
        if identifier_info.identifier_type == "patent":
            return "patent"
        elif identifier_info.identifier_type in ["application", "publication"]:
            return "application"
        else:
            # Unknown type - use old simple heuristic as fallback
            clean_id = identifier.replace("/", "").replace("-", "").replace(",", "")
            if len(clean_id) <= 7 and clean_id.isdigit():
                return "patent"
            else:
                return "application"

    def extract_xml_url(self, associated_docs: dict, target_xml: str) -> str:
        """
        Extract the correct XML URL from Associated Documents.

        Args:
            associated_docs: Associated documents data from API
            target_xml: "PTGRXML" for granted patents, "APPXML" for applications
        """
        if not associated_docs or not associated_docs.get("documents"):
            raise AuthoredClientError("No associated documents available")

        documents = associated_docs["documents"]
        if not documents:
            raise AuthoredClientError("No documents found in associated documents")

        doc = documents[0]  # Usually only one document entry

        if target_xml == "PTGRXML":
            if "grantDocumentMetaData" in doc and associated_docs.get("ptgrXmlAvailable"):
                return doc["grantDocumentMetaData"]["fileLocationURI"]
            else:
                raise AuthoredClientError(PTGRXML_NOT_SERVED_MESSAGE)

        elif target_xml == "APPXML":
            if "pgpubDocumentMetaData" in doc and associated_docs.get("appXmlAvailable"):
                return doc["pgpubDocumentMetaData"]["fileLocationURI"]
            else:
                raise AuthoredClientError("No application XML available")

        raise ValueError(f"Unknown XML type: {target_xml}")

    async def _download_once(self, url: str) -> "httpx.Response":
        """Perform exactly one direct USPTO download GET (XML or PDF),
        gated by the shared cross-process rate limiter (token + concurrency
        slot) — off unless USPTO_SHARED_RATE_LIMIT_DIR is set. Single choke
        point for the two download paths that don't route through
        USPTOTransport (fetch_xml_from_url and the OCR-extraction PDF
        fetch); both are api.uspto.gov fetches under the same ODP key."""
        async with httpx.AsyncClient(
            timeout=self.download_timeout,
            limits=self.download_limits,
            follow_redirects=True,
            # Drop X-API-KEY on any hop that is not https on uspto.gov: these
            # URLs 302 to signed storage URLs, and httpx strips only
            # Authorization and Cookie across origins, so the shared ODP key
            # was reaching the redirect target verbatim.
            event_hooks=USPTO_KEY_EVENT_HOOKS,
        ) as client:
            send = client.get(url, headers=self.headers)
            limiter = get_shared_limiter()
            if limiter is not None:
                async with limiter:
                    return await send
            return await send

    async def fetch_xml_from_url(self, xml_url: str) -> str:
        """
        Fetch XML content from the provided URL.

        Args:
            xml_url: URL to fetch XML from

        Returns:
            Raw XML content as string
        """
        try:
            response = await self._download_once(xml_url)
            response.raise_for_status()
            return response.text
        except Exception as e:
            raise ValueError(f"Failed to fetch XML from URL {xml_url}: {str(e)}")

    # XML parsing lives in api/xml_parsing.py (audit F3); these delegators
    # preserve the public client surface.
    def parse_xml_for_llm(self, xml_content: str, include_fields: Optional[List[str]] = None) -> dict:
        """Parse USPTO XML into LLM-friendly structured format (see
        api/xml_parsing.py for field options)."""
        from .xml_parsing import parse_xml_for_llm
        return parse_xml_for_llm(xml_content, include_fields)

    def _build_fields_metadata(self, include_fields, structured_content) -> dict:
        from .xml_parsing import build_fields_metadata
        return build_fields_metadata(include_fields, structured_content)


    async def get_patent_or_application_xml(
        self,
        identifier: str,
        content_type: str = "auto",
        include_fields: Optional[List[str]] = None,
        include_raw_xml: bool = True
    ) -> Dict[str, Any]:
        """
        Get XML content with intelligent patent-to-application mapping.

        Args:
            identifier: Patent number (7971071) or application number (11752072)
            content_type: "patent", "application", "auto" (default: auto-detect)
            include_fields: Optional list of fields to include (default: ["abstract", "claims", "description"])
            include_raw_xml: Include raw XML in response. The CLIENT default stays
                True; the TOOL (PFW_get_patent_or_application_xml) defaults it to
                False as of 2026-08-21 — the ~50K-token blob is almost never read.

        Returns:
            Clean, structured XML content with full text, claims, and metadata
        """
        resolution = None
        try:
            # Step 1: Decide which lane the identifier belongs to. An 8-digit
            # bare number is BOTH a valid patent number and a valid application
            # serial, so the API decides, not arithmetic (OPEN_ITEMS #9).
            from ..util.identifier_resolution import resolve_identifier_lanes

            resolution = await resolve_identifier_lanes(
                self, identifier, content_type, verify_application_lane=True
            )
            if not resolution.application_number:
                return {
                    **format_error_response(
                        f"Could not resolve identifier '{identifier}' to a USPTO application. "
                        + (resolution.note or "")
                    ),
                    **resolution.response_fields(),
                }

            app_number = resolution.application_number
            # A resolved patent number wants the GRANT XML; anything else wants
            # the pre-grant publication XML.
            target_xml = "PTGRXML" if resolution.resolved_as == "patent" else "APPXML"

            # Step 2: Associated documents for that application
            assoc_docs = None
            assoc_docs_result = await self.get_associated_documents(app_number)
            if assoc_docs_result.get("success"):
                documents = assoc_docs_result.get("associated_documents", [])
                assoc_docs = {
                    "documents": documents,
                    "ptgrXmlAvailable": any("grantDocumentMetaData" in doc for doc in documents),
                    "appXmlAvailable": any("pgpubDocumentMetaData" in doc for doc in documents),
                }

            # Step 3: Extract appropriate XML URL
            xml_url = self.extract_xml_url(assoc_docs, target_xml)

            # Step 4: Fetch and parse XML
            xml_content = await self.fetch_xml_from_url(xml_url)
            structured = self.parse_xml_for_llm(xml_content, include_fields)

            # Build fields metadata
            fields_metadata = self._build_fields_metadata(include_fields, structured)

            # Build response (conditionally include raw_xml)
            response = {
                "success": True,
                "identifier_used": identifier,
                **resolution.response_fields(),
                "application_number": app_number,
                "patent_number_resolved": resolution.patent_number,
                "xml_type": target_xml,
                "xml_source": xml_url,
                "structured_content": structured,
                "fields_metadata": fields_metadata,
                "data_limitation": "XML content only available for patents/applications filed after January 1, 2001"
            }

            # Only include raw_xml if requested (the tool layer defaults it off)
            if include_raw_xml:
                response["raw_xml"] = xml_content

            return response

        except AuthoredClientError as e:
            # Server-authored, sensitive-free, and the whole point is that the
            # caller reads it: 404 (not 500, which agents retry) with the text.
            logger.info(f"XML not available: {e}")
            error = format_error_response(
                str(e), status_code=404, error_type="xml_not_available",
            )
            if resolution is not None:
                error.update(resolution.response_fields())
            return error
        except Exception as e:
            error = _handle_client_error("Failed to get XML content", e)
            # Keep the lane report on the failure path too — "which identifier
            # did you actually look up" is exactly the question a failed XML
            # fetch raises (OPEN_ITEMS #9).
            if resolution is not None:
                error.update(resolution.response_fields())
            return error

    def is_good_extraction(self, text: str) -> bool:
        """
        Determine if PyPDF2 extraction is usable.

        Criteria for "good" extraction:
        - Not empty or whitespace-only
        - Contains reasonable amount of text (>50 chars)
        - Contains readable words (not just symbols/garbage)
        - Has reasonable word-to-character ratio

        Public name kept; the thresholds and the reason live in
        ``extraction_reject_reason`` (audit R-5).
        """
        return extraction_reject_reason(text) is None

    async def extract_with_pypdf2(
        self, pdf_content: bytes, status: Optional[Dict[str, Any]] = None,
        page_offset: int = 0,
    ) -> str:
        """Extract text using PyPDF2, capped at PYPDF_MAX_PAGES.

        Two things changed here (both were silent before):

        1. The loop walked EVERY page of the document. A 900-page file wrapper
           produced a multi-megabyte string that the client then replaced with
           an unrecoverable truncation error.
        2. Pages were concatenated with a bare newline, so there was no way to
           serve page-unit windows. Every page now carries an
           ``=== PAGE N ===`` header in exactly the format the Mistral OCR tier
           emits (services/ocr_service.py), which is what
           shared/response_bounds.py's ``PAGE_MARKER_PATTERN`` recognizes.

        ``status`` (when given) collects the honest bookkeeping the caller
        surfaces: ``page_count`` (the reader's real count — never a guess),
        ``pages_extracted``, and, when the cap fired, ``pages_truncated`` plus
        a ``truncation_note``.
        """
        if not PDF_AVAILABLE:
            raise ValueError("PyPDF2 not available")

        import PyPDF2
        import io

        status = status if status is not None else {}
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(pdf_content))
        total_pages = len(pdf_reader.pages)
        cap = pypdf_max_pages()
        truncated = total_pages > cap
        pages_to_extract = pdf_reader.pages[:cap] if truncated else pdf_reader.pages

        text_parts: List[str] = []
        pages_with_text = 0
        for index, page in enumerate(pages_to_extract, start=1 + page_offset):
            page_text = page.extract_text() or ""
            if page_text.strip():
                pages_with_text += 1
                text_parts.append(f"=== PAGE {index} ===\n{page_text}")
            else:
                # Keep the header so page offsets stay aligned with the document.
                text_parts.append(f"=== PAGE {index} ===\n{PYPDF_EMPTY_PAGE_PLACEHOLDER}")

        status["page_count"] = total_pages
        status["page_count_source"] = "pypdf"
        status["page_offset"] = page_offset
        status["pages_extracted"] = len(text_parts)
        status["pages_with_text"] = pages_with_text
        if truncated:
            status["pages_truncated"] = total_pages - cap
            status["truncation_note"] = (
                f"Document has {total_pages} pages; the free PyPDF2 tier extracted "
                f"the first {cap} (PYPDF_MAX_PAGES limit). The text is incomplete."
            )

        return "\n\n".join(text_parts).strip()

    async def extract_with_docling(self, pdf_content: bytes, document_identifier: str) -> str:
        """Extract text via docling-serve REST API (true OCR, handles scanned PDFs).

        Uses the DOCLING_SERVE_URL environment variable to locate the server.
        Supports both local Docker (http://localhost:5001) and remote instances.
        """
        client = self.docling_client
        return await client.extract(pdf_content, filename=f"{document_identifier}.pdf")

    async def _resolve_document_for_extraction(
        self, app_number: str, document_identifier: str, request_id: str
    ):
        """Locate the documentBag entry and its PDF option.

        Returns ``(target_doc, pdf_option)`` — ``pdf_option`` is the IFW render
        when there is one, else an as-uploaded PDF, else None (some APP.TEXT
        filings carry only a .docx) — or an error dict shaped like a tool
        response. Raises NotFoundError for an unknown document identifier.
        """
        docs_result = await self.get_documents(app_number)
        if docs_result.get('error'):
            return docs_result

        target_doc = None
        for doc in docs_result.get('documentBag', []):
            if doc.get('documentIdentifier') == document_identifier:
                target_doc = doc
                break
        if not target_doc:
            raise NotFoundError(
                f"Document with identifier '{document_identifier}' not found in application {app_number}",
                request_id=request_id
            )

        buckets = classify_download_options(target_doc.get('downloadOptionBag', []))
        pdf_options = buckets["render_pdf"] or buckets["uploaded_pdf"]
        return target_doc, (pdf_options[0] if pdf_options else None)

    @staticmethod
    def _check_download_size(response) -> None:
        """Refuse a document too large to hold in memory three times over.

        `response.content` buffers the whole PDF, `slice_pdf_pages` holds a
        second copy and a multipart OCR body a third, and nothing looked at
        Content-Length (audits M-19, resilience F-9). A 500-page file wrapper
        is a real object. The download PROXY streams correctly, so this is
        only the extraction path.

        Raises:
            ValidationError: with the page-window advice the caller can act on.
        """
        # getattr, not response.headers: the check must never be the reason a
        # download fails. A response object without usable headers (test
        # doubles, some transports) simply goes unchecked rather than being
        # reported as a download failure.
        headers = getattr(response, "headers", None) or {}
        try:
            declared = int(headers.get("content-length", 0))
        except (AttributeError, TypeError, ValueError):
            declared = 0
        if declared > max_document_bytes():
            raise ValidationError(
                f"Document is {declared} bytes, over the "
                f"{max_document_bytes()}-byte extraction cap. Request a page "
                f"window with page_from/page_to, or raise PFW_MAX_DOCUMENT_BYTES."
            )

    async def _download_pdf_for_extraction(
        self, base: Dict[str, Any], pdf_option: Optional[Dict[str, Any]], progress_cb=None
    ) -> Any:
        """Download the PDF the PyPDF2 / OCR tiers work on. Returns the bytes,
        or an error dict shaped like a tool response (``base`` supplies the
        document identity fields and any ``free_text_variants`` record)."""
        if not pdf_option:
            return format_error_response("PDF not available for this document")

        page_count = pdf_option.get('pageTotalQuantity', 0)
        if progress_cb:
            await progress_cb(10, 100, f"Downloading PDF ({page_count} pages)...")

        # A download failure blocks every extraction tier — label it as such
        # (audit F49: previously reported as extraction_method "failed")
        try:
            response = await self._download_once(pdf_option.get('downloadUrl'))
            response.raise_for_status()
            self._check_download_size(response)
            return response.content
        except Exception as e:
            return {
                **base,
                "success": False,
                "error": f"Failed to download PDF from USPTO: {e}",
                "extracted_content": "",
                "extraction_method": "download_failed",
            }

    # --- Tier 0: free-text variants (2026-08-25 follow-up) -------------------
    # Tried BEFORE the IFW PDF render is downloaded, in preference order
    # .docx -> xmlarchive -> as-uploaded PDF text layer. Each runner returns a
    # result-update dict or raises; VariantMismatchError / VariantEmptyError
    # are expected outcomes and fall through to the next variant, then to the
    # PDF tiers. See api/free_text_variants.py for the formats and the
    # application-number check.

    async def _fetch_variant_bytes(self, option: Dict[str, Any]) -> bytes:
        response = await self._download_once(option.get('downloadUrl'))
        response.raise_for_status()
        self._check_download_size(response)
        return response.content

    @staticmethod
    def _variant_update(parsed: Dict[str, Any], size: int) -> Dict[str, Any]:
        method = parsed["extraction_method"]
        return {
            "extracted_content": parsed["text"],
            "extraction_method": method,
            "auto_optimization": f"{method} served by the USPTO API - PDF render not downloaded, no OCR spent",
            "file_size_bytes": size,
            "application_number_verified": parsed["application_number_verified"],
        }

    async def _try_docx_variant(self, option: Dict[str, Any], app_number: str, document_identifier: str):
        data = await self._fetch_variant_bytes(option)
        return self._variant_update(extract_docx(data, app_number), len(data))

    async def _try_xmlarchive_variant(self, option: Dict[str, Any], app_number: str, document_identifier: str):
        data = await self._fetch_variant_bytes(option)
        return self._variant_update(extract_xmlarchive(data, app_number), len(data))

    async def _try_uploaded_pdf_variant(self, option: Dict[str, Any], app_number: str, document_identifier: str):
        data = await self._fetch_variant_bytes(option)
        update = await self._try_pypdf2_tier(data, document_identifier, extraction_method=METHOD_UPLOADED_PDF)
        if update is None:
            raise VariantEmptyError("as-uploaded PDF has no usable text layer")
        update["file_size_bytes"] = len(data)
        # A plain PDF carries no application-number field to check; the option
        # came from this document's own downloadOptionBag and nothing more.
        update["application_number_verified"] = False
        return update

    async def _try_free_variant_tiers(
        self, app_number: str, target_doc: Dict[str, Any], document_identifier: str,
        attempts: List[Dict[str, Any]], progress_cb=None
    ):
        """Tier 0 (auto-optimize only): the free-text variants in preference
        order. Appends one record per variant tried to ``attempts`` (surfaced
        as ``free_text_variants``) and returns the first usable result-update
        dict, or None to fall through to the PDF render tiers."""
        buckets = classify_download_options(target_doc.get('downloadOptionBag', []))
        plan = (
            ("docx", buckets["docx"], self._try_docx_variant),
            ("xmlarchive", buckets["xmlarchive"], self._try_xmlarchive_variant),
            ("as-uploaded pdf", buckets["uploaded_pdf"], self._try_uploaded_pdf_variant),
        )
        for label, options, runner in plan:
            for option in options:
                if progress_cb:
                    await progress_cb(15, 100, f"Trying free {label} variant...")
                try:
                    update = await runner(option, app_number, document_identifier)
                except VariantMismatchError as e:
                    logger.warning(f"{label} variant rejected for {document_identifier}: {e}")
                    attempts.append({"variant": label, "outcome": "rejected", "reason": str(e)})
                except VariantEmptyError as e:
                    attempts.append({"variant": label, "outcome": "no text", "reason": str(e)})
                except Exception as e:
                    logger.warning(f"{label} variant failed for {document_identifier}: {type(e).__name__}")
                    attempts.append({"variant": label, "outcome": "failed", "reason": f"{type(e).__name__}: {e}"})
                else:
                    attempts.append({"variant": label, "outcome": "used"})
                    return update
        return None

    async def _free_variant_result(
        self, app_number: str, target_doc: Dict[str, Any], document_identifier: str,
        pdf_option: Optional[Dict[str, Any]], extraction_result: Dict[str, Any], progress_cb=None
    ):
        """Tier 0 wrapper: runs the variants, records ``free_text_variants`` on
        ``extraction_result`` when any were tried, and returns the completed
        result-update (page metadata from the documentBag, since no PDF was
        read) or None."""
        attempts: List[Dict[str, Any]] = []
        update = await self._try_free_variant_tiers(
            app_number, target_doc, document_identifier, attempts, progress_cb
        )
        if attempts:
            extraction_result["free_text_variants"] = attempts
        if update is None:
            return None
        page_count, page_count_source = _resolve_page_count(pdf_option or {}, b"")
        return {"page_count": page_count, "page_count_source": page_count_source, **update}

    async def _try_pypdf2_tier(
        self, pdf_content: bytes, document_identifier: str, progress_cb=None,
        extraction_method: str = "PyPDF2", page_offset: int = 0,
    ):
        """Tier 1 (auto-optimize only): free PyPDF2 text extraction of the IFW
        render — or, with ``extraction_method=METHOD_UPLOADED_PDF``, of an
        as-uploaded PDF variant's native text layer.
        Returns a result-update dict, or None to fall through."""
        if progress_cb:
            await progress_cb(25, 100, "Trying text extraction (PyPDF2)...")
        try:
            if not PDF_AVAILABLE:
                logger.warning("PyPDF2 not available - falling back to Mistral OCR")
                return None
            status: Dict[str, Any] = {}
            pypdf2_text = await self.extract_with_pypdf2(pdf_content, status, page_offset)
            if status.get("pages_with_text") == 0:
                # Every page came back empty: a rasterized render. This used
                # to pass is_good_extraction on the placeholders alone.
                logger.info(f"PyPDF2 recovered no text from any page of {document_identifier} - falling back")
                return None
            reject_reason = extraction_reject_reason(_pypdf_body_text(pypdf2_text))
            if reject_reason:
                # Name the failing check: this escalation is what costs money.
                logger.info(
                    f"PyPDF2 extraction poor for {document_identifier} "
                    f"({reject_reason}) - falling back to Mistral OCR"
                )
                return None
            update = {
                "extracted_content": pypdf2_text,
                "extraction_method": extraction_method,
                "auto_optimization": f"{extraction_method} successful - no OCR needed",
                # The reader's own count is authoritative — it beats whatever
                # pageTotalQuantity the documentBag claimed.
                "page_count": status.get("page_count"),
                "page_count_source": status.get("page_count_source", "pypdf"),
                "pages_extracted": status.get("pages_extracted"),
            }
            if status.get("pages_truncated"):
                update.update(_page_cap_markers(
                    pages_truncated=status["pages_truncated"],
                    pages_returned=status.get("pages_extracted"),
                    pages_total=status.get("page_count"),
                    note=status["truncation_note"],
                ))
            return update
        except Exception as e:
            logger.warning(f"PyPDF2 extraction failed for {document_identifier}: {e} - falling back to Mistral OCR")
            return None

    async def _try_mistral_tier(
        self, pdf_content: bytes, page_count: int, app_number: str,
        document_identifier: str, auto_optimize: bool, progress_cb=None,
        page_offset: int = 0,
    ):
        """Tier 2: Mistral OCR via OCRService.

        `page_offset` is forwarded so the `=== PAGE N ===` headers carry the
        TRUE document page. The bytes handed to this tier are the sliced window
        when page_from/page_to were used, and Mistral indexes that slice from
        0 — a page_from=51 window used to emit `=== PAGE 1 ===` while
        `page_window` in the same response said 51-53.

        Returns a result-update dict, or None to fall through."""
        if not self.mistral_api_key:
            return None
        if progress_cb:
            await progress_cb(50, 100, f"Sending to Mistral OCR ({page_count} pages)...")
        mistral_result = await self.ocr_service.extract_document_content(
            pdf_content, page_count, app_number, document_identifier,
            page_offset=page_offset,
        )
        if not mistral_result.get("success"):
            logger.warning(
                f"Mistral OCR failed for {document_identifier}: {mistral_result.get('error')} - falling back to Docling"
            )
            return None
        update = {
            "extracted_content": mistral_result.get("extracted_content", ""),
            "extraction_method": "Mistral OCR" + (" (PyPDF2 fallback)" if auto_optimize else " (direct)"),
            "ocr_model": mistral_result.get("ocr_model", self.mistral_ocr_model),
            "auto_optimization": "Mistral OCR used - scanned document detected" if auto_optimize else "Mistral OCR direct",
        }
        if mistral_result.get("pages_processed"):
            update["pages_extracted"] = mistral_result["pages_processed"]
        # Pass through the page-cap truncation signal (audit F48), now with the
        # shared `_bounds` vocabulary alongside the legacy keys.
        if mistral_result.get("pages_truncated"):
            update.update(_page_cap_markers(
                pages_truncated=mistral_result["pages_truncated"],
                pages_returned=mistral_result.get("pages_processed"),
                pages_total=page_count,
                note=mistral_result.get("truncation_note", ""),
            ))
        return update

    async def _try_docling_tier(
        self, pdf_content: bytes, page_count: int, document_identifier: str,
        docling_client, progress_cb=None
    ):
        """Tier 3 (auto-optimize only): free Docling OCR via docling-serve.

        No `page_offset` parameter: docling-serve returns one flat text
        document with no `=== PAGE N ===` markers at all, so there are no page
        headers on this branch to offset (the PyPDF2 and Mistral branches both
        emit them and both carry the offset). A page window still applies —
        the bytes are sliced before they get here — it just cannot be snapped
        to page boundaries afterwards.

        Returns a result-update dict, or None to fall through."""
        if not docling_client.is_available():
            return None
        if not docling_client.within_page_limit(page_count):
            logger.warning(
                f"Skipping Docling for {document_identifier}: {page_count} pages exceeds "
                f"DOCLING_MAX_PAGES={docling_client.max_pages}. Ask for a page window "
                f"(page_from/page_to) of at most {docling_client.max_pages} pages, or raise "
                "DOCLING_MAX_PAGES on the docling deployment."
            )
            return None
        try:
            if progress_cb:
                await progress_cb(50, 100, f"Sending to Docling OCR ({page_count} pages — this may take a minute)...")
            docling_text = await self.extract_with_docling(pdf_content, document_identifier)
            reject_reason = extraction_reject_reason(docling_text)
            if reject_reason:
                logger.info(
                    f"Docling extraction also poor for {document_identifier} "
                    f"({reject_reason})"
                )
                return None
            return {
                "extracted_content": docling_text,
                "extraction_method": "Docling OCR",
                "auto_optimization": "Docling OCR used - PyPDF2 insufficient, no Mistral key",
            }
        except Exception as e:
            logger.warning(f"Docling extraction failed for {document_identifier}: {e}")
            return None

    async def _run_pdf_tiers(
        self, extraction_result: Dict[str, Any], pdf_option: Optional[Dict[str, Any]], pdf_content: bytes,
        app_number: str, document_identifier: str, auto_optimize: bool, progress_cb=None,
        page_offset: int = 0, window_total_pages: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Tiers 1-3 over the downloaded PDF: PyPDF2 (auto-optimize only)
        -> Mistral OCR -> Docling OCR, then the terminal "all failed"
        envelope. Split out of extract_document_content_hybrid when Tier 0
        (the free-text variants) pushed that method past the complexity cap."""
        # Never fabricate a page count: pageTotalQuantity used to default to
        # 0, which reads as "this document has no pages" rather than "the
        # metadata did not say". Recover it from the PDF itself, else null.
        page_count, page_count_source = _resolve_page_count(pdf_option, pdf_content)
        # The bytes handed to the tiers are a SLICE whenever a page window was
        # requested. Re-resolve the count from those bytes: a first-page window
        # (page_from=1, page_to=3) leaves page_offset at 0, so gating the
        # re-resolution on the offset alone let the Docling cap compare 3
        # extracted pages against the DOCUMENT's 128.
        if page_offset or window_total_pages is not None:
            page_count, page_count_source = _resolve_page_count({}, pdf_content)
            if window_total_pages:
                extraction_result["document_page_count"] = window_total_pages
        # Downstream tiers need an int for their page budgets; when the
        # count is genuinely unknown, fall back to the tier's own cap
        # rather than sending an unbounded request.
        page_budget = page_count if isinstance(page_count, int) else self.ocr_service.ocr_max_pages
        extraction_result.update({
            "page_count": page_count,
            "page_count_source": page_count_source,
            "file_size_bytes": len(pdf_content),
        })

        if auto_optimize:
            update = await self._try_pypdf2_tier(
                pdf_content, document_identifier, progress_cb, page_offset=page_offset
            )
            if update is not None:
                extraction_result.update(update)
                return extraction_result

        update = await self._try_mistral_tier(
            pdf_content, page_budget, app_number, document_identifier, auto_optimize,
            progress_cb, page_offset=page_offset,
        )
        if update is not None:
            extraction_result.update(update)
            return extraction_result

        if not auto_optimize and not self.mistral_api_key:
            # User explicitly requested Mistral but no API key
            extraction_result.update({
                "extracted_content": "",
                "extraction_method": "failed",
                "error": "MISTRAL_API_KEY environment variable is required for OCR content extraction",
                "mistral_api_key_missing": True,
                "suggestion": "Set MISTRAL_API_KEY environment variable: set MISTRAL_API_KEY=your_key_here (Windows) or export MISTRAL_API_KEY=your_key_here (Linux/Mac)",
            })
            return extraction_result

        docling_client = self.docling_client
        if auto_optimize:
            update = await self._try_docling_tier(
                pdf_content, page_budget, document_identifier, docling_client, progress_cb
            )
            if update is not None:
                extraction_result.update(update)
                return extraction_result

        # All methods failed
        extraction_result.update({
            "extracted_content": "",
            "extraction_method": "failed",
            "error": "Document appears to be a scanned image. Could not extract meaningful text.",
            "mistral_api_key_missing": not bool(self.mistral_api_key),
            "docling_not_configured": not docling_client.is_available(),
            "docling_page_limit_exceeded": docling_client.is_available() and not docling_client.within_page_limit(page_budget),
            "suggestion": _extraction_failure_advice(
                bool(self.mistral_api_key), docling_client, page_budget
            ),
            "llm_guidance": {
                "explain_to_user": "Many USPTO Patent File Wrapper documents are scanned images rather than text-based PDFs. "
                                  "PyPDF2 cannot read scanned images. Mistral OCR and Docling handle true scans.",
                "recommended_solution": _extraction_failure_advice(
                    bool(self.mistral_api_key), docling_client, page_budget
                ),
            }
        })
        return extraction_result

    async def extract_document_content_hybrid(
        self,
        app_number: str,
        document_identifier: str,
        auto_optimize: bool = True,
        progress_cb=None,
        page_from: int = 1,
        page_to: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get document content with intelligent extraction method selection.

        Walks a tier waterfall (each tier is its own method — audit: this was
        a single ~200-line function at manual complexity ~18-20):
        - auto_optimize=True (default): free-text variants from the
          downloadOptionBag (.docx -> xmlarchive -> as-uploaded PDF text
          layer; no PDF render download, no OCR) -> PyPDF2 on the IFW render
          -> Mistral OCR -> Docling OCR (self-hosted)
        - auto_optimize=False: Mistral OCR only

        Args:
            app_number: Application number (e.g., '11752072')
            document_identifier: Document ID from documentBag
            auto_optimize: Try the free tiers first, fall back to OCR (default: True)
            page_from: First page to extract, 1-based inclusive (default 1)
            page_to: Last page to extract, 1-based inclusive (default: end of document)

        A page window is applied by SLICING THE PDF before the extraction tiers
        run, so each tier's own page cap (PYPDF_MAX_PAGES, MISTRAL_OCR_MAX_PAGES)
        applies to the window rather than to the whole document — that is what
        makes pages past the cap reachable at all (OPEN_ITEMS #11). The free-text
        variant tier has no page structure, so a window is not applied there and
        `page_window.applied` says so.

        Returns:
            Document content with extraction method metadata
        """
        try:
            app_number = validate_app_number(app_number)
            request_id = generate_request_id()

            resolved = await self._resolve_document_for_extraction(app_number, document_identifier, request_id)
            if isinstance(resolved, dict):  # error response from the document lookup
                return resolved
            target_doc, pdf_option = resolved

            extraction_result = {
                "success": True,
                "application_number": app_number,
                "document_identifier": document_identifier,
                "document_code": target_doc.get("documentCode"),
                "document_description": target_doc.get("documentCodeDescriptionText"),
                "official_date": target_doc.get("officialDate"),
            }

            window_requested = page_from > 1 or page_to is not None

            if auto_optimize:
                update = await self._free_variant_result(
                    app_number, target_doc, document_identifier, pdf_option, extraction_result, progress_cb
                )
                if update is not None:
                    extraction_result.update(update)
                    if window_requested:
                        extraction_result.update(_page_window_markers(
                            None, None, extraction_result.get("page_count"), False,
                            "page_from/page_to were NOT applied: this text came from a free "
                            "USPTO text variant (.docx / xmlarchive / as-uploaded PDF text "
                            "layer), which has no page structure. The whole document text is "
                            "returned; page it with char_offset/max_chars instead.",
                        ))
                    return extraction_result

            pdf_content = await self._download_pdf_for_extraction(extraction_result, pdf_option, progress_cb)
            if isinstance(pdf_content, dict):  # error response from the download
                return pdf_content

            page_offset = 0
            window_markers: Dict[str, Any] = {}
            if window_requested:
                try:
                    sliced, first, last, total = slice_pdf_pages(pdf_content, page_from, page_to)
                except ValueError as ve:
                    return {
                        **extraction_result,
                        "success": False,
                        "error": str(ve),
                        "extracted_content": "",
                        "extraction_method": "page_range_invalid",
                    }
                if first is None:
                    window_markers = _page_window_markers(
                        1, total, total, False,
                        "page_from/page_to cover the whole document, so no slice was made.",
                    )
                else:
                    pdf_content = sliced
                    page_offset = first - 1
                    window_markers = _page_window_markers(
                        first, last, total, True,
                        f"Pages {first}-{last} of {total} were extracted. Each extraction "
                        "tier's page cap applies to this window, so raise page_from to "
                        "reach later pages.",
                    )

            result = await self._run_pdf_tiers(
                extraction_result, pdf_option, pdf_content, app_number, document_identifier,
                auto_optimize, progress_cb, page_offset=page_offset,
                window_total_pages=window_markers.get("page_window", {}).get("page_count_total"),
            )
            result.update(window_markers)
            return result

        except Exception as e:
            return {
                "success": False,
                "application_number": app_number,
                "document_identifier": document_identifier,
                "error": str(e),
                "extracted_content": "",
                "extraction_method": "failed"
            }

    async def get_granted_patent_documents_download(
        self,
        app_number: str,
        include_drawings: bool = True,
        include_original_claims: bool = False,
        direction_category: Optional[str] = "INCOMING"
    ) -> Dict[str, Any]:
        """
        Get complete granted patent package (ABST, DRW, SPEC, CLM) in one call.

        Args:
            app_number: Patent application number
            include_drawings: Include drawings (default: True, set False to skip)
            include_original_claims: Get originally-filed claims vs. granted claims
                                    (default: False = get granted/final claims)
            direction_category: Filter claims by direction (default: INCOMING)
                              Set to None to get all claim versions

        Returns:
            dict: Structured response with all patent components and download metadata

        Raises:
            ValueError: If app_number is invalid
            Exception: If API call fails or no components found
        """

        # Validate app_number
        if not app_number or not isinstance(app_number, str):
            raise ValueError("app_number must be a non-empty string")

        # Get proxy port from environment variables
        # Check PFW_PROXY_PORT first (MCP-specific), then PROXY_PORT (generic)
        proxy_port = int(os.getenv('PFW_PROXY_PORT', os.getenv('PROXY_PORT', 8080)))

        # Components to retrieve
        components_to_fetch = ['ABST', 'SPEC', 'CLM']
        if include_drawings:
            components_to_fetch.insert(1, 'DRW')  # Insert after ABST

        results = {
            "success": False,
            "application_number": app_number,
            "granted_patent_components": {},
            "total_pages": 0,
            "components_found": [],
            "components_missing": [],
            "error_details": []
        }

        # Fetch each component
        for doc_code in components_to_fetch:
            try:
                # Call existing get_documents with filter
                response = await self.get_documents(
                    app_number=app_number,
                    document_code=doc_code,
                    direction_category=direction_category if doc_code != 'CLM' else direction_category,
                    limit=GRANTED_COMPONENT_FETCH_LIMIT
                )

                if response.get("success") and response.get("count", 0) > 0:
                    documents = response.get("documentBag", [])
                    # How many versions the min()/max() selection below actually
                    # saw, vs how many exist. A 12-amendment claims history was
                    # decided from the 5 the fetch happened to return, and the
                    # response said nothing about the other 7.
                    versions_considered = len(documents)
                    versions_available = response.get("matched_count")

                    # For claims, handle original vs granted
                    if doc_code == 'CLM':
                        if include_original_claims:
                            # Get oldest (originally filed) claims
                            selected_doc = min(documents, key=lambda d: d.get("officialDate", ""))
                        else:
                            # Get newest (granted/final) claims
                            selected_doc = max(documents, key=lambda d: d.get("officialDate", ""))
                    else:
                        # ABST/DRW/SPEC can carry several versions too: a
                        # replacement-paragraphs amendment is coded SPEC just
                        # like the original filing, and the API returns newest
                        # first, so documents[0] can be a 2-page delta while
                        # the 21-page original sits behind it (seen live on
                        # 11/752,072). Prefer the complete document: most PDF
                        # pages wins, earliest officialDate breaks ties.
                        selected_doc = _select_complete_version(documents)

                    # Extract key information
                    component_name = doc_code.lower()
                    if doc_code == 'ABST':
                        component_name = 'abstract'
                    elif doc_code == 'DRW':
                        component_name = 'drawings'
                    elif doc_code == 'SPEC':
                        component_name = 'specification'
                    elif doc_code == 'CLM':
                        component_name = 'claims'

                    download_options = selected_doc.get("downloadOptionBag", [])
                    pdf_option = next((opt for opt in download_options if opt.get("mimeTypeIdentifier") == "PDF"), None)

                    component_entry = {
                        "document_identifier": selected_doc.get("documentIdentifier"),
                        "document_code": selected_doc.get("documentCode"),
                        "document_description": selected_doc.get("documentCodeDescriptionText"),
                        "official_date": selected_doc.get("officialDate"),
                        "page_count": pdf_option.get("pageTotalQuantity", 0) if pdf_option else 0,
                        "direct_download_url": pdf_option.get("downloadUrl") if pdf_option else None,
                        "proxy_download_url": f"{os.getenv('PFW_PROXY_BASE_URL', f'http://localhost:{proxy_port}')}/download/{app_number}/{selected_doc.get('documentIdentifier')}",
                        "direction_category": selected_doc.get("directionCategory"),
                        "versions_considered": versions_considered,
                        "versions_available": versions_available,
                        "versions_fetch_limit": GRANTED_COMPONENT_FETCH_LIMIT,
                    }
                    if doc_code != 'CLM' and versions_considered > 1:
                        component_entry["version_selection_note"] = (
                            f"{versions_considered} '{doc_code}' documents exist; chose the "
                            f"most complete ({component_entry['page_count']} pages, "
                            f"{component_entry['official_date']}) since amendment papers share "
                            "this document code. Use PFW_get_application_documents("
                            f"app_number=..., document_code='{doc_code}') for the full history."
                        )
                    if (
                        isinstance(versions_available, int)
                        and versions_available > versions_considered
                    ):
                        component_entry["selection_note"] = (
                            f"This application has {versions_available} '{doc_code}' documents; "
                            f"only the first {versions_considered} were fetched "
                            f"(versions_fetch_limit={GRANTED_COMPONENT_FETCH_LIMIT}) and the "
                            "earliest/latest was chosen from those. Use "
                            f"PFW_get_application_documents(app_number=..., document_code='{doc_code}') "
                            "to see the full version history."
                        )
                    results["granted_patent_components"][component_name] = component_entry

                    results["total_pages"] += component_entry["page_count"]
                    results["components_found"].append(component_name)
                else:
                    results["components_missing"].append(doc_code)

            except Exception as e:
                results["error_details"].append({
                    "component": doc_code,
                    "error": str(e)
                })
                results["components_missing"].append(doc_code)

        # Determine success
        results["success"] = len(results["components_found"]) >= 3  # At least 3 of 4 components

        # Add guidance for LLM response formatting
        results["llm_response_guidance"] = {
            "critical_requirement": "ALWAYS format each component as a clickable markdown link AND raw URL",
            "required_format": "**📁 [Download {ComponentName} ({PageCount} pages)]({proxy_download_url})** | Raw URL: `{proxy_download_url}`",
            "example": "**📁 [Download Abstract (1 page)]({proxy_download_url})** | Raw URL: `{proxy_download_url}`",
            "presentation_order": ["abstract", "drawings", "specification", "claims"],
            "include_total": "Show total page count at end: 'Total: 59 pages'",
            "explanation": "Clickable link works in Claude Desktop, raw URL enables copy/paste in Msty and other clients where links aren't clickable"
        }

        return results
