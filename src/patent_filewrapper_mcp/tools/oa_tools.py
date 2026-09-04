"""Office Action tools: rejections + full text (audit F2 split from main.py).

COVERAGE-FLOOR PROVENANCE (recorded 2026-08-21)
-----------------------------------------------
Both tools state a coverage floor in their docstrings, and the two floors have
DIFFERENT evidentiary standing. Recording it here so a future reader does not
promote one to the other:

* PFW_get_oa_rejections — "Oct 1, 2017 to 30 days prior to today".
  DOCUMENTED COVERAGE: this is USPTO's own published span for the Office Action
  Rejections dataset, restated by the Citations MCP for the same reason. NOT
  independently probe-verified in this repo.

* PFW_get_oa_text — "office actions mailed roughly 2008 onward".
  DOCUMENTED COVERAGE / UNVERIFIED: the "~2008" figure is asserted consistently
  across this repo's skills (skills/prior-art-analysis, patent-invalidity-
  analysis, pfw-art-unit-quality-assessment, and others) and in the server
  instructions, but NO probe record, date, or baseline for it exists anywhere in
  the repo. It is deliberately hedged ("roughly") in every place it appears.
  Treat it as a working expectation, not a measured boundary; a num_found=0 is
  a normal empty result either way, which is why neither tool errors on it.

Neither floor should be tightened, quoted as exact, or cited as probe-verified
until someone runs a real probe and records the date, method and baseline here.
"""

from typing import Any, Dict, Optional


from ..api.helpers import format_error_response
from ..client_registry import _client, get_api_client
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
from ..util.error_handlers import mcp_error_handler
from ..util.identifier_resolution import resolve_or_error

logger = get_safe_logger(__name__)

#: Document codes the OA TEXT dataset actually serves, with the dataset-wide
#: record count each carried when probed.
#:
#: PROBE-VERIFIED 2026-08-30 against
#: https://api.uspto.gov/api/v1/patent/oa/oa_actions/v1/records with
#: criteria='legacyDocumentCodeIdentifier:<code>'. `action_type` used to be
#: interpolated into the criteria unvalidated, so a code the dataset does not
#: carry returned an empty result indistinguishable from "this application has
#: no such action" (OPEN_ITEMS #8).
#:
#: Codes probed and found EMPTY (numFound 0), i.e. deliberately excluded:
#: CTNR, N417, CTFWF, CTNFR, CTFRR, MCTNF, MCTFR, EXAN, CTAF, CTNRC, CTOA,
#: CTMI, CTAD, CTPA, CTQU, CTSP, NOAR, CNOA, CTFRW, CTNFW, MCTA. Code 892
#: returned 2 records dataset-wide (stray data, not coverage) and is excluded.
OA_TEXT_ACTION_TYPES = {
    "CTNF": "Non-final rejection (8,853,261 records)",
    "NOA": "Notice of allowance (4,699,304 records)",
    "CTFR": "Final rejection (4,376,715 records)",
    "CTRS": "Restriction / election requirement (1,262,527 records)",
    "CTEQ": "Ex parte Quayle action (106,588 records)",
    "CTAV": "Advisory action (47,327 records)",
    "NRES": "Notice of non-responsive amendment (11,481 records)",
    "CTMS": "Miscellaneous examiner action (6,522 records)",
    "EXIN": "Examiner interview summary (1,690 records)",
    "ABN": "Notice of abandonment (457 records)",
}

#: Solr `rows` bounds for PFW_get_oa_rejections. The parameter used to be
#: passed to the OA rejections endpoint VERBATIM with no clamp at all, so
#: rows=100000 (or rows=-1) went straight to USPTO.
MIN_OA_ROWS = 1
MAX_OA_ROWS = 100

#: Rows the OA-text search requests. Hardcoded before; still fixed, but now
#: surfaced in the response so `showing` vs `num_found` is explicable.
#:
#: OA_TEXT_ROWS_LATEST is how many office actions `latest_only=True` RETURNS,
#: not how many rows are requested upstream. The dataset answers in ASCENDING
#: submission-date order, so asking it for one row handed back the OLDEST
#: action of the type: measured 2026-09-03 on application 16/319,040, which
#: carries two CTFRs (2021-12-21 and 2022-12-27) and returned the 2021 one as
#: "the most recent". Every call now requests the full window and sorts
#: NEWEST FIRST here, then slices.
OA_TEXT_ROWS_LATEST = 1
OA_TEXT_ROWS_ALL = 10

#: Value of the `order` field on every PFW_get_oa_text response.
OA_TEXT_ORDER = "submission_date_desc"

OA_TEXT_ORDER_NOTE = (
    "Office actions are ordered NEWEST FIRST by submission_date. The USPTO "
    "dataset answers in ascending date order, so this server sorts before "
    "selecting: latest_only=True returns the action with the LATEST "
    "submission_date among the matches, and with latest_only=False "
    "office_actions[0] is the most recent."
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



def _first_value(value: Any) -> Any:
    """USPTO Solr returns most fields as single-element lists."""
    if isinstance(value, list):
        return value[0] if value else ""
    return "" if value is None else value


def _submission_date(doc: Dict[str, Any]) -> str:
    """The row's submission date as a sortable ISO string ('' when absent)."""
    return str(_first_value(doc.get("submissionDate", "")) or "")


def sort_docs_newest_first(docs: list) -> list:
    """Order raw dataset rows NEWEST FIRST by submission date.

    `latest_only` used to mean "the first row the dataset happened to return",
    which is its OLDEST matching action (see OA_TEXT_ROWS_LATEST). Submission
    dates are ISO (YYYY-MM-DD), so a string sort IS a date sort. A row with no
    date sorts last rather than displacing a dated one, and rows sharing a date
    keep the dataset's own order (`sorted` is stable).
    """
    return sorted(
        docs,
        key=lambda doc: (bool(_submission_date(doc)), _submission_date(doc)),
        reverse=True,
    )


def select_office_action_rows(docs: list, latest_only: bool):
    """(rows_to_return, rows_considered), newest first and then sliced.

    The ordering happens before the slice, which is the whole fix: taking the
    dataset's own first row is taking the OLDEST matching action.
    """
    ordered = sort_docs_newest_first(docs)
    if latest_only:
        return ordered[:OA_TEXT_ROWS_LATEST], len(ordered)
    return ordered, len(ordered)


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


def _int_or_zero(value: Any) -> int:
    """Solr integers arrive as ints, strings or single-element lists."""
    value = _first_value(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def row_has_corroborated_103(doc: Dict[str, Any]) -> bool:
    """USPTO's hasRej103 flag, corroborated by an actual § 103 citation.

    Measured 2026-09-03 on application 15/603,285 (patent 10,213,765): the sole
    office action in that file rejects on nonstatutory (obviousness-type)
    double patenting and 35 U.S.C. 112 first paragraph only, no rejection under
    35 U.S.C. 103 appears anywhere in its text, and `cite103Max` is 0, yet
    `hasRej103` came back true. The upstream classifier fires on the word
    "obvious" inside the double-patenting boilerplate ("would have been obvious
    over the reference claims").

    A rejection UNDER § 103 applies prior art, so it carries at least one § 103
    citation. This dataset serves no office-action text, so the citation count
    is the corroboration available here; `PFW_get_oa_text(section='103')`
    reads the statutory language itself.
    """
    if not _first_value(doc.get("hasRej103", 0)):
        return False
    return _int_or_zero(doc.get("cite103Max", 0)) > 0


def distinct_office_actions(docs: list) -> int:
    """Office actions among the returned ROWS, as distinct
    (submission date, document code) pairs.

    Rows are per rejection GROUP: application 15/603,285 answered with 10 rows
    that were all one CTNF mailed 2018-01-10 (measured 2026-09-03).
    """
    return len({
        (_submission_date(doc), str(_first_value(doc.get("legacyDocumentCodeIdentifier", ""))))
        for doc in docs
    })


_OA_REJECTIONS_COUNTS_NOTE = (
    "rejection_rows_total is the number of rejection ROWS the dataset holds "
    "for this application, not the number of office actions: one office action "
    "commonly yields several rows sharing a submission_date and doc_code. "
    "office_actions_in_returned_rows counts the distinct "
    "(submission_date, doc_code) pairs among the rows THIS response carries, "
    "so it is a floor whenever has_more is true. office_actions_count is a "
    "deprecated alias of rejection_rows_total, kept for one release; it was "
    "named as if it counted office actions and never did. For the true office "
    "action census use PFW_get_oa_text, whose num_found counts actions."
)

_OA_REJECTIONS_103_NOTE = (
    "has_103 requires USPTO's hasRej103 flag AND at least one § 103 citation "
    "(cite_103_max). The raw flag also fires on nonstatutory "
    "(obviousness-type) double-patenting boilerplate, which is not a rejection "
    "under 35 U.S.C. 103: measured 2026-09-03 on application 15/603,285, where "
    "the flag was true with cite_103_max 0 and no § 103 rejection in the text. "
    "has_103_indicator_raw reports the unqualified upstream flag; when the two "
    "disagree, check has_double_patenting and read the action with "
    "PFW_get_oa_text(section='103')."
)


def validate_action_type(action_type: str):
    """Return (normalized_code, error_response_or_None) for `action_type`."""
    code = str(action_type).strip().upper()
    if code in OA_TEXT_ACTION_TYPES:
        return code, None
    error = format_error_response(
        f"action_type '{action_type}' is not a document code the USPTO office-action "
        "TEXT dataset carries, so querying it would return an empty result that looks "
        "identical to 'this application has no such action'.",
        400,
    )
    error["action_types_served"] = dict(OA_TEXT_ACTION_TYPES)
    error["action_types_provenance"] = (
        "Probe-verified 2026-08-30 against the OA text dataset "
        "(legacyDocumentCodeIdentifier:<code>, dataset-wide record counts). Codes "
        "outside this set exist in the file wrapper but not in this dataset — reach "
        "them with PFW_get_application_documents(document_code=...) plus "
        "PFW_get_document_content_with_ocr."
    )
    return code, error


async def _documents_by_code(application_number: str):
    """Census of the application's own document bag, keyed by document code.

    The OA text dataset is a SUBSET of what the file wrapper holds, and an
    action it does not carry reads exactly like an application that never had
    one (OPEN_ITEMS #5). Returning the bag's own census next to the OA-text
    result makes the gap visible. Returns (census, note) and never raises — a
    census failure must not fail the office-action read.
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
        "office-action code present here but absent from the OA-text result is a "
        "COVERAGE GAP in the text dataset, not an application without that action. "
        f"Office-action codes in this file wrapper: {', '.join(served) or 'none'}. "
        "Read a gapped action with PFW_get_application_documents(document_code=...) "
        "plus PFW_get_document_content_with_ocr."
    )
    return census, note


def _build_oa_entry(client, doc, section: str) -> Dict[str, Any]:
    """One office action's entry: title, doc code, and the requested section of
    its text (falling back to the full body, honestly labelled)."""
    title_raw = doc.get("inventionTitle", [])
    title = (title_raw[0] if isinstance(title_raw, list) and title_raw else title_raw) or ""
    doc_code_raw = doc.get("legacyDocumentCodeIdentifier", [])
    doc_code = (doc_code_raw[0] if isinstance(doc_code_raw, list) and doc_code_raw else doc_code_raw) or ""

    # `section_returned` must describe what the caller is holding.
    # It used to echo the REQUESTED section even on the full-body
    # fallback, so a section='103' request that matched nothing came
    # back as the entire office action labelled "103".
    section_returned = section
    section_note = None
    if section == "all":
        text = client.extract_body_text(doc)
    else:
        text = client.extract_section_text(doc, section)
        if not text:
            # Fall back to full body if section not separately indexed
            text = client.extract_body_text(doc)
            section_returned = "all"
            section_note = (
                f"USPTO has no separately indexed § {section} sub-document for "
                "this office action, so the FULL body text is returned instead. "
                "This is not a § " + section + " excerpt — search the text "
                "yourself, or try PFW_get_oa_rejections to confirm whether a "
                f"§ {section} rejection was made at all."
            )
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

    entry = {
        "submission_date": doc.get("submissionDate", ""),
        "doc_code": doc_code,
        "art_unit": doc.get("groupArtUnitNumber", ""),
        "invention_title": title,
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
    return entry


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
    Rejections, 101, 102, 103, 112, Alice, eligibility, novelty, obviousness, was it rejected, what did the examiner reject, prosecution triage.

    TRIAGE STEP for office-action analysis. Cheap, structured, small context — run this
    first to decide which office actions are worth reading in full, then pull only those
    with PFW_get_oa_text.

    Returns structured data about what types of rejections appeared in office actions:
    - 35 U.S.C. 101 (patent eligibility), 102 (novelty), 103 (obviousness), 112 (written description)
    - Alice/Mayo/Bilski/Myriad eligibility indicators
    - Citation counts (max 103 citations, citations equal to 1, citations greater than 3)
    - Quality flags: closingMissing, formParagraphMissing, headerMissing, rejectFormMissmatch

    Data covers office actions from Oct 1, 2017 to 30 days prior to current date. This floor
    is specific to this dataset — PFW_get_oa_text reaches considerably further back (office
    actions mailed roughly 2008 onward), so an empty result here does not mean the OA text
    is unavailable.

    Rows are per rejection group, not per office action: one office action commonly yields
    several rows sharing a submission_date and doc_code with different claim sets. The
    `summary` block reports `rejection_rows_total` (rows the dataset holds) next to
    `office_actions_in_returned_rows` (distinct submission_date + doc_code pairs among the
    rows this response carries, a floor when has_more is true). `office_actions_count` is a
    DEPRECATED alias of rejection_rows_total kept for one release: it was named as if it
    counted office actions and never did. For the office-action census use PFW_get_oa_text,
    whose num_found counts actions.

    `has_103` requires USPTO's flag AND at least one § 103 citation. The raw flag alone
    fires on nonstatutory (obviousness-type) double-patenting boilerplate, which is not a
    rejection under 35 U.S.C. 103; `has_103_indicator_raw` reports the unqualified flag and
    `summary.has_103_note` explains a disagreement.

    Args:
        application_number: Patent application number (e.g., '15992176') or the granted
                            patent number. WARNING: a bare 8-digit number is ambiguous.
                            It is a valid application serial and, since patent numbers
                            crossed US 10,000,000 in mid-2018, also a valid patent
                            number, and resolution is patent-number-first, so an
                            8-digit serial can be captured by an unrelated granted
                            patent. For an application serial, use the slash-comma
                            format (e.g. '11/752,072') or pass
                            content_type='application'; the response reports
                            identifier_resolved_as, identifier_note and
                            identifier_lanes_tried.
        latest_only: reserved; the endpoint returns rejection groups newest-first.
        rows: Rejection rows to request (1-100, default 10). The response reports
              rows_requested / rows_applied alongside num_found and showing.
        content_type: 'auto' (default), 'patent' or 'application'. The two explicit
                            values force one resolution lane for a bare 8-digit
                            identifier instead of the patent-number-first probe.

    Examples:
        PFW_get_oa_rejections('15/992,176')            # All OA rejections for this app
        PFW_get_oa_rejections('15/992,176', rows=25)   # Get up to 25 records

    Use PFW_get_oa_text to fetch the full text of a specific office action.
    Use PFW_get_application_documents to get document identifiers for download.
        """
        # `rows` was forwarded to Solr verbatim with no clamp — validate before
        # anything reaches USPTO.
        if not isinstance(rows, int) or isinstance(rows, bool) or rows < MIN_OA_ROWS or rows > MAX_OA_ROWS:
            return format_error_response(
                f"rows must be an integer between {MIN_OA_ROWS} and {MAX_OA_ROWS}", 400
            )
        try:
            # An 8-digit identifier is both a valid patent number and a valid
            # application serial — resolve it before it reaches Solr, and say
            # which lane answered (OPEN_ITEMS #9).
            resolution, resolve_error = await resolve_or_error(
                _client(), application_number, content_type
            )
            if resolve_error:
                return resolve_error
            application_number = resolution.application_number

            client = _get_oa_rejection_client()
            criteria = f"patentApplicationNumber:{application_number}"
            raw = await client.search(criteria=criteria, start=0, rows=rows)
            docs = raw.get("response", {}).get("docs", [])
            num_found = raw.get("response", {}).get("numFound", 0)

            if not docs:
                return {
                    "success": True,
                    **resolution.response_fields(),
                    "application_number": application_number,
                    "num_found": 0,
                    "rows_requested": rows,
                    "rows_applied": rows,
                    "rejections": [],
                    "note": "No OA rejection data found. Coverage starts Oct 1, 2017. Application may "
                            "predate coverage or have no office actions. PFW_get_oa_text covers office "
                            "actions mailed roughly 2008 onward and may still return the text."
                }

            # Summarize rejection indicators across all OAs
            summary = {
                "has_101": any(d.get("hasRej101", 0) for d in docs),
                "has_102": any(d.get("hasRej102", 0) for d in docs),
                "has_103": any(row_has_corroborated_103(d) for d in docs),
                "has_103_indicator_raw": any(d.get("hasRej103", 0) for d in docs),
                "has_112": any(d.get("hasRej112", 0) for d in docs),
                "has_double_patenting": any(d.get("hasRejDP", 0) for d in docs),
                "alice_indicator": any(d.get("aliceIndicator") for d in docs),
                "mayo_indicator": any(d.get("mayoIndicator") for d in docs),
                "bilski_indicator": any(d.get("bilskiIndicator") for d in docs),
                "myriad_indicator": any(d.get("myriadIndicator") for d in docs),
                "max_103_citations": max((_int_or_zero(d.get("cite103Max", 0)) for d in docs), default=0),
                "rejection_rows_total": num_found,
                "office_actions_in_returned_rows": distinct_office_actions(docs),
                # DEPRECATED alias of rejection_rows_total, kept for one
                # release: the key was named as if it counted office actions
                # and has always held the rejection-row count.
                "office_actions_count": num_found,
                "counts_note": _OA_REJECTIONS_COUNTS_NOTE,
                "has_103_note": _OA_REJECTIONS_103_NOTE,
            }

            return {
                "success": True,
                **resolution.response_fields(),
                "application_number": application_number,
                "num_found": num_found,
                "showing": len(docs),
                "rows_requested": rows,
                "rows_applied": rows,
                "has_more": isinstance(num_found, int) and num_found > len(docs),
                "summary": summary,
                "rejections": [
                    {
                        "submission_date": d.get("submissionDate", ""),
                        "doc_code": d.get("legacyDocumentCodeIdentifier", ""),
                        "art_unit": d.get("groupArtUnitNumber", ""),
                        "has_101": bool(d.get("hasRej101", 0)),
                        "has_102": bool(d.get("hasRej102", 0)),
                        "has_103": row_has_corroborated_103(d),
                        "has_103_indicator_raw": bool(d.get("hasRej103", 0)),
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

    Args:
        application_number: Patent application number (e.g., '15992176') or the granted
                            patent number. WARNING: a bare 8-digit number is ambiguous.
                            It is a valid application serial and, since patent numbers
                            crossed US 10,000,000 in mid-2018, also a valid patent
                            number, and resolution is patent-number-first, so an
                            8-digit serial can be captured by an unrelated granted
                            patent. For an application serial, use the slash-comma
                            format (e.g. '11/752,072') or pass
                            content_type='application'; the response reports
                            identifier_resolved_as, identifier_note and
                            identifier_lanes_tried.
        action_type: Filter by document code. VALIDATED against the codes this dataset
                     actually serves (probe-verified 2026-08-30): CTNF (non-final),
                     CTFR (final rejection), NOA (notice of allowance), CTRS
                     (restriction/election), CTEQ (Ex parte Quayle), CTAV (advisory
                     action), NRES (non-responsive amendment), CTMS (miscellaneous
                     examiner action), EXIN (interview summary), ABN (abandonment).
                     Anything else is rejected with the served set in the error rather
                     than returning an empty result that looks like "no such action".
                     If omitted, returns the most recent office action of any type.
        latest_only: Return only the most recent matching OA (default: True).
                     Set to False to return all matching OAs (up to 10).
                     "Most recent" means the LATEST submission_date among the
                     matches: the matches are sorted newest-first here before
                     one is taken, so a file with two CTFRs returns the later
                     one. With latest_only=False the returned office_actions
                     are ordered newest first as well; every response states
                     this in `order` / `order_note`.
        section: Which text to return:
                 'all' (default) — full bodyText (may be large; 70K+ chars on a heavy OA)
                 '101' — only the § 101 eligibility rejection section
                 '102' — only the § 102 novelty rejection section
                 '103' — only the § 103 obviousness rejection section
                 '112' — only the § 112 written description rejection section
                 USPTO populates these section sub-documents sparsely — 101/102/112 are
                 often empty even when 103 is present. When the requested section is
                 empty this falls back to the full body; `section_requested` then keeps
                 your value while `section_returned` reports 'all' (what you are
                 actually holding) plus a `section_note`.
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

    Note: Returns text to LLM context for analysis. Coverage is office actions mailed
    roughly 2008 onward (10-series applications and later), which is far broader than the
    Oct 1, 2017 floor on PFW_get_oa_rejections. Absence of coverage is not an error: the
    result comes back success=True with num_found=0 and empty text.

    COVERAGE CENSUS. Every response carries `documents_by_code` — the application's
    OWN document bag counted by document code — plus `action_types_served`. The OA
    text dataset is a subset of the file wrapper, so an office-action code present in
    `documents_by_code` but absent from this result is a coverage GAP, not an
    application that never had that action. Read a gapped action with
    PFW_get_application_documents(document_code=...) plus
    PFW_get_document_content_with_ocr.

    Nothing is discarded — long text is PAGED. `text_total_chars` is the full length,
    `text_returned_chars` what this window holds, and `_window` carries the cursor.
    See PFW_get_guidance(section='limits').

    Fall back to PFW_get_application_documents + PFW_get_document_content_with_ocr only
    for office actions older than this dataset, for non-OA documents (claims, amendments,
    892/1449 forms, IDS, specifications), or when an actual PDF is needed.

    Examples:
        PFW_get_oa_text('15/992,176')                        # Latest OA full text
        PFW_get_oa_text('15/992,176', action_type='CTNF')    # Latest non-final OA
        PFW_get_oa_text('15/992,176', section='103')         # Only 103 rejection text
        PFW_get_oa_text('15/992,176', latest_only=False)     # All OAs full text
        """
        if char_offset < 0:
            return format_error_response("char_offset must be non-negative", 400)
        if max_chars is not None and max_chars < 1:
            return format_error_response("max_chars must be at least 1", 400)
        # `action_type` was interpolated into the Solr criteria unvalidated, so a
        # code this dataset does not carry came back empty and read as "no such
        # action for this application" (OPEN_ITEMS #8).
        if action_type:
            action_type, action_type_error = validate_action_type(action_type)
            if action_type_error:
                return action_type_error
        try:
            resolution, resolve_error = await resolve_or_error(
                _client(), application_number, content_type
            )
            if resolve_error:
                return resolve_error
            application_number = resolution.application_number

            client = _get_oa_text_client()

            # Build criteria
            criteria_parts = [f"patentApplicationNumber:{application_number}"]
            if action_type:
                criteria_parts.append(f"legacyDocumentCodeIdentifier:{action_type}")
            criteria = " AND ".join(criteria_parts)

            # ALWAYS request the full window and sort here. Asking the dataset
            # for one row returned its FIRST row in ascending date order, i.e.
            # the OLDEST matching action, which is the opposite of what
            # latest_only promises (see OA_TEXT_ROWS_LATEST).
            rows = OA_TEXT_ROWS_ALL
            raw = await client.search(criteria=criteria, start=0, rows=rows)
            docs, candidates_considered = select_office_action_rows(
                raw.get("response", {}).get("docs", []), latest_only
            )
            num_found = raw.get("response", {}).get("numFound", 0)

            # The OA text dataset is a SUBSET of the file wrapper. Return the
            # application's own document census next to the result so a coverage
            # gap is visible instead of reading as a clean record (OPEN_ITEMS #5).
            census, census_note = await _documents_by_code(application_number)
            coverage = {
                "action_types_served": dict(OA_TEXT_ACTION_TYPES),
                "documents_by_code": census,
                "documents_by_code_note": census_note,
                "order": OA_TEXT_ORDER,
                "order_note": OA_TEXT_ORDER_NOTE,
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
                    "note": "No office action text found. Coverage is office actions mailed roughly "
                            "2008 onward. Application may have no public office actions, or its "
                            "office actions may predate coverage — fall back to "
                            "PFW_get_application_documents (document_code='CTNF'|'CTFR'|'NOA') plus "
                            "PFW_get_document_content_with_ocr.",
                    "provenance_note": RETRIEVED_TEXT_NOTE,
                }

            results = [_build_oa_entry(client, doc, section) for doc in docs]

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
            tally = _fit_office_actions(
                envelope, results, full_texts, application_number, char_offset, budget
            )
            _attach_office_action_bounds(envelope, tally, application_number, budget)
            return envelope

        except Exception as e:
            return {"success": False, "error": str(e), "application_number": application_number}

