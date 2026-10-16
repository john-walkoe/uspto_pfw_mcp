"""Office Action tools: rejections + full text (audit F2 split from main.py).

SOURCE (ported 2026-10-11)
--------------------------
Both tools read the ODP Office Action API (api/office_action_client.py):
POST /api/v1/patent/office-action/search for an application's office-action
records (metadata, `rejectionTypeBag`, a 500-character snippet) and
GET /api/v1/patent/office-action/{officeActionRecordIdentifier}/download/officeActionText
for the full text. The full text is fetched only for the office actions a tool
is about to return, never for the whole list.

They used to read two separate datasets, the Office Action Rejections API
(/api/v1/patent/oa/oa_rejections/v2/records) and the Office Action Text
Retrieval API (/api/v1/patent/oa/oa_actions/v1/records). USPTO answers both
with an HTML 404 since about 2026-10-10. Their two coverage floors ("Oct 1,
2017" and "roughly 2008") are gone with them.

COVERAGE (probe-verified 2026-10-11 against the new index, facets and sorts)
---------------------------------------------------------------------------
* 19,939,490 records; submissionDate (the mailing date) from 2007-07-27 to
  2026-10-09 on the day probed. An office action mailed before 2007-07-27 is
  not in the index.
* filingDate: 156 records belong to applications filed before 2001; the rest
  were filed 2001 or later (some records carry the placeholder 0001-01-01).
* documentCode: CTNF 8,935,306, NOA 4,759,100, CTFR 4,410,566, CTRS 1,277,856,
  plus petition decisions and other office-issued papers. NOA records exist and
  their full text downloads (a 2026-10-09 NOA, 5,020 characters).
* rejectionTypeBag is carried essentially only by CTNF and CTFR records; its
  values are 103, 102, 112, Other, 101 and DoublePatent.

A num_found=0 is a normal empty result, which is why neither tool errors on it.
"""

import asyncio
import re
from typing import Any, Dict, List, Optional, Tuple


from ..api.helpers import format_error_response
from ..api.office_action_client import (
    DOUBLE_PATENTING,
    STATUTORY_SECTIONS,
    extract_section_text,
    normalize_rejection_types,
)
from ..client_registry import _client, get_api_client
from ..exceptions import UpstreamRateLimitedError
from ..shared.injection_scan import RETRIEVED_TEXT_NOTE, scan_hits
from ..shared.response_bounds import (
    BOUNDS_KEY,
    REASON_WINDOW,
    STAGE_TRUNCATED,
    WINDOW_KEY,
    apply_text_window,
    content_char_budget,
    measure_chars,
    window_text,
)
from ..shared.safe_logger import get_safe_logger
from ..util.citation_links import (
    DOCUMENT_CITATION_NOTE,
    attach_document_cite_as,
    citation_block,
)
from ..util.error_handlers import mcp_error_handler
from ..util.identifier_resolution import resolve_or_error

logger = get_safe_logger(__name__)

#: Document codes PFW_get_oa_text serves, with the index-wide record count each
#: carried when probed.
#:
#: PROBE-VERIFIED 2026-10-11 against
#: POST https://api.uspto.gov/api/v1/patent/office-action/search with
#: facets=['documentCode'] over the whole index. `action_type` is validated
#: against this set because a code outside it would return an empty result
#: indistinguishable from "this application has no such action" (OPEN_ITEMS #8).
#: The index carries other codes too (petition decisions, APEA, PPH decisions);
#: they are not office actions this tool reads, and the call without
#: action_type is restricted to this set so "the most recent office action"
#: never turns out to be a petition decision.
OA_TEXT_ACTION_TYPES = {
    "CTNF": "Non-final rejection (8,935,306 records)",
    "NOA": "Notice of allowance (4,759,100 records)",
    "CTFR": "Final rejection (4,410,566 records)",
    "CTRS": "Restriction / election requirement (1,277,856 records)",
    "CTEQ": "Ex parte Quayle action (111,184 records)",
    "CTAV": "Advisory action (47,997 records)",
    "NRES": "Notice of non-responsive amendment (11,647 records)",
    "CTMS": "Miscellaneous examiner action (6,569 records)",
    "EXIN": "Examiner interview summary (1,734 records)",
    "ABN": "Notice of abandonment (461 records)",
}

#: The office actions PFW_get_oa_rejections triages: the two codes that carry
#: rejectionTypeBag (probed 2026-10-11: rejectionTypeBag:* matched CTNF
#: 8,902,486 and CTFR 4,393,028 records, every other code 30 or fewer).
REJECTION_ACTION_TYPES = ("CTNF", "CTFR")

#: `rows` bounds for PFW_get_oa_rejections (the search page size).
MIN_OA_ROWS = 1
MAX_OA_ROWS = 100

#: Rows the OA-text search requests. OA_TEXT_ROWS_LATEST is how many office
#: actions `latest_only=True` RETURNS. The search asks for submissionDate desc,
#: and the rows are sorted NEWEST FIRST here as well before slicing, so the
#: result never depends on the upstream order (measured 2026-09-03 on the
#: retired text dataset, which answered ascending and handed back the OLDEST
#: CTFR of application 16/319,040 as "the most recent").
OA_TEXT_ROWS_LATEST = 1

#: Full-text downloads per call, newest first, for BOTH tools (audit 2026-10-12
#: M1). PFW_get_oa_rejections used to download one text per returned row, up
#: to 100, so one call could spend about 103 requests of the per-key ODP
#: budget every caller of the deployment shares. Rows past the cap carry the
#: rejectionTypeBag only (`text_available: false`) and the envelope's
#: `text_fetch_cap` block names the cap.
OA_TEXT_FETCH_CAP = 10
OA_TEXT_ROWS_ALL = OA_TEXT_FETCH_CAP

#: How many full-text downloads run at once (USPTO's guidance is a small
#: burst; the shared cross-process limiter, when configured, still applies).
_TEXT_FETCH_CONCURRENCY = 2

#: Overall deadline, in seconds, on one call's full-text downloads. Each
#: download has its own 60 s timeout and retries (api/oa_base.py); without a
#: ceiling over the batch a degraded upstream held one call for minutes. Rows
#: whose text had not arrived by the deadline carry the bag only and say so.
#: Kept under the ~100 s a proxied request survives at the edge.
OA_TEXT_FETCH_DEADLINE_S = 75.0

_DEADLINE_ERROR = (
    "text download not finished within the call's {seconds:g} s deadline; the row carries the "
    "rejectionTypeBag only"
)

#: Value of the `order` field on every PFW_get_oa_text response.
OA_TEXT_ORDER = "submission_date_desc"

OA_TEXT_ORDER_NOTE = (
    "Office actions are ordered NEWEST FIRST by submission_date (the mailing "
    "date). latest_only=True returns the action with the LATEST "
    "submission_date among the matches, and with latest_only=False "
    "office_actions[0] is the most recent."
)

#: The coverage sentence both tools put in their responses.
OA_COVERAGE_NOTE = (
    "Source: the USPTO ODP Office Action API (office-action search plus the "
    "officeActionText download). Probed 2026-10-11: office actions mailed from "
    "2007-07-27 onward, almost all for applications filed 2001 or later; the "
    "index is refreshed by USPTO and its newest mailing date was 2026-10-09 on "
    "that day."
)

#: Floor for the per-document slice when several office actions share one
#: content budget — below this a "window" is not worth returning.
_MIN_PER_DOCUMENT_CHARS = 2_000

#: Headroom left for the `_bounds` marker the fitting loop may still attach.
_BOUNDS_RESERVE_CHARS = 700

_OA_TEXT_BOUNDS_NOTE = (
    "Several office actions shared one content budget, so each was given a "
    "per-document window (`per_document_char_budget`) and the longer ones were "
    "cut. Nothing was discarded: each entry keeps `text_total_chars` next to "
    "`text_returned_chars` and carries its own `_window.next_offset`. Re-call "
    "PFW_get_oa_text(application_number='{application_number}', "
    "char_offset=<_window.next_offset>) to continue, narrow with "
    "action_type= or section='101'|'102'|'103'|'112', or set latest_only=True "
    "to give the whole budget to the most recent action."
)

_OA_TEXT_WINDOW_NOTE = (
    "Only part of this office action's text is shown. Re-call "
    "PFW_get_oa_text(application_number='{application_number}', "
    "char_offset=<_window.next_offset>) to continue from where this window "
    "ended; raise max_chars to widen it, or use section='101'|'102'|'103'|'112' "
    "to target one rejection."
)


# Lazy-initialized Office Action API client
_office_action_client = None


def _oa_failure(exc: Exception, application_number: str) -> Dict[str, Any]:
    """The OA tools' failure envelope. A USPTO 429 (UpstreamRateLimitedError,
    api/oa_base.py) comes back as the transport's rate-limit envelope rather
    than a generic failure, so the caller sees rate_limited/retry_after_seconds
    whichever ODP client met it."""
    if isinstance(exc, UpstreamRateLimitedError):
        return {**exc.envelope, "application_number": application_number}
    return {"success": False, "error": str(exc), "application_number": application_number}


def _get_office_action_client():
    global _office_action_client
    if _office_action_client is None:
        from ..api.office_action_client import OfficeActionClient
        # Reuse API key from already-initialized main client (handles secure storage + env var)
        try:
            api_key = get_api_client().api_key
        except Exception:
            api_key = None
        _office_action_client = OfficeActionClient(api_key=api_key)
    return _office_action_client


def _first_value(value: Any) -> Any:
    """A scalar from a value that may arrive as a single-element list."""
    if isinstance(value, list):
        return value[0] if value else ""
    return "" if value is None else value


def _submission_date(doc: Dict[str, Any]) -> str:
    """The row's submission date as a sortable ISO string ('' when absent)."""
    return str(_first_value(doc.get("submissionDate", "")) or "")


def _doc_code(doc: Dict[str, Any]) -> str:
    return str(_first_value(doc.get("documentCode", "")) or "")


def sort_docs_newest_first(docs: list) -> list:
    """Order office-action records NEWEST FIRST by submission date.

    Submission dates are ISO (YYYY-MM-DD), so a string sort IS a date sort. A
    row with no date sorts last rather than displacing a dated one, and rows
    sharing a date keep the API's own order (`sorted` is stable).
    """
    return sorted(
        docs,
        key=lambda doc: (bool(_submission_date(doc)), _submission_date(doc)),
        reverse=True,
    )


def select_office_action_rows(docs: list, latest_only: bool):
    """(rows_to_return, rows_considered), newest first and then sliced."""
    ordered = sort_docs_newest_first(docs)
    if latest_only:
        return ordered[:OA_TEXT_ROWS_LATEST], len(ordered)
    return ordered, len(ordered)


async def _fetch_one(client, doc: Dict[str, Any], gate: asyncio.Semaphore,
                     tolerate_errors: bool) -> Tuple[Optional[str], Optional[str]]:
    """One office action's full text under the concurrency gate (see _fetch_texts)."""
    record_id = doc.get("officeActionRecordIdentifier")
    if not record_id:
        return None, "no officeActionRecordIdentifier on this record"
    async with gate:
        try:
            return await client.get_office_action_text(record_id), None
        except UpstreamRateLimitedError:
            raise
        except Exception as e:
            if not tolerate_errors:
                raise
            logger.info(f"Office action text unavailable ({type(e).__name__})")
            return None, f"text download failed ({type(e).__name__})"


async def _fetch_texts(client, docs: list, tolerate_errors: bool,
                       deadline_s: Optional[float] = None) -> List[Tuple[Optional[str], Optional[str]]]:
    """Full text for each record in `docs`: (text_or_None, error_or_None).

    One download per record, at most _TEXT_FETCH_CONCURRENCY at a time, all
    inside one overall deadline (OA_TEXT_FETCH_DEADLINE_S by default). A 429
    always propagates and cancels the downloads still queued or running (the
    tool answers with the rate-limit envelope, and the siblings would only meet
    the same 429). Other failures propagate the same way unless
    `tolerate_errors`, in which case that row reports the error class and the
    rest still come back. A row whose download had not finished by the
    deadline comes back (None, <deadline note>) in either mode.
    """
    if not docs:
        return []
    deadline = OA_TEXT_FETCH_DEADLINE_S if deadline_s is None else deadline_s
    gate = asyncio.Semaphore(_TEXT_FETCH_CONCURRENCY)
    tasks = [asyncio.ensure_future(_fetch_one(client, doc, gate, tolerate_errors)) for doc in docs]
    try:
        done, pending = await asyncio.wait(tasks, timeout=deadline, return_when=asyncio.FIRST_EXCEPTION)
    finally:
        # Cancelled from outside, past the deadline, or a sibling raised:
        # nothing keeps spending the shared key after this call has its answer.
        for task in tasks:
            if not task.done():
                task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    failed = next((t for t in done if not t.cancelled() and t.exception() is not None), None)
    if failed is not None:
        raise failed.exception()
    if pending:
        logger.info(f"Office action text deadline reached: {len(pending)} of {len(tasks)} downloads cancelled")
    late = (None, _DEADLINE_ERROR.format(seconds=deadline))
    return [task.result() if task in done else late for task in tasks]


def _text_fetch_cap_block(rows_total: int, texts_fetched: int, tool: str) -> Dict[str, Any]:
    """The envelope block naming the full-text cap, when it cut a response."""
    if tool == "PFW_get_oa_rejections":
        note = (f"Full text is read for the newest {OA_TEXT_FETCH_CAP} rows of a call only; the other "
                f"{rows_total - texts_fetched} rows carry USPTO's rejectionTypeBag without section_counts "
                "(text_available: false). Call PFW_get_oa_text(action_type=..., latest_only=False) for the "
                "examiner's text of older actions, or latest_only=True to triage the newest action alone.")
    else:
        note = (f"PFW_get_oa_text reads at most {OA_TEXT_FETCH_CAP} office actions per call, newest first. "
                "Narrow with action_type= or section=, or use latest_only=True for the most recent one; "
                "PFW_get_oa_rejections lists every action's date and code.")
    return {"cap": OA_TEXT_FETCH_CAP, "rows": rows_total, "texts_fetched": texts_fetched, "note": note}


def _per_document_budget(budget: int, document_count: int) -> int:
    """Split one content budget across the office actions in a response."""
    if document_count <= 1:
        return budget
    return max(_MIN_PER_DOCUMENT_CHARS, budget // document_count)


def _window_office_actions(
    results: list, full_texts: list, application_number: str,
    char_offset: int, per_doc: int,
) -> Dict[str, int]:
    """Give every office action in a multi-OA response its own text window.

    Each entry keeps `text_total_chars` (the full length) next to
    `text_returned_chars` (this window), and carries its own `_window` cursor
    when there is more to read. Entries that fit are left untouched — no
    marker at all, same contract as the shared guard.

    Windowing always starts from `full_texts` (the untouched bodies), so the
    caller can re-run it with a smaller `per_doc` until the whole envelope
    fits. Returns the character tallies the `_bounds` marker reports.
    """
    note = _OA_TEXT_WINDOW_NOTE.format(application_number=application_number)
    returned_chars = 0
    total_chars = 0
    windowed_count = 0
    for entry, full_text in zip(results, full_texts):
        windowed = window_text(
            full_text, offset=char_offset, max_chars=per_doc, note=note
        )
        entry["text"] = windowed["text"]
        entry["text_returned_chars"] = len(windowed["text"])
        entry["text_length_chars"] = entry["text_returned_chars"]
        entry["text_total_chars"] = len(full_text)
        entry.pop(WINDOW_KEY, None)
        entry.pop("truncated", None)
        entry.pop("truncation_note", None)
        if WINDOW_KEY in windowed:
            entry[WINDOW_KEY] = windowed[WINDOW_KEY]
            entry["truncated"] = True
            entry["truncation_note"] = note
            windowed_count += 1
        returned_chars += entry["text_returned_chars"]
        total_chars += len(full_text)
    return {
        "returned_chars": returned_chars,
        "total_chars": total_chars,
        "windowed_count": windowed_count,
    }


def _fit_office_actions(
    envelope: Dict[str, Any], results: list, full_texts: list,
    application_number: str, char_offset: int, budget: int,
) -> Dict[str, Any]:
    """Shrink the per-document window until the WHOLE envelope fits `budget`.

    Splitting the budget evenly across the office actions is not enough on its
    own: the envelope also carries the coverage census, the resolution block
    and per-entry metadata, and JSON-escaping inflates every newline in the
    text. A three-CTNF file came back at about 106,000 characters and was
    discarded by the client instead of being windowed (measured 2026-09-03 on
    application 11/752,072). The loop below measures what will actually ship.
    """
    per_doc = _per_document_budget(budget, len(results))
    ceiling = max(_MIN_PER_DOCUMENT_CHARS, budget - _BOUNDS_RESERVE_CHARS)
    while True:
        tally = _window_office_actions(
            results, full_texts, application_number, char_offset, per_doc
        )
        envelope["per_document_char_budget"] = per_doc
        if measure_chars(envelope) <= ceiling or per_doc <= _MIN_PER_DOCUMENT_CHARS:
            return tally
        per_doc = max(_MIN_PER_DOCUMENT_CHARS, per_doc // 2)


def _attach_office_action_bounds(
    envelope: Dict[str, Any], tally: Dict[str, int], application_number: str, budget: int
) -> None:
    """`_bounds` for the multi-OA path. ABSENT when nothing was cut."""
    if not tally.get("windowed_count"):
        return
    marker = {
        "applied": True,
        "reason": REASON_WINDOW,
        "size_chars": 0,
        "size_limit": budget,
        "stages": [STAGE_TRUNCATED],
        "slimmed_fields": [],
        "items_returned": tally["returned_chars"],
        "items_total": tally["total_chars"],
        "note": _OA_TEXT_BOUNDS_NOTE.format(application_number=application_number),
    }
    envelope[BOUNDS_KEY] = marker
    # Two passes: the second reports the size of the payload actually returned.
    marker["size_chars"] = measure_chars(envelope)
    marker["size_chars"] = measure_chars(envelope)


def section_counts(text: Optional[str]) -> Optional[Dict[str, int]]:
    """'rejected under 35 U.S.C. <section>' statements per statutory section in
    an office action's full text; None when the text is unavailable."""
    if text is None:
        return None
    return {section: _count_section_rejections(text, section) for section in STATUTORY_SECTIONS}


def row_has_corroborated_103(rejection_types: List[str], counts: Optional[Dict[str, int]]) -> bool:
    """'103' in rejectionTypeBag, corroborated by a § 103 rejection statement in
    the office action's own text.

    The bag is a classifier's output, not the examiner's statement of grounds.
    The retired rejections dataset's hasRej103 flag fired on nonstatutory
    (obviousness-type) double-patenting boilerplate ("would have been obvious
    over the reference claims"), measured 2026-09-03 on application 15/603,285,
    whose only CTNF rejects on double patenting and § 112 and nothing under
    § 103. The new index carries the same record (CTNF 2018-01-10) with
    rejectionTypeBag ["103", "112", "DoublePatent"]. A rejection UNDER § 103
    says so in the text, so the text is the corroboration. When the text could
    not be read the bag stands alone and the row says so (`text_available`).
    """
    if "103" not in rejection_types:
        return False
    if counts is None:
        return True
    return counts.get("103", 0) > 0


def distinct_office_actions(docs: list) -> int:
    """Office actions among the returned ROWS, as distinct
    (submission date, document code) pairs. Rows are one per office action on
    the ODP index, so this equals the row count unless two records share a
    mailing date and code."""
    return len({(_submission_date(doc), _doc_code(doc)) for doc in docs})


_OA_REJECTIONS_COUNTS_NOTE = (
    "Rows are ONE PER OFFICE ACTION (CTNF and CTFR records of the ODP Office "
    "Action API). rejection_rows_total is the number of such office actions the "
    "index holds for this application; office_actions_in_returned_rows counts "
    "the distinct (submission_date, doc_code) pairs among the rows THIS response "
    "carries, a floor whenever has_more is true. office_actions_count is a "
    "deprecated alias of rejection_rows_total. rejection_types is USPTO's "
    "rejectionTypeBag for the action (a classifier's output); section_counts is "
    "this server's count of 'rejected under 35 U.S.C. <section>' statements in "
    "the action's full text. They can disagree: application 11/752,072's CTFR "
    "of 2009-09-21 has rejectionTypeBag ['103', '112'] while its text withdraws "
    "the § 112 rejections and rejects claims under § 102(e) and § 103(a) "
    "(probed 2026-10-11). Read the text with PFW_get_oa_text before relying on "
    "either."
)

_OA_REJECTIONS_103_NOTE = (
    "has_103 requires '103' in USPTO's rejectionTypeBag AND at least one "
    "'rejected under 35 U.S.C. 103' statement in the office action's full text "
    "(section_counts['103']). The bag alone also names § 103 on nonstatutory "
    "(obviousness-type) double-patenting boilerplate, which is not a rejection "
    "under 35 U.S.C. 103: application 15/603,285's CTNF of 2018-01-10 carries "
    "['103', '112', 'DoublePatent'] with no § 103 rejection in its text. "
    "has_103_indicator_raw reports the bag alone; when the two disagree, check "
    "has_double_patenting and read the action with PFW_get_oa_text(section='103')."
)

#: Fields of the retired Office Action Rejections dataset that the ODP Office
#: Action API does not publish. The keys stay in every row and summary (null)
#: so a consumer written against them reads "not available", not a KeyError.
_RETIRED_FIELDS = (
    "alice", "mayo", "bilski", "myriad", "cite_103_max", "allowed_claims", "claims",
)

_RETIRED_FIELDS_NOTE = (
    "alice/mayo/bilski/myriad indicators, cite_103_max (max_103_citations), "
    "allowed_claims and claims came from the retired Office Action Rejections "
    "dataset (/api/v1/patent/oa/oa_rejections/v2, HTML 404 since about "
    "2026-10-10). The ODP Office Action API publishes none of them, so they are "
    "null. For eligibility reasoning read PFW_get_oa_text(section='101'); for "
    "cited references use the Citations MCP."
)


def validate_action_type(action_type: str):
    """Return (normalized_code, error_response_or_None) for `action_type`."""
    code = str(action_type).strip().upper()
    if code in OA_TEXT_ACTION_TYPES:
        return code, None
    error = format_error_response(
        f"action_type '{action_type}' is not an office-action document code this tool "
        "reads from the ODP Office Action API, so querying it would return an empty "
        "result that looks identical to 'this application has no such action'.",
        400,
    )
    error["action_types_served"] = dict(OA_TEXT_ACTION_TYPES)
    error["action_types_provenance"] = (
        "Probe-verified 2026-10-11 against the ODP Office Action API "
        "(facets=['documentCode'], index-wide record counts). Codes outside this set "
        "are other papers (petition decisions and the like) or are not in the index; "
        "reach them with PFW_get_application_documents(document_code=...) plus "
        "PFW_get_document_content_with_ocr."
    )
    return code, error


async def _documents_by_code(application_number: str):
    """Census of the application's own document bag, keyed by document code.

    The Office Action index is a SUBSET of what the file wrapper holds (nothing
    mailed before 2007-07-27, and not every action after), and an action it
    does not carry reads exactly like an application that never had one
    (OPEN_ITEMS #5). Returning the bag's own census next to the result makes
    the gap visible. Returns (census, note) and never raises — a census failure
    must not fail the office-action read.
    """
    try:
        docs = await _client().get_documents(application_number, limit=200)
    except Exception as e:
        logger.info(f"Document census unavailable ({type(e).__name__})")
        return None, "Document-bag census unavailable (the documentBag lookup failed)."
    if docs.get("error"):
        return None, "Document-bag census unavailable (the documentBag lookup returned an error)."

    census = {}
    for doc in docs.get("documentBag") or []:
        code = doc.get("documentCode") or "UNKNOWN"
        census[code] = census.get(code, 0) + 1
    if not census:
        return {}, "The application's document bag is empty."

    served = sorted(c for c in census if c in OA_TEXT_ACTION_TYPES)
    note = (
        "documents_by_code is the application's OWN document bag, counted by document "
        "code (up to 200 documents). Compare it against what this call returned: an "
        "office-action code present here but absent from the result is a COVERAGE GAP "
        "in the ODP Office Action index, not an application without that action. "
        f"Office-action codes in this file wrapper: {', '.join(served) or 'none'}. "
        "Read a gapped action with PFW_get_application_documents(document_code=...) "
        "plus PFW_get_document_content_with_ocr."
    )
    return census, note


def _count_section_rejections(text: str, section: str) -> int:
    """How many 'rejected under 35 U.S.C. <section>' statements a text holds.

    Examiners write the statute several ways ("35 U.S.C. 112", "35 USC § 112",
    "35 U.S.C. § 112(b)", "35 u.s.c. 112, second paragraph"); the pattern
    accepts the punctuation variants and is case-insensitive."""
    if not text:
        return 0
    pattern = re.compile(
        r"rejected\s+under\s+35\s*u\.?\s*s\.?\s*c\.?\s*(?:§\s*)?" + re.escape(section) + r"(?![0-9])",
        re.IGNORECASE,
    )
    return len(pattern.findall(text))


def _section_partial_marker(body: str, excerpt: str, section: str) -> Optional[Dict[str, Any]]:
    """The `section_partial` marker when the served excerpt holds fewer
    'rejected under 35 U.S.C. <section>' statements than the full body; None
    when the excerpt is complete."""
    in_body = _count_section_rejections(body, section)
    in_excerpt = _count_section_rejections(excerpt, section)
    if in_body <= in_excerpt:
        return None
    return {
        "rejections_in_excerpt": in_excerpt,
        "rejections_in_full_text": in_body,
        "note": (
            f"PARTIAL § {section} EXCERPT. The text under this office action's "
            f"'Claim Rejections - 35 USC § {section}' heading holds {in_excerpt} "
            f"of the {in_body} 'rejected under 35 U.S.C. {section}' statements in "
            "its full text (the others sit under another heading, e.g. a § 112 "
            "ground stated in a section of its own or in a response to arguments). "
            "Re-read with section='all' before concluding which claims were "
            f"rejected under § {section} and on what theory."
        ),
    }


def _record_fields(doc: Dict[str, Any]) -> Dict[str, Any]:
    """The identifying fields every office-action row carries."""
    return {
        "office_action_id": doc.get("officeActionRecordIdentifier") or "",
        # The Patent Center document identifier: the same id
        # PFW_get_application_documents returns as documentIdentifier.
        "document_identifier": doc.get("obsoleteDocumentIdentifier") or "",
        "doc_description": doc.get("documentCodeDescriptionText") or "",
    }


def _build_oa_entry(doc, body: Optional[str], section: str, application_number: Any = None) -> Dict[str, Any]:
    """One office action's entry: metadata plus the requested section of its
    full text (falling back to the full text, honestly labelled).

    `body` is the full text from the officeActionText download (None when the
    API had none). `application_number` only feeds `cite_as`."""
    body = body or ""
    title = str(_first_value(doc.get("inventionTitle", "")) or "")
    doc_code = _doc_code(doc)

    # `section_returned` must describe what the caller is holding: the full
    # text when no heading for the section was found.
    section_returned = section
    section_note = None
    if section == "all":
        text = body
    else:
        text = extract_section_text(body, section)
        if not text:
            text = body
            section_returned = "all"
            section_note = (
                f"No 'Claim Rejections - 35 USC § {section}' heading was found in this "
                "office action's text, so the FULL text is returned instead. This is "
                f"not a § {section} excerpt: search the text yourself; "
                "`rejection_types` shows whether USPTO's index tags the action "
                f"with § {section} at all."
            )

    # The excerpt is cut at the section's own heading, and a ground stated
    # elsewhere is outside it: application 11/752,072's 2009-01-29 CTNF holds a
    # § 112 first-paragraph AND a § 112 second-paragraph rejection, and an
    # excerpt that carries only one must say so (walkthrough run, 2026-09-05).
    # Count the statements in the full body against the excerpt.
    section_partial = None
    if section != "all" and section_returned == section:
        section_partial = _section_partial_marker(body, text, section)

    entry = {
        "submission_date": doc.get("submissionDate", ""),
        "doc_code": doc_code,
        **_record_fields(doc),
        "art_unit": doc.get("groupArtUnitNumber", ""),
        "invention_title": title,
        "rejection_types": normalize_rejection_types(doc.get("rejectionTypeBag")),
        "section_requested": section,
        "section_returned": section_returned,
        "text": text,
        # `text_length_chars` is kept as an alias of the RETURNED
        # length for consumers written against the old key.
        "text_length_chars": len(text),
        "text_total_chars": len(text),
        "text_returned_chars": len(text),
    }
    if section_note:
        entry["section_note"] = section_note
    if section_partial:
        entry["section_partial"] = section_partial
    # CITATIONS ARE LINKS (2026-09-05). USPTO publishes no public per-document
    # URL for a file-wrapper document, so the target is the APPLICATION's Patent
    # Center page and DOCUMENT_CITATION_NOTE says where to look once it opens.
    # The server's own persistent download links are credentials and are never
    # emitted as a citation target.
    attach_document_cite_as(
        [entry], application_number, code_keys=("doc_code",), date_keys=("submission_date",)
    )
    return entry


def _build_rejection_row(doc: Dict[str, Any], text: Optional[str], text_error: Optional[str]) -> Dict[str, Any]:
    """One PFW_get_oa_rejections row: rejectionTypeBag plus the section counts
    over the office action's full text."""
    types = normalize_rejection_types(doc.get("rejectionTypeBag"))
    counts = section_counts(text)
    row = {
        "submission_date": doc.get("submissionDate", ""),
        "doc_code": _doc_code(doc),
        **_record_fields(doc),
        "art_unit": doc.get("groupArtUnitNumber", ""),
        "rejection_types": types,
        "section_counts": counts,
        "text_available": text is not None,
        "has_101": "101" in types,
        "has_102": "102" in types,
        "has_103": row_has_corroborated_103(types, counts),
        "has_103_indicator_raw": "103" in types,
        "has_112": "112" in types,
        "has_double_patenting": DOUBLE_PATENTING in types,
        **{field: None for field in _RETIRED_FIELDS},
    }
    if text_error:
        row["text_error"] = text_error
    elif text is None:
        row["text_error"] = "the Office Action API holds no text for this record"
    return row


def _summarize_rejections(rows: List[Dict[str, Any]], docs: list, num_found: int) -> Dict[str, Any]:
    """The `summary` block over the returned rows."""
    totals = {section: 0 for section in STATUTORY_SECTIONS}
    by_type: Dict[str, int] = {}
    for row in rows:
        for section, count in (row["section_counts"] or {}).items():
            totals[section] += count
        for rejection_type in row["rejection_types"]:
            by_type[rejection_type] = by_type.get(rejection_type, 0) + 1
    return {
        "has_101": any(r["has_101"] for r in rows),
        "has_102": any(r["has_102"] for r in rows),
        "has_103": any(r["has_103"] for r in rows),
        "has_103_indicator_raw": any(r["has_103_indicator_raw"] for r in rows),
        "has_112": any(r["has_112"] for r in rows),
        "has_double_patenting": any(r["has_double_patenting"] for r in rows),
        "alice_indicator": None,
        "mayo_indicator": None,
        "bilski_indicator": None,
        "myriad_indicator": None,
        "max_103_citations": None,
        # Statements in the returned actions' full texts, per section.
        "section_counts": totals,
        # Returned actions whose rejectionTypeBag names each type.
        "office_actions_by_rejection_type": by_type,
        "office_actions_text_unavailable": sum(1 for r in rows if not r["text_available"]),
        "rejection_rows_total": num_found,
        "office_actions_in_returned_rows": distinct_office_actions(docs),
        # DEPRECATED alias of rejection_rows_total, kept for compatibility.
        "office_actions_count": num_found,
        "counts_note": _OA_REJECTIONS_COUNTS_NOTE,
        "has_103_note": _OA_REJECTIONS_103_NOTE,
        "retired_fields_note": _RETIRED_FIELDS_NOTE,
    }


async def _get_oa_rejections(application_number: str, latest_only: bool, rows: int, content_type: str) -> Dict[str, Any]:
    """PFW_get_oa_rejections, behind the MCP registration."""
    # Validate before anything reaches USPTO.
    if not isinstance(rows, int) or isinstance(rows, bool) or rows < MIN_OA_ROWS or rows > MAX_OA_ROWS:
        return format_error_response(
            f"rows must be an integer between {MIN_OA_ROWS} and {MAX_OA_ROWS}", 400
        )
    rows_applied = 1 if latest_only else rows
    try:
        # An 8-digit identifier is both a valid patent number and a valid
        # application serial — resolve it before it reaches USPTO, and say
        # which lane answered (OPEN_ITEMS #9).
        resolution, resolve_error = await resolve_or_error(
            _client(), application_number, content_type
        )
        if resolve_error:
            return resolve_error
        application_number = resolution.application_number

        client = _get_office_action_client()
        raw = await client.search_office_actions(
            application_number,
            document_codes=REJECTION_ACTION_TYPES,
            offset=0,
            limit=rows_applied,
        )
        docs = sort_docs_newest_first(raw.get("officeActionDataBag") or [])[:rows_applied]
        num_found = raw.get("count", 0)

        if not docs:
            return {
                "success": True,
                **resolution.response_fields(),
                "application_number": application_number,
                "num_found": 0,
                "rows_requested": rows,
                "rows_applied": rows_applied,
                "rejections": [],
                "note": "No non-final or final rejection found in the ODP Office Action index "
                        "for this application. The index holds office actions mailed from "
                        "2007-07-27 onward; the application may have none, or they may predate "
                        "the index. PFW_get_oa_text(action_type='NOA'|'CTRS'|...) reads other "
                        "office actions; PFW_get_application_documents(document_code='CTNF'|'CTFR') "
                        "plus PFW_get_document_content_with_ocr reaches older ones.",
                "data_note": OA_COVERAGE_NOTE,
            }

        # Full text for the newest OA_TEXT_FETCH_CAP rows only; the rest keep the bag.
        head = docs[:OA_TEXT_FETCH_CAP]
        texts = await _fetch_texts(client, head, tolerate_errors=True)
        texts += [(None, f"text not read: only the newest {OA_TEXT_FETCH_CAP} rows of a call are read "
                         "(text_fetch_cap)")] * (len(docs) - len(head))
        rejections = [
            _build_rejection_row(doc, text, error)
            for doc, (text, error) in zip(docs, texts)
        ]
        summary = _summarize_rejections(rejections, docs, num_found)
        # CITATIONS ARE LINKS (2026-09-05): a triage row named an office
        # action by date and code with nothing to click. There is no public
        # per-document URL, so each row cites the application's Patent
        # Center page; DOCUMENT_CITATION_NOTE says where to look there.
        attach_document_cite_as(
            rejections,
            application_number,
            code_keys=("doc_code",),
            date_keys=("submission_date",),
        )

        envelope = {
            "success": True,
            **resolution.response_fields(),
            "application_number": application_number,
            "num_found": num_found,
            "showing": len(docs),
            "rows_requested": rows,
            "rows_applied": rows_applied,
            "has_more": isinstance(num_found, int) and num_found > len(docs),
            "summary": summary,
            "rejections": rejections,
            **citation_block(rejections, DOCUMENT_CITATION_NOTE),
            "data_note": OA_COVERAGE_NOTE,
        }
        if len(docs) > len(head):
            envelope["text_fetch_cap"] = _text_fetch_cap_block(len(docs), len(head), "PFW_get_oa_rejections")
        return envelope

    except Exception as e:
        return _oa_failure(e, application_number)


def _oa_text_argument_error(char_offset: int, max_chars: Optional[int], action_type: Optional[str]):
    """(normalized action_type, error_response_or_None) for PFW_get_oa_text's
    arguments, checked before anything reaches USPTO. A code the index does not
    carry would come back empty and read as "no such action for this
    application" (OPEN_ITEMS #8)."""
    if char_offset < 0:
        return action_type, format_error_response("char_offset must be non-negative", 400)
    if max_chars is not None and max_chars < 1:
        return action_type, format_error_response("max_chars must be at least 1", 400)
    if action_type:
        return validate_action_type(action_type)
    return action_type, None


_NO_TEXT_NOTE = (
    "The Office Action API holds no text for this record (its officeActionText "
    "download answered 'No matching records'). Read it with "
    "PFW_get_application_documents(document_code=...) plus "
    "PFW_get_document_content_with_ocr, using document_identifier."
)


def _oa_text_entries(docs: list, texts: list, section: str, application_number: str) -> List[Dict[str, Any]]:
    """One entry per returned office action, from its record and full text."""
    results = []
    for doc, (text, error) in zip(docs, texts):
        entry = _build_oa_entry(doc, text, section, application_number)
        if text is None and error and "deadline" in error:
            entry["text_error"] = error
            entry["text_note"] = ("The text download did not finish in time; re-call PFW_get_oa_text with "
                                  "latest_only=True or action_type= to read fewer actions.")
        elif text is None:
            entry["text_note"] = _NO_TEXT_NOTE
        results.append(entry)
    return results


def _oa_text_provenance(results: List[Dict[str, Any]], application_number: str) -> Dict[str, Any]:
    """Provenance note, citation block and the detection-only injection scan
    of the returned OA text (kind labels only, never matched text — see
    shared/injection_scan.py). Per-item dicts carry no application_number (it
    is envelope-level), so it is stamped into each flagged entry for
    attribution. `injection_scan` is ABSENT when clean."""
    provenance = {
        "provenance_note": RETRIEVED_TEXT_NOTE,
        **citation_block(results, DOCUMENT_CITATION_NOTE),
    }
    injection = scan_hits(results, text_keys=("text",), id_key="doc_code")
    if injection:
        for entry in injection["flagged"]:
            entry["application_number"] = application_number
        provenance["injection_scan"] = injection
    return provenance


async def _get_oa_text(
    application_number: str, action_type: Optional[str], latest_only: bool, section: str,
    char_offset: int, max_chars: Optional[int], content_type: str,
) -> Dict[str, Any]:
    """PFW_get_oa_text, behind the MCP registration."""
    action_type, argument_error = _oa_text_argument_error(char_offset, max_chars, action_type)
    if argument_error:
        return argument_error
    try:
        resolution, resolve_error = await resolve_or_error(
            _client(), application_number, content_type
        )
        if resolve_error:
            return resolve_error
        application_number = resolution.application_number

        client = _get_office_action_client()

        # Without action_type the search is restricted to the office-action
        # codes this tool serves, so "the most recent office action" is
        # never a petition decision the index also carries.
        codes = [action_type] if action_type else list(OA_TEXT_ACTION_TYPES)
        rows = OA_TEXT_ROWS_ALL
        raw = await client.search_office_actions(
            application_number, document_codes=codes, offset=0, limit=rows
        )
        docs, candidates_considered = select_office_action_rows(
            raw.get("officeActionDataBag") or [], latest_only
        )
        num_found = raw.get("count", 0)

        # The Office Action index is a SUBSET of the file wrapper. Return the
        # application's own document census next to the result so a coverage
        # gap is visible instead of reading as a clean record (OPEN_ITEMS #5).
        census, census_note = await _documents_by_code(application_number)
        coverage = {
            "action_types_served": dict(OA_TEXT_ACTION_TYPES),
            "documents_by_code": census,
            "documents_by_code_note": census_note,
            "order": OA_TEXT_ORDER,
            "order_note": OA_TEXT_ORDER_NOTE,
            "data_note": OA_COVERAGE_NOTE,
        }

        if not docs:
            return {
                "success": True,
                **resolution.response_fields(),
                **coverage,
                "application_number": application_number,
                "num_found": 0,
                "rows_applied": rows,
                "text": "",
                "text_total_chars": 0,
                "text_returned_chars": 0,
                "note": "No office action text found in the ODP Office Action index. It holds "
                        "office actions mailed from 2007-07-27 onward; the application may have "
                        "no public office actions, or they may predate the index — fall back to "
                        "PFW_get_application_documents (document_code='CTNF'|'CTFR'|'NOA') plus "
                        "PFW_get_document_content_with_ocr.",
                "provenance_note": RETRIEVED_TEXT_NOTE,
            }

        # Full text only for the office actions this call returns, never more
        # than OA_TEXT_FETCH_CAP (the search already asks for no more).
        docs = docs[:OA_TEXT_FETCH_CAP]
        texts = await _fetch_texts(client, docs, tolerate_errors=False)
        results = _oa_text_entries(docs, texts, section, application_number)
        provenance = _oa_text_provenance(results, application_number)

        # Budget: the caller explicitly asked for office-action text, so the
        # ceiling is the higher CONTENT budget. With several OAs in one
        # response they SHARE it — one 70K-char final rejection used to be
        # able to crowd out the nine after it.
        budget = min(max_chars, content_char_budget()) if max_chars else content_char_budget()

        if latest_only and results:
            envelope = {
                "success": True,
                **resolution.response_fields(),
                **coverage,
                "application_number": application_number,
                "num_found": num_found,
                "rows_applied": rows,
                "candidates_considered": candidates_considered,
                **results[0],
                **provenance,
            }
            apply_text_window(
                envelope,
                "text",
                offset=char_offset,
                max_chars=budget,
                note=_OA_TEXT_WINDOW_NOTE.format(application_number=application_number),
                aliases={"applied": "truncated", "note": "truncation_note"},
            )
            envelope["text_returned_chars"] = len(envelope["text"])
            envelope["text_length_chars"] = envelope["text_returned_chars"]
            return envelope

        full_texts = [entry["text"] for entry in results]
        envelope = {
            "success": True,
            **resolution.response_fields(),
            **coverage,
            "application_number": application_number,
            "num_found": num_found,
            "showing": len(results),
            "rows_applied": rows,
            "candidates_considered": candidates_considered,
            "per_document_char_budget": _per_document_budget(budget, len(results)),
            "office_actions": results,
            **provenance,
        }
        if isinstance(num_found, int) and num_found > len(results):
            envelope["text_fetch_cap"] = _text_fetch_cap_block(num_found, len(results), "PFW_get_oa_text")
        tally = _fit_office_actions(
            envelope, results, full_texts, application_number, char_offset, budget
        )
        _attach_office_action_bounds(envelope, tally, application_number, budget)
        return envelope

    except Exception as e:
        return _oa_failure(e, application_number)


def register(mcp) -> None:
    """Register the two OA tools."""
    @mcp.tool(name="PFW_get_oa_rejections", annotations={"defer_loading": True, "readOnlyHint": True})
    @mcp_error_handler
    async def pfw_get_oa_rejections(
        application_number: str,
        latest_only: bool = False,
        rows: int = 10,
        content_type: str = "auto",
    ) -> Dict[str, Any]:
        """Get Office Action rejection indicators for a patent application.
    Rejections, 101, 102, 103, 112, double patenting, eligibility, novelty, obviousness, was it rejected, what did the examiner reject, prosecution triage.

    TRIAGE STEP for office-action analysis. Structured, small context — run this first to
    decide which office actions are worth reading in full, then pull only those with
    PFW_get_oa_text.

    Source: the USPTO ODP Office Action API. One row per non-final (CTNF) or final (CTFR)
    rejection, newest first, each with:
    - `rejection_types`: USPTO's rejectionTypeBag for the action, normalised to
      '101', '102', '103', '112', 'DoublePatent', 'Other'
    - `section_counts`: how many 'rejected under 35 U.S.C. <section>' statements the
      action's FULL text holds for 101/102/103/112 (the text is downloaded for the rows
      this call returns, at most the newest 10, never for the whole list)
    - has_101/has_102/has_112/has_double_patenting from the bag; `has_103` requires the
      bag AND a § 103 statement in the text (`has_103_indicator_raw` is the bag alone)
    - `office_action_id` and `document_identifier` (the Patent Center id that
      PFW_get_application_documents returns as documentIdentifier)
    The `summary` block totals the section counts and the rejection types over the
    returned rows. The bag and the text can disagree; `summary.counts_note` gives a
    measured example. The retired dataset's Alice/Mayo/Bilski/Myriad flags, citation
    counts and claim lists are not published by this API: those keys are null
    (`summary.retired_fields_note`).

    Coverage (probed 2026-10-11): office actions mailed from 2007-07-27 onward, almost all
    for applications filed 2001 or later. Earlier actions are not in the index; use
    PFW_get_application_documents(document_code='CTNF'|'CTFR') plus
    PFW_get_document_content_with_ocr for those.

    `rejection_rows_total` (alias `office_actions_count`) is the number of CTNF/CTFR
    office actions the index holds for the application; `office_actions_in_returned_rows`
    counts distinct submission_date + doc_code pairs among the rows returned.

    CITATIONS ARE LINKS: every rejection row carries `cite_as`, a ready-made markdown
    link labelled with the action's code and date. Paste it after each sentence or
    table row that rests on that office action. A date plus a document code with no
    link is not a citation. USPTO publishes no public per-document URL, so the link
    opens the APPLICATION in Patent Center; the office action itself is under
    Documents & Transactions there, by date and code. Never cite this server's own
    persistent document links: those are credentials, not public records.

    Args:
        application_number: Patent application number (e.g., '15992176') or the granted
                            patent number. WARNING: a bare 8-digit number is ambiguous.
                            It is a valid application serial and, since patent numbers
                            crossed US 10,000,000 in mid-2018, also a valid patent
                            number, and resolution is patent-number-first, so an
                            8-digit serial can be captured by an unrelated granted
                            patent. For an application serial, use the slash-comma
                            format (e.g. '11/752,072', '29/328,018'; unambiguous in every era) or pass
                            content_type='application'. Design (29/), Hague (35/), provisional
                            (60/ to 63/) and reexamination (90/, 95/, 96/) serials are read as
                            applications even when bare; a bare 8-digit number is never a
                            pre-grant publication number (those are 11 digits); the response reports
                            identifier_resolved_as, identifier_note and
                            identifier_lanes_tried.
        latest_only: True returns only the most recent rejection (one row, one text
                     download). Default False.
        rows: Office actions to return (1-100, default 10), newest first. The newest 10
              rows cost one text download each; rows past 10 carry the bag only
              (text_available false, `text_fetch_cap` names the cap). The response reports
              rows_requested / rows_applied alongside num_found and showing.
        content_type: 'auto' (default), 'patent' or 'application'. The two explicit
                            values force one resolution lane for a bare 8-digit
                            identifier instead of the patent-number-first probe.

    Examples:
        PFW_get_oa_rejections('15/992,176')            # Up to 10 most recent rejections
        PFW_get_oa_rejections('15/992,176', rows=25)   # Up to 25 rows, text for the newest 10

    Use PFW_get_oa_text to read the text of a specific office action.
    Use PFW_get_application_documents to get document identifiers for download.
        """
        return await _get_oa_rejections(application_number, latest_only, rows, content_type)



    @mcp.tool(name="PFW_get_oa_text", annotations={"defer_loading": True, "readOnlyHint": True})
    @mcp_error_handler
    async def pfw_get_oa_text(
        application_number: str,
        action_type: Optional[str] = None,
        latest_only: bool = True,
        section: str = "all",
        char_offset: int = 0,
        max_chars: Optional[int] = None,
        content_type: str = "auto",
    ) -> Dict[str, Any]:
        """Fetch full text of a USPTO office action (CTNF, CTFR, NOA, etc.).
    Read the office action, examiner's reasoning, rejection text, final rejection, notice of allowance, reasons for allowance, restriction requirement.

    PRIMARY PATH for reading an office action. Returns the examiner's text directly in one
    call — no document-bag lookup, no PDF download, no scanning step in between. Ideal for a non-final
    office action (CTNF), final rejection (CTFR), notice of allowance (NOA), or restriction
    requirement (CTRS).

    Source: the USPTO ODP Office Action API. The search finds the application's office
    actions; the full text of each action returned comes from its officeActionText
    download (fetched only for the actions this call returns). Each action carries
    `office_action_id`, `document_identifier` (the Patent Center id
    PFW_get_application_documents returns) and `rejection_types` (USPTO's
    rejectionTypeBag, normalised to '101', '102', '103', '112', 'DoublePatent', 'Other').

    CITATIONS ARE LINKS: every office action carries `cite_as`, a ready-made markdown
    link labelled with the action's code and date (with latest_only=True it sits at the
    top level of the response; with latest_only=False, on each entry of `office_actions`).
    Paste it after each sentence, quotation or claim-chart row that rests on that action.
    A date, a document code or a claim number with no link is not a citation. USPTO
    publishes no public per-document URL, so the link opens the APPLICATION in Patent
    Center; the office action itself is under Documents & Transactions there, by date and
    code. Never cite this server's own persistent document links: those are credentials,
    not public records.

    Args:
        application_number: Patent application number (e.g., '15992176') or the granted
                            patent number. WARNING: a bare 8-digit number is ambiguous.
                            It is a valid application serial and, since patent numbers
                            crossed US 10,000,000 in mid-2018, also a valid patent
                            number, and resolution is patent-number-first, so an
                            8-digit serial can be captured by an unrelated granted
                            patent. For an application serial, use the slash-comma
                            format (e.g. '11/752,072', '29/328,018'; unambiguous in every era) or pass
                            content_type='application'. Design (29/), Hague (35/), provisional
                            (60/ to 63/) and reexamination (90/, 95/, 96/) serials are read as
                            applications even when bare; a bare 8-digit number is never a
                            pre-grant publication number (those are 11 digits); the response reports
                            identifier_resolved_as, identifier_note and
                            identifier_lanes_tried.
        action_type: Filter by document code. VALIDATED against the office-action codes
                     this tool reads (probe-verified 2026-10-11): CTNF (non-final),
                     CTFR (final rejection), NOA (notice of allowance), CTRS
                     (restriction/election), CTEQ (Ex parte Quayle), CTAV (advisory
                     action), NRES (non-responsive amendment), CTMS (miscellaneous
                     examiner action), EXIN (interview summary), ABN (abandonment).
                     Anything else is rejected with the served set in the error rather
                     than returning an empty result that looks like "no such action".
                     If omitted, returns the most recent office action of any of these types.
        latest_only: Return only the most recent matching OA (default: True).
                     Set to False to return all matching OAs (up to 10).
                     "Most recent" means the LATEST submission_date among the
                     matches: a file with two CTFRs returns the later one. With
                     latest_only=False the returned office_actions are ordered
                     newest first as well; every response states this in
                     `order` / `order_note`.
        section: Which text to return:
                 'all' (default) — the full text (may be large; 70K+ chars on a heavy OA)
                 '101' — only the § 101 eligibility rejection section
                 '102' — only the § 102 novelty rejection section
                 '103' — only the § 103 obviousness rejection section
                 '112' — only the § 112 rejection section
                 A section is the text under the action's own "Claim Rejections -
                 35 USC § <n>" heading, up to the next heading. When the action has no
                 such heading the full text comes back instead; `section_requested`
                 then keeps your value while `section_returned` reports 'all' (what you
                 are actually holding) plus a `section_note`. When the excerpt holds
                 fewer 'rejected under 35 U.S.C. <n>' statements than the full text,
                 `section_partial` gives both counts.
        char_offset: Where to start reading in the text (default 0). Feed
                 `_window.next_offset` back here to continue.
        max_chars: Window size in characters (default USPTO_MAX_CONTENT_CHARS,
                 120,000). With latest_only=False the budget is split across the
                 office actions returned (`per_document_char_budget`) and the
                 split is tightened until the WHOLE envelope fits, so several
                 long actions cannot add up past the budget. `_bounds` reports
                 what was cut and each entry carries its own `_window` cursor.
        content_type: 'auto' (default), 'patent' or 'application'. The two explicit
                 values force one resolution lane for a bare 8-digit identifier
                 instead of the patent-number-first probe.

    Note: Returns text to LLM context for analysis. Coverage (probed 2026-10-11): office
    actions mailed from 2007-07-27 onward, almost all for applications filed 2001 or later.
    Absence of coverage is not an error: the result comes back success=True with
    num_found=0 and empty text.

    COVERAGE CENSUS. Every response carries `documents_by_code` — the application's
    OWN document bag counted by document code — plus `action_types_served`. The Office
    Action index is a subset of the file wrapper, so an office-action code present in
    `documents_by_code` but absent from this result is a coverage GAP, not an
    application that never had that action. Read a gapped action with
    PFW_get_application_documents(document_code=...) plus
    PFW_get_document_content_with_ocr.

    Nothing is discarded — long text is PAGED. `text_total_chars` is the full length,
    `text_returned_chars` what this window holds, and `_window` carries the cursor.
    See PFW_get_guidance(section='limits').

    Fall back to PFW_get_application_documents + PFW_get_document_content_with_ocr only
    for office actions mailed before 2007-07-27 or otherwise missing from the index, for
    non-OA documents (claims, amendments, 892/1449 forms, IDS, specifications), or when an
    actual PDF is needed.

    Examples:
        PFW_get_oa_text('15/992,176')                        # Latest OA full text
        PFW_get_oa_text('15/992,176', action_type='CTNF')    # Latest non-final OA
        PFW_get_oa_text('15/992,176', section='103')         # Only 103 rejection text
        PFW_get_oa_text('15/992,176', latest_only=False)     # Up to 10 OAs full text
        """
        return await _get_oa_text(
            application_number, action_type, latest_only, section, char_offset, max_chars, content_type
        )
