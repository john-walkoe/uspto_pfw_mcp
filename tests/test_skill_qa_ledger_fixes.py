"""Tests for the server defects recorded in the USPTO skill QA ledger.

Source: the 2026-09-03 skill QA round, whose live tool-surface testing
recorded these defects for this server, with the measurements taken on the
same date.

Every case below reproduces something the server ASSERTED that was not true:
"latest" that meant oldest, a budget split that still overran the client, a
document_code example the tool could not execute, an office-action count that
counted rejection rows, a `has_103` that fired on the word "obvious", an
identifier note that dated every slashed serial to before 2001.

Hermetic: no network, no FastMCP server, no USPTO key beyond a placeholder.
"""

import pytest

from patent_filewrapper_mcp.shared.response_bounds import (
    BOUNDS_KEY,
    WINDOW_KEY,
    measure_chars,
)


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

class _CaptureMCP:
    """Collects the functions each tools module registers."""

    def __init__(self):
        self.tools = {}

    def tool(self, *args, **kwargs):
        if args and callable(args[0]):
            fn = args[0]
            self.tools[kwargs.get("name") or fn.__name__] = fn
            return fn

        def decorator(fn):
            self.tools[kwargs.get("name") or fn.__name__] = fn
            return fn

        return decorator


class _FakeOAClient:
    """Stands in for OATextClient / OARejectionClient."""

    def __init__(self, docs, num_found=None, section_text=None):
        self._docs = docs
        self._num_found = len(docs) if num_found is None else num_found
        self._section_text = section_text
        self.calls = []

    async def search(self, criteria, start=0, rows=10):
        self.calls.append({"criteria": criteria, "start": start, "rows": rows})
        return {"response": {"docs": self._docs, "numFound": self._num_found}}

    def extract_body_text(self, doc):
        return doc.get("_body", "")

    def extract_section_text(self, doc, section):
        return self._section_text or ""


@pytest.fixture
def oa_tools(monkeypatch):
    monkeypatch.setenv("USPTO_API_KEY", "test-uspto-key-0123456789")
    from patent_filewrapper_mcp.tools import oa_tools as mod

    fake = _CaptureMCP()
    mod.register(fake)
    return fake.tools, mod


@pytest.fixture
def document_tools(monkeypatch):
    monkeypatch.setenv("USPTO_API_KEY", "test-uspto-key-0123456789")
    from patent_filewrapper_mcp.tools import document_tools as mod

    fake = _CaptureMCP()
    mod.register(fake)
    return fake.tools, mod


def _ctfr(date, body="body"):
    return {
        "_body": body,
        "submissionDate": date,
        "legacyDocumentCodeIdentifier": ["CTFR"],
    }


# ---------------------------------------------------------------------------
# (1) PFW_get_oa_text: latest_only must mean LATEST
# ---------------------------------------------------------------------------
# Ledger: "`latest_only` returns the OLDEST action of a type
# (`OA_TEXT_ROWS_LATEST = 1` takes the first row in ascending date order)".
# Measured on application 16/319,040, two CTFRs (2021-12-21 and 2022-12-27):
# the default call returned the 2021 one.

@pytest.mark.asyncio
async def test_latest_only_returns_the_newest_action_not_the_first_row(oa_tools, monkeypatch):
    tools, mod = oa_tools
    # Dataset order: ASCENDING, exactly as USPTO answers.
    client = _FakeOAClient([
        _ctfr("2021-12-21", "the superseded final rejection"),
        _ctfr("2022-12-27", "the final rejection under appeal"),
    ])
    monkeypatch.setattr(mod, "_get_oa_text_client", lambda: client)

    result = await tools["PFW_get_oa_text"]("16/319,040", action_type="CTFR")

    assert result["submission_date"] == "2022-12-27"
    assert result["text"] == "the final rejection under appeal"
    assert result["candidates_considered"] == 2
    assert result["order"] == mod.OA_TEXT_ORDER


@pytest.mark.asyncio
async def test_latest_only_asks_the_dataset_for_the_whole_window(oa_tools, monkeypatch):
    """A one-row request cannot be sorted, so the row count no longer depends
    on latest_only."""
    tools, mod = oa_tools
    client = _FakeOAClient([_ctfr("2021-12-21"), _ctfr("2022-12-27")])
    monkeypatch.setattr(mod, "_get_oa_text_client", lambda: client)

    await tools["PFW_get_oa_text"]("16/319,040", action_type="CTFR")

    assert client.calls[0]["rows"] == mod.OA_TEXT_ROWS_ALL


@pytest.mark.asyncio
async def test_all_actions_come_back_newest_first(oa_tools, monkeypatch):
    tools, mod = oa_tools
    client = _FakeOAClient([
        _ctfr("2008-09-08"), _ctfr("2009-01-29"), _ctfr("2010-10-13"),
    ])
    monkeypatch.setattr(mod, "_get_oa_text_client", lambda: client)

    result = await tools["PFW_get_oa_text"]("11/752,072", latest_only=False)

    dates = [entry["submission_date"] for entry in result["office_actions"]]
    assert dates == ["2010-10-13", "2009-01-29", "2008-09-08"]
    assert result["order"] == mod.OA_TEXT_ORDER
    assert "newest first" in result["order_note"].lower()


def test_undated_rows_sort_last_rather_than_displacing_a_dated_one(oa_tools):
    _tools, mod = oa_tools

    ordered = mod.sort_docs_newest_first([
        {"submissionDate": ""},
        {"submissionDate": ["2019-01-01"]},
        {},
        {"submissionDate": "2020-06-30"},
    ])

    assert [mod._submission_date(d) for d in ordered] == [
        "2020-06-30", "2019-01-01", "", "",
    ]


# ---------------------------------------------------------------------------
# (1b) The follow-on: latest_only=False must WINDOW, not overrun the client
# ---------------------------------------------------------------------------
# Ledger: "`latest_only=False` on a three-CTNF file overran the client limit at
# about 106,000 characters instead of windowing" (application 11/752,072).

@pytest.mark.asyncio
async def test_three_long_actions_stay_inside_the_content_budget(oa_tools, monkeypatch):
    tools, mod = oa_tools
    # Newlines are what made the measured payload bigger than the sum of the
    # text lengths: json.dumps escapes each one into two characters.
    body = ("z" * 79 + "\n") * 450  # 36,000 chars, ~106K across three actions
    docs = [
        {"_body": body, "submissionDate": f"201{i}-01-01",
         "legacyDocumentCodeIdentifier": ["CTNF"]}
        for i in range(3)
    ]
    monkeypatch.setattr(mod, "_get_oa_text_client", lambda: _FakeOAClient(docs))

    result = await tools["PFW_get_oa_text"]("11/752,072", latest_only=False, max_chars=40_000)

    assert measure_chars(result) <= 40_000
    assert result["per_document_char_budget"] <= 40_000 // 3
    for entry in result["office_actions"]:
        assert entry["text_total_chars"] == len(body)
        assert entry["text_returned_chars"] <= result["per_document_char_budget"]
        assert entry[WINDOW_KEY]["has_more"] is True


@pytest.mark.asyncio
async def test_the_multi_action_cut_is_reported_in_bounds(oa_tools, monkeypatch):
    tools, mod = oa_tools
    docs = [
        {"_body": "z" * 30_000, "submissionDate": f"201{i}-01-01",
         "legacyDocumentCodeIdentifier": ["CTNF"]}
        for i in range(3)
    ]
    monkeypatch.setattr(mod, "_get_oa_text_client", lambda: _FakeOAClient(docs))

    result = await tools["PFW_get_oa_text"]("11/752,072", latest_only=False, max_chars=30_000)

    marker = result[BOUNDS_KEY]
    assert marker["applied"] is True
    assert marker["reason"] == "window"
    assert marker["size_limit"] == 30_000
    assert marker["items_total"] == 90_000          # characters held upstream
    assert marker["items_returned"] < marker["items_total"]
    assert "per_document_char_budget" in marker["note"]


@pytest.mark.asyncio
async def test_actions_that_fit_carry_no_bounds_marker(oa_tools, monkeypatch):
    """No-op is an identity return, the same contract as the shared guard."""
    tools, mod = oa_tools
    docs = [
        {"_body": "short body", "submissionDate": "2019-01-01",
         "legacyDocumentCodeIdentifier": ["CTNF"]}
        for _ in range(3)
    ]
    monkeypatch.setattr(mod, "_get_oa_text_client", lambda: _FakeOAClient(docs))

    result = await tools["PFW_get_oa_text"]("11/752,072", latest_only=False)

    assert BOUNDS_KEY not in result
    for entry in result["office_actions"]:
        assert WINDOW_KEY not in entry
        assert "truncated" not in entry


# ---------------------------------------------------------------------------
# (2) document_code: the pipe-joined form the server teaches must WORK
# ---------------------------------------------------------------------------
# Ledger: "`guidance.py:530, 540, 546, 555, 558` and
# `prompts/document_filtering_assistant.py` (seven call sites) teach
# pipe-joined codes and call `A...` a wildcard", against an exact-match filter.

_BAG = [
    {"documentCode": "CTFR", "documentIdentifier": "d1"},
    {"documentCode": "CTNF", "documentIdentifier": "d2"},
    {"documentCode": "ctnf", "documentIdentifier": "d3"},   # case-insensitive
    {"documentCode": "NOA", "documentIdentifier": "d4"},
    {"documentCode": "A...", "documentIdentifier": "d5"},
    {"documentCode": "A.NE", "documentIdentifier": "d6"},
]


@pytest.fixture
def documents_client(monkeypatch):
    monkeypatch.setenv("USPTO_API_KEY", "test-uspto-key-0123456789")
    from patent_filewrapper_mcp.api.enhanced_client import EnhancedPatentClient

    client = EnhancedPatentClient()

    async def fake_request(path, *args, **kwargs):
        return {"documentBag": [dict(doc) for doc in _BAG]}

    monkeypatch.setattr(client, "_make_request", fake_request)
    return client


async def _codes_returned(client, document_code):
    result = await client.get_documents("11752072", document_code=document_code)
    return sorted(doc["documentIdentifier"] for doc in result["documentBag"])


@pytest.mark.asyncio
async def test_pipe_joined_document_code_ors_the_codes(documents_client):
    assert await _codes_returned(documents_client, "CTFR|CTNF") == ["d1", "d2", "d3"]


@pytest.mark.asyncio
async def test_list_document_code_ors_the_codes(documents_client):
    assert await _codes_returned(documents_client, ["CTFR", "CTNF"]) == ["d1", "d2", "d3"]


@pytest.mark.asyncio
async def test_a_single_code_is_unchanged(documents_client):
    assert await _codes_returned(documents_client, "NOA") == ["d4"]


@pytest.mark.asyncio
async def test_each_code_is_still_an_exact_match_not_a_wildcard(documents_client):
    """'A...' is the literal USPTO amendment code. It must not sweep in A.NE."""
    assert await _codes_returned(documents_client, "A...") == ["d5"]
    assert await _codes_returned(documents_client, ["A...", "A.NE"]) == ["d5", "d6"]


@pytest.mark.asyncio
async def test_the_filter_summary_names_the_codes_that_were_applied(documents_client):
    result = await documents_client.get_documents("11752072", document_code="ctnf|CTFR")

    applied = result["summary"]["filtering"]["filters_applied"]
    assert applied == ["document_code='CTFR|CTNF'"]


@pytest.mark.parametrize("value, expected", [
    (None, set()),
    ("", set()),
    ("   ", set()),
    ("noa", {"NOA"}),
    ("CTFR|CTNF", {"CTFR", "CTNF"}),
    (" CTFR | ctnf ", {"CTFR", "CTNF"}),
    ("CTFR||CTNF|", {"CTFR", "CTNF"}),
    (["CTFR", "CTNF"], {"CTFR", "CTNF"}),
    (["CTFR|CTNF", "NOA"], {"CTFR", "CTNF", "NOA"}),
    ("A...", {"A..."}),
])
def test_parse_document_codes(value, expected):
    from patent_filewrapper_mcp.api.helpers import parse_document_codes

    assert parse_document_codes(value) == expected


def test_no_guidance_or_prompt_still_calls_a_dots_a_wildcard():
    """The guidance said "# Wildcard matches all A. codes" next to a filter
    that has never had a wildcard."""
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "patent_filewrapper_mcp"
    offenders = []
    for path in list(src.glob("prompts/*.py")) + [src / "guidance.py"]:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            lowered = line.lower()
            if "document_code" not in lowered or "wildcard" not in lowered:
                continue
            # A line is allowed to SAY there is no wildcard; it may not claim one.
            if "no wildcard" in lowered or "not a wildcard" in lowered:
                continue
            offenders.append(f"{path.name}:{number}")
    assert offenders == []


# ---------------------------------------------------------------------------
# (3a) max_pages: a friendly 400 naming the parameters that exist
# ---------------------------------------------------------------------------
# Ledger: "No friendly error for `max_pages`."

@pytest.mark.asyncio
async def test_max_pages_returns_a_400_naming_the_real_parameters(document_tools):
    tools, _mod = document_tools

    result = await tools["PFW_get_document_content_with_ocr"](
        "11/752,072", "GN23NLY2PPOPPY5", max_pages=10
    )

    assert result.get("error")
    message = result["error"] if isinstance(result["error"], str) else str(result)
    for parameter in ("char_offset", "max_chars", "page_from", "page_to"):
        assert parameter in message


@pytest.mark.asyncio
async def test_the_supported_window_parameters_are_still_validated(document_tools):
    tools, _mod = document_tools

    assert (await tools["PFW_get_document_content_with_ocr"]("1", "d", char_offset=-1))["error"]
    assert (await tools["PFW_get_document_content_with_ocr"]("1", "d", max_chars=0))["error"]
    assert (await tools["PFW_get_document_content_with_ocr"]("1", "d", page_from=0))["error"]


# ---------------------------------------------------------------------------
# (3b) PFW_get_oa_rejections: office_actions_count counted rejection ROWS
# ---------------------------------------------------------------------------
# Ledger: "`PFW_get_oa_rejections` `summary.office_actions_count` is a
# rejection-row count". Measured on application 15/603,285: num_found 10, all
# one CTNF mailed 2018-01-10, confirmed by PFW_get_oa_text's num_found of 1.

def _rejection_row(**overrides):
    row = {
        "submissionDate": "2018-01-10",
        "legacyDocumentCodeIdentifier": "CTNF",
        "hasRej112": 1,
        "hasRejDP": 1,
        "hasRej103": 1,
        "cite103Max": 0,
    }
    row.update(overrides)
    return row


@pytest.mark.asyncio
async def test_rejection_rows_and_office_actions_are_counted_separately(oa_tools, monkeypatch):
    tools, mod = oa_tools
    docs = [_rejection_row() for _ in range(10)]
    monkeypatch.setattr(mod, "_get_oa_rejection_client", lambda: _FakeOAClient(docs, num_found=10))

    summary = (await tools["PFW_get_oa_rejections"]("15/603,285"))["summary"]

    assert summary["rejection_rows_total"] == 10
    assert summary["office_actions_in_returned_rows"] == 1
    # The old key is kept for one release, as a documented alias of the ROW
    # count it has always held.
    assert summary["office_actions_count"] == summary["rejection_rows_total"]
    assert "deprecated alias" in summary["counts_note"]


@pytest.mark.asyncio
async def test_distinct_office_actions_counts_date_and_code_pairs(oa_tools, monkeypatch):
    tools, mod = oa_tools
    docs = [
        _rejection_row(),
        _rejection_row(),
        _rejection_row(submissionDate="2018-09-26", legacyDocumentCodeIdentifier="CTFR"),
        _rejection_row(legacyDocumentCodeIdentifier="CTFR"),
    ]
    monkeypatch.setattr(mod, "_get_oa_rejection_client", lambda: _FakeOAClient(docs, num_found=4))

    summary = (await tools["PFW_get_oa_rejections"]("15/603,285"))["summary"]

    assert summary["office_actions_in_returned_rows"] == 3


# ---------------------------------------------------------------------------
# (3c) has_103 fired on double-patenting boilerplate
# ---------------------------------------------------------------------------
# Ledger: "`has_103` fires on double-patenting boilerplate with
# `cite_103_max: 0`". Measured on application 15/603,285, whose sole office
# action rejects only on obviousness-type double patenting and 112(1st).

@pytest.mark.asyncio
async def test_has_103_needs_a_103_citation_not_the_word_obvious(oa_tools, monkeypatch):
    tools, mod = oa_tools
    docs = [_rejection_row()]  # hasRej103 set, cite103Max 0, double patenting
    monkeypatch.setattr(mod, "_get_oa_rejection_client", lambda: _FakeOAClient(docs, num_found=1))

    result = await tools["PFW_get_oa_rejections"]("15/603,285")

    assert result["summary"]["has_103"] is False
    assert result["summary"]["has_103_indicator_raw"] is True
    assert result["summary"]["has_double_patenting"] is True
    assert result["rejections"][0]["has_103"] is False
    assert result["rejections"][0]["has_103_indicator_raw"] is True
    assert "double-patenting" in result["summary"]["has_103_note"]


@pytest.mark.asyncio
async def test_a_real_103_rejection_still_reads_as_103(oa_tools, monkeypatch):
    tools, mod = oa_tools
    docs = [_rejection_row(cite103Max=3, hasRejDP=0)]
    monkeypatch.setattr(mod, "_get_oa_rejection_client", lambda: _FakeOAClient(docs, num_found=1))

    result = await tools["PFW_get_oa_rejections"]("18/407,147")

    assert result["summary"]["has_103"] is True
    assert result["summary"]["max_103_citations"] == 3


# ---------------------------------------------------------------------------
# (3d) identifier_note dated every slashed serial to before 2001
# ---------------------------------------------------------------------------
# Ledger: "`identifier_note` says "Pre-2001 application format" for any slashed
# serial". Measured on 17/996,652, filed 2022.

@pytest.mark.parametrize("slashed", ["11/752,072", "17/996,652"])
def test_a_slashed_serial_is_not_described_as_pre_2001(slashed):
    from patent_filewrapper_mcp.util.identifier_normalization import normalize_identifier

    info = normalize_identifier(slashed)

    assert info.identifier_type == "application"
    assert "pre-2001" not in info.notes.lower()
    assert "slash-form serial, unambiguous" in info.notes.lower()


# ---------------------------------------------------------------------------
# (3e) identifier_ambiguous on PFW_get_application_documents
# ---------------------------------------------------------------------------
# Ledger: "`PFW_get_application_documents` has no ... `identifier_ambiguous`"
# flag where the XML tool sets one. Measured on the bare '11752072', which
# silently resolved to a different patent's application (16816197).

class _FakeResolutionClient:
    """The live patent lane, probed 2026-08-30/31 against api.uspto.gov."""

    _PATENT_LANE = {
        "applicationMetaData.patentNumber:11752072": {
            "applicationNumberText": "16816197",
            "applicationMetaData": {"patentNumber": "11752072"},
        },
    }
    _PUBLICATION_LANE = {
        "applicationMetaData.earliestPublicationNumber:20080141381": {
            "applicationNumberText": "11752072",
            "applicationMetaData": {"patentNumber": "7971071"},
        },
        "applicationMetaData.earliestPublicationNumber:US20240000001*": {
            "applicationNumberText": "18407147",
            "applicationMetaData": {},
        },
    }

    def __init__(self, fail_documents=False):
        self.queries = []
        self.fail_documents = fail_documents

    async def lookup_identifier_lane(self, query):
        self.queries.append(query)
        return {**self._PATENT_LANE, **self._PUBLICATION_LANE}.get(query)

    async def get_documents(self, app_number, **kwargs):
        if self.fail_documents:
            raise RuntimeError("upstream exploded")
        return {
            "application_number": app_number,
            "count": 1,
            "documentBag": [{"documentCode": "NOA", "documentIdentifier": "X"}],
            "summary": {},
        }


@pytest.mark.asyncio
async def test_documents_flags_an_ambiguous_identifier(document_tools, monkeypatch):
    tools, mod = document_tools
    monkeypatch.setattr(mod, "_client", lambda: _FakeResolutionClient())

    result = await tools["PFW_get_application_documents"]("11752072", document_code="NOA")

    assert result["identifier_ambiguous"] is True
    assert result["identifier_resolved_as"] == "patent"
    assert result["application_number"] == "16816197"
    assert "11,752,072" in result["identifier_note"]


@pytest.mark.asyncio
async def test_documents_keeps_the_identifier_block_on_the_failure_path(
    document_tools, monkeypatch
):
    """"Which identifier did you actually look up" is exactly the question a
    failed document read raises."""
    tools, mod = document_tools
    monkeypatch.setattr(mod, "_client", lambda: _FakeResolutionClient(fail_documents=True))

    result = await tools["PFW_get_application_documents"]("11752072")

    assert result["success"] is False
    assert result["identifier_ambiguous"] is True
    assert result["identifier_resolved_as"] == "patent"


# ---------------------------------------------------------------------------
# (3g) an 11-digit publication number must resolve
# ---------------------------------------------------------------------------
# Ledger: "the XML tool cannot take an 11-digit publication number although the
# search index crosswalks it via applicationMetaData.earliestPublicationNumber".

@pytest.mark.asyncio
async def test_a_publication_number_resolves_to_its_application():
    from patent_filewrapper_mcp.util.identifier_resolution import resolve_or_error

    client = _FakeResolutionClient()
    resolution, error = await resolve_or_error(client, "20080141381")

    assert error is None
    assert resolution.resolved_as == "publication"
    assert resolution.application_number == "11752072"
    assert client.queries == [
        "applicationMetaData.earliestPublicationNumber:20080141381"
    ]


@pytest.mark.asyncio
async def test_the_st16_publication_form_is_tried_too():
    """USPTO prints the field bare and with a country prefix plus kind code."""
    from patent_filewrapper_mcp.util.identifier_resolution import resolve_or_error

    client = _FakeResolutionClient()
    resolution, error = await resolve_or_error(client, "US 2024/0000001 A1")

    assert error is None
    assert resolution.application_number == "18407147"
    assert client.queries == [
        "applicationMetaData.earliestPublicationNumber:20240000001",
        "applicationMetaData.earliestPublicationNumber:US20240000001*",
    ]


@pytest.mark.asyncio
async def test_an_unknown_publication_number_says_which_field_was_tried():
    from patent_filewrapper_mcp.util.identifier_resolution import resolve_or_error

    client = _FakeResolutionClient()
    resolution, error = await resolve_or_error(client, "20999999999")

    assert error["status_code"] == 404
    assert resolution.resolved_as == "unresolved"
    assert "earliestPublicationNumber" in resolution.note


# ---------------------------------------------------------------------------
# (3f) the description extractor dropped the paragraph id / num attributes
# ---------------------------------------------------------------------------
# Ledger: "the description extractor drops the paragraph `id`/`num` attributes
# a chart needs (pinpoints require include_raw_xml=True)".

_DESCRIPTION_XML = (
    "<us-patent-grant><description>"
    + "".join(
        f'<p id="p-{i:04d}" num="{i:04d}">Paragraph {i}.</p>' for i in range(1, 13)
    )
    + "</description></us-patent-grant>"
)


def _description(**kwargs):
    from patent_filewrapper_mcp.api.xml_parsing import parse_xml_for_llm

    return parse_xml_for_llm(_DESCRIPTION_XML, include_fields=["description"], **kwargs)


def test_description_paragraphs_carry_their_id_and_num():
    structured = _description()

    first = structured["description_paragraphs"][0]
    assert first["id"] == "p-0001"
    assert first["num"] == "0001"
    assert first["position"] == 1
    assert first["text"] == "Paragraph 1."


def test_the_default_description_window_is_unchanged():
    from patent_filewrapper_mcp.api.xml_parsing import DESCRIPTION_PARAGRAPH_LIMIT

    structured = _description()

    assert structured["description_paragraphs_returned"] == DESCRIPTION_PARAGRAPH_LIMIT
    assert structured["description_paragraphs_total"] == 12
    assert structured["description_paragraph_from"] == 1
    assert structured["description_paragraph_to"] == DESCRIPTION_PARAGRAPH_LIMIT
    assert structured["description"].startswith("Paragraph 1.")


def test_the_description_window_moves():
    structured = _description(
        description_paragraph_from=6, description_paragraph_to=8
    )

    assert structured["description_paragraph_from"] == 6
    assert structured["description_paragraph_to"] == 8
    assert structured["description_paragraphs_returned"] == 3
    assert [p["num"] for p in structured["description_paragraphs"]] == [
        "0006", "0007", "0008",
    ]
    assert structured["description"] == (
        "Paragraph 6.\n\nParagraph 7.\n\nParagraph 8."
    )


def test_a_window_past_the_end_is_empty_not_an_error():
    structured = _description(description_paragraph_from=99)

    assert structured["description_paragraphs"] == []
    assert structured["description_paragraphs_returned"] == 0
    assert structured["description_paragraphs_total"] == 12


def test_description_companion_keys_stay_out_of_fields_included():
    from patent_filewrapper_mcp.api.xml_parsing import build_fields_metadata

    metadata = build_fields_metadata(["description"], _description())

    assert metadata["fields_included"] == ["description"]


# ---------------------------------------------------------------------------
# (3h) the inventor search has no census: documented, not fixed
# ---------------------------------------------------------------------------
# Ledger: "The inventor search has no census (no `offset`, `paging.total`
# null)." A real census needs a change on USPTO's side; the limit is stated in
# each inventor tool's own description instead.

@pytest.mark.parametrize("tool_name", [
    "PFW_search_inventor",
    "PFW_search_inventor_minimal",
    "PFW_search_inventor_balanced",
])
def test_every_inventor_tier_states_the_census_limit(monkeypatch, tool_name):
    import inspect

    monkeypatch.setenv("USPTO_API_KEY", "test-uspto-key-0123456789")
    from patent_filewrapper_mcp.tools import search_tools

    fake = _CaptureMCP()
    search_tools.register(fake)
    tool = fake.tools[tool_name]

    doc = inspect.getdoc(tool) or ""
    assert "NO CENSUS" in doc
    assert "paging.total` is null" in doc
    assert "SAMPLE" in doc
    # The claim has to be true: none of the three takes an offset.
    assert "offset" not in inspect.signature(tool).parameters
