"""Tests for the honesty fixes shipped alongside the response-size guard.

Every case here pins a response that used to ASSERT SOMETHING FALSE — a limit
that was never applied, a count contradicting its own list, a section label
that did not describe the text under it, a page count of 0 meaning "unknown".
The theme is that the caps themselves mostly stayed; what changed is that the
response now says what it did.

Hermetic: no network, no FastMCP server, no USPTO key beyond a placeholder.
"""

import pytest

from patent_filewrapper_mcp.api import enhanced_client as ec_mod
from patent_filewrapper_mcp.api.enhanced_client import EnhancedPatentClient
from patent_filewrapper_mcp.api.helpers import MAX_INVENTOR_QUERIES, create_inventor_queries
from patent_filewrapper_mcp.api.xml_parsing import (
    CITATION_LIMIT,
    DESCRIPTION_PARAGRAPH_LIMIT,
    build_fields_metadata,
    parse_xml_for_llm,
)
from patent_filewrapper_mcp.models.search_params import (
    MAX_SEARCH_LIMIT,
    InventorSearchParameters,
    ParameterValidationError,
    SearchParameters,
)
from patent_filewrapper_mcp.shared.response_bounds import BOUNDS_KEY, WINDOW_KEY


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("USPTO_API_KEY", "test-uspto-key-0123456789")
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    c = EnhancedPatentClient()
    c.mistral_api_key = None
    return c


# ---------------------------------------------------------------------------
# (a) The search limit: one honest ceiling across all three layers
# ---------------------------------------------------------------------------

def test_all_three_layers_agree_on_the_ceiling():
    """MAX_SEARCH_LIMIT was 1000, SearchParameters rejected >500, and the wire
    clamped to 100 — a caller could be accepted at 500 and served 100."""
    assert EnhancedPatentClient.MAX_SEARCH_LIMIT == 100
    assert MAX_SEARCH_LIMIT == 100


@pytest.mark.parametrize("params_cls, kwargs", [
    (SearchParameters, {"query": "x"}),
    (InventorSearchParameters, {"name": "Smith"}),
])
def test_search_params_reject_above_the_ceiling(params_cls, kwargs):
    params_cls(limit=MAX_SEARCH_LIMIT, **kwargs)  # the ceiling itself is fine
    with pytest.raises(ParameterValidationError) as exc:
        params_cls(limit=MAX_SEARCH_LIMIT + 1, **kwargs)
    assert exc.value.field == "limit"


@pytest.mark.asyncio
async def test_search_reports_the_applied_limit_not_the_requested_one(client, monkeypatch):
    """The envelope used to echo `limit: 500` on a response the wire had capped
    at 100 — an active false assertion, not merely a missing one."""
    sent = {}

    async def fake_request(endpoint, method="GET", **kwargs):
        sent.update(kwargs.get("json") or {})
        return {
            "patentFileWrapperDataBag": [
                {"applicationNumberText": f"1{i:07d}"} for i in range(100)
            ],
            "count": 1372,
        }

    monkeypatch.setattr(client, "_make_request", fake_request)

    result = await client.search_applications("q", limit=500, offset=0)

    assert sent["pagination"]["limit"] == 100  # what the wire actually got
    assert result["limit"] == 100              # what the envelope now claims
    paging = result["paging"]
    assert paging["limit_requested"] == 500
    assert paging["limit_applied"] == 100
    assert paging["returned"] == 100
    assert paging["total"] == 1372
    assert paging["has_more"] is True
    assert paging["next_offset"] == 100


@pytest.mark.asyncio
async def test_paging_block_reports_exhaustion(client, monkeypatch):
    async def fake_request(endpoint, method="GET", **kwargs):
        return {"patentFileWrapperDataBag": [{"applicationNumberText": "10000001"}], "count": 1}

    monkeypatch.setattr(client, "_make_request", fake_request)

    paging = (await client.search_applications("q", limit=10))["paging"]
    assert paging["has_more"] is False
    assert paging["next_offset"] is None


# ---------------------------------------------------------------------------
# (b)/(i) Inventor fan-out: the count must match its own list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_inventor_count_matches_the_returned_list(client, monkeypatch):
    async def fake_search(query, limit, offset, fields):
        return {
            "success": True,
            "applications": [
                {"applicationNumberText": f"2{i:07d}"} for i in range(limit)
            ],
        }

    monkeypatch.setattr(client, "search_applications", fake_search)

    result = await client.search_inventor("John Q Smith", limit=3)

    assert result["total_unique_applications"] == len(result["unique_applications"]) == 3
    assert result["paging"]["returned"] == 3
    # The fan-out has no server-side total; one is never guessed.
    assert result["paging"]["total"] is None


@pytest.mark.asyncio
async def test_inventor_reports_the_sub_query_limit(client, monkeypatch):
    """Each name-variant query fetches at most INVENTOR_SUBQUERY_LIMIT, so a
    short result set does not mean the portfolio is exhausted."""
    captured = []

    async def fake_search(query, limit, offset, fields):
        captured.append(limit)
        return {"success": True, "applications": []}

    monkeypatch.setattr(client, "search_applications", fake_search)

    result = await client.search_inventor("John Q Smith", limit=100)

    assert set(captured) == {EnhancedPatentClient.INVENTOR_SUBQUERY_LIMIT}
    assert result["sub_query_limit"] == EnhancedPatentClient.INVENTOR_SUBQUERY_LIMIT
    assert "sub_query_limit_note" in result


@pytest.mark.asyncio
async def test_inventor_reports_generated_vs_executed_queries(client, monkeypatch):
    """A RECALL bug: a 3-part name generates more variants than the cap runs,
    and applications matched only by a dropped variant never appeared."""
    async def fake_search(query, limit, offset, fields):
        return {"success": True, "applications": []}

    monkeypatch.setattr(client, "search_applications", fake_search)

    result = await client.search_inventor(
        "Maria Elena Rodriguez Garcia", strategy="comprehensive"
    )

    assert result["queries_executed"] == MAX_INVENTOR_QUERIES
    assert result["queries_generated"] > result["queries_executed"]
    assert "may be missing" in result["queries_note"]
    # `queries_used` shows only 5 — the counter says so rather than letting the
    # key imply the whole set.
    assert len(result["queries_used"]) == result["queries_used_shown"] == 5


def test_create_inventor_queries_keeps_its_cap_and_reports_the_total():
    """The cap is deliberately UNCHANGED (each variant is a USPTO round trip);
    only the reporting is new."""
    name = "Maria Elena Rodriguez Garcia"
    plain = create_inventor_queries(name, "comprehensive")
    executed, generated = create_inventor_queries(name, "comprehensive", with_totals=True)

    assert plain == executed
    assert len(executed) == MAX_INVENTOR_QUERIES
    assert generated > MAX_INVENTOR_QUERIES


# ---------------------------------------------------------------------------
# (d) XML: caps that used to be invisible
# ---------------------------------------------------------------------------

_XML = (
    "<us-patent-grant><abstract>An abstract.</abstract><description>"
    + "".join(f"<p>Paragraph {i}.</p>" for i in range(40))
    + "</description>"
    + "".join(
        f"<citation><patcit><doc-number>{7000000 + i}</doc-number></patcit></citation>"
        for i in range(25)
    )
    + "</us-patent-grant>"
)


def test_description_cap_is_marked_with_returned_and_total():
    structured = parse_xml_for_llm(_XML, include_fields=["description"])

    assert structured["description_paragraphs_returned"] == DESCRIPTION_PARAGRAPH_LIMIT
    assert structured["description_paragraphs_total"] == 40
    assert "first 5 of 40" in structured["description_note"]
    # The default size is UNCHANGED — only the marker is new.
    assert structured["description"].count("Paragraph") == DESCRIPTION_PARAGRAPH_LIMIT


def test_citation_cap_is_marked_with_returned_and_total():
    structured = parse_xml_for_llm(_XML, include_fields=["citations"])

    assert len(structured["citations"]) == CITATION_LIMIT
    assert structured["citations_returned"] == CITATION_LIMIT
    assert structured["citations_total"] == 25
    assert "10 of 25" in structured["citations_note"]


def test_no_marker_when_nothing_was_capped():
    short = (
        "<us-patent-grant><description><p>Only one.</p></description></us-patent-grant>"
    )
    structured = parse_xml_for_llm(short, include_fields=["description"])

    assert structured["description_paragraphs_returned"] == 1
    assert structured["description_paragraphs_total"] == 1
    assert "description_note" not in structured


def test_markers_do_not_pollute_fields_included():
    """`fields_included` drives field discoverability — the truncation markers
    are bookkeeping, not selectable content fields."""
    structured = parse_xml_for_llm(_XML, include_fields=["description", "citations"])

    metadata = build_fields_metadata(["description", "citations"], structured)
    assert sorted(metadata["fields_included"]) == ["citations", "description"]


# ---------------------------------------------------------------------------
# (f) The free PyPDF2 tier: page cap + page headers
# ---------------------------------------------------------------------------

#: Realistic page text. It has to be long enough for is_good_extraction's
#: alphabetic-character ratio: the `=== PAGE N ===` headers are punctuation, so
#: on a toy 25-char page they would dominate the ratio and the tier would
#: (correctly, for a real scan) fall through to OCR. Real prosecution pages run
#: to thousands of characters, where a 15-char header is noise.
_PAGE_BODY = (
    "The claims stand rejected under thirty five United States Code section "
    "one hundred three as being unpatentable over the cited reference in view "
    "of the applicant admitted prior art of record on page %d. "
)


class _FakePage:
    def __init__(self, index, text=None):
        self._text = _PAGE_BODY % index if text is None else text

    def extract_text(self):
        return self._text


class _FakeReader:
    def __init__(self, _stream):
        self.pages = _FakeReader.pages_to_serve


@pytest.fixture
def fake_pypdf(monkeypatch):
    import PyPDF2

    monkeypatch.setattr(PyPDF2, "PdfReader", _FakeReader)
    return _FakeReader


@pytest.mark.asyncio
async def test_pypdf_emits_page_headers_in_the_shared_format(client, fake_pypdf):
    """`=== PAGE N ===` is what shared/response_bounds.PAGE_MARKER_PATTERN
    recognizes, so page-unit windows only work if this tier emits them."""
    fake_pypdf.pages_to_serve = [_FakePage(i) for i in range(1, 4)]

    text = await client.extract_with_pypdf2(b"%PDF-")

    assert text.startswith("=== PAGE 1 ===")
    assert "=== PAGE 2 ===" in text and "=== PAGE 3 ===" in text


@pytest.mark.asyncio
async def test_pypdf_keeps_the_header_on_a_blank_page(client, fake_pypdf):
    """A page that yields no text keeps its header, so character offsets stay
    aligned with the document's real page numbering."""
    fake_pypdf.pages_to_serve = [_FakePage(1), _FakePage(2, text="  "), _FakePage(3)]

    text = await client.extract_with_pypdf2(b"%PDF-")

    assert "=== PAGE 2 ===\n[no text recovered from this page]" in text


@pytest.mark.asyncio
async def test_pypdf_page_cap_fires_and_is_marked(client, fake_pypdf, monkeypatch):
    monkeypatch.setenv("PYPDF_MAX_PAGES", "5")
    fake_pypdf.pages_to_serve = [_FakePage(i) for i in range(1, 31)]
    status = {}

    text = await client.extract_with_pypdf2(b"%PDF-", status)

    assert "=== PAGE 5 ===" in text and "=== PAGE 6 ===" not in text
    assert status["page_count"] == 30          # the reader's REAL count
    assert status["pages_extracted"] == 5
    assert status["pages_truncated"] == 25
    assert "PYPDF_MAX_PAGES" in status["truncation_note"]


@pytest.mark.asyncio
async def test_pypdf_tier_surfaces_the_cap_as_a_page_bounds_marker(client, fake_pypdf, monkeypatch):
    """A page cap means pages were never EXTRACTED, so it is `_bounds` with
    reason 'window' counting PAGES — not `_window`, whose counters are
    contractually characters of text the caller is holding."""
    monkeypatch.setenv("PYPDF_MAX_PAGES", "5")
    fake_pypdf.pages_to_serve = [_FakePage(i) for i in range(1, 31)]

    update = await client._try_pypdf2_tier(b"%PDF-", "DOC1")

    assert update["extraction_method"] == "PyPDF2"
    assert update["page_count"] == 30
    assert update["page_count_source"] == "pypdf"
    assert update["truncated"] is True
    marker = update[BOUNDS_KEY]
    assert marker["reason"] == "window"
    assert marker["items_returned"] == 5
    assert marker["items_total"] == 30
    assert WINDOW_KEY not in update


@pytest.mark.asyncio
async def test_no_cap_marker_when_the_document_fits(client, fake_pypdf, monkeypatch):
    monkeypatch.setenv("PYPDF_MAX_PAGES", "200")
    fake_pypdf.pages_to_serve = [_FakePage(i) for i in range(1, 4)]

    update = await client._try_pypdf2_tier(b"%PDF-", "DOC1")

    assert BOUNDS_KEY not in update
    assert "truncated" not in update


def test_pypdf_max_pages_env_parsing(monkeypatch):
    monkeypatch.delenv("PYPDF_MAX_PAGES", raising=False)
    assert ec_mod.pypdf_max_pages() == 200
    monkeypatch.setenv("PYPDF_MAX_PAGES", "25")
    assert ec_mod.pypdf_max_pages() == 25
    monkeypatch.setenv("PYPDF_MAX_PAGES", "garbage")
    assert ec_mod.pypdf_max_pages() == 200


# ---------------------------------------------------------------------------
# (f) Page counts are never fabricated
# ---------------------------------------------------------------------------

def test_page_count_prefers_the_document_bag():
    count, source = ec_mod._resolve_page_count({"pageTotalQuantity": 12}, b"")
    assert (count, source) == (12, "downloadOptionBag")


def test_page_count_falls_back_to_the_pdf_bytes(fake_pypdf):
    fake_pypdf.pages_to_serve = [_FakePage(i) for i in range(1, 8)]

    count, source = ec_mod._resolve_page_count({}, b"%PDF-")

    assert (count, source) == (7, "pdf")


def test_missing_page_count_is_null_not_zero(monkeypatch):
    """`pageTotalQuantity` used to be read with a 0 default, which reads as
    "this document has no pages" rather than "the metadata did not say" — and
    made every "did the cap fire?" comparison silently false."""
    monkeypatch.setattr(ec_mod, "PDF_AVAILABLE", False)

    count, source = ec_mod._resolve_page_count({}, b"%PDF-")

    assert count is None
    assert source == "unknown"


# ---------------------------------------------------------------------------
# (g) The granted-patent package's capped per-component fetch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_granted_package_marks_a_capped_version_selection(client, monkeypatch):
    """A 12-amendment claims history was decided from the 5 versions the fetch
    happened to return, and the response said nothing about the other 7."""
    async def fake_get_documents(app_number, limit=None, document_code=None, direction_category=None):
        return {
            "success": True,
            "count": 5,
            "matched_count": 12 if document_code == "CLM" else 1,
            "documentBag": [
                {
                    "documentIdentifier": f"{document_code}{i}",
                    "documentCode": document_code,
                    "officialDate": f"202{i}-01-01",
                    "downloadOptionBag": [
                        {"mimeTypeIdentifier": "PDF", "downloadUrl": "u", "pageTotalQuantity": 3}
                    ],
                }
                for i in range(5)
            ],
        }

    monkeypatch.setattr(client, "get_documents", fake_get_documents)

    result = await client.get_granted_patent_documents_download("14171705")

    claims = result["granted_patent_components"]["claims"]
    assert claims["versions_considered"] == 5
    assert claims["versions_available"] == 12
    assert claims["versions_fetch_limit"] == ec_mod.GRANTED_COMPONENT_FETCH_LIMIT
    assert "only the first 5 were fetched" in claims["selection_note"]
    # A component with nothing hidden carries no note.
    assert "selection_note" not in result["granted_patent_components"]["abstract"]


@pytest.mark.asyncio
async def test_get_documents_reports_the_pre_limit_match_count(client, monkeypatch):
    async def fake_request(endpoint, method="GET", **kwargs):
        return {"documentBag": [
            {"documentIdentifier": f"D{i}", "documentCode": "CLM"} for i in range(40)
        ]}

    monkeypatch.setattr(client, "_make_request", fake_request)

    result = await client.get_documents("14171705", limit=5, document_code="CLM")

    assert result["count"] == 5
    assert result["matched_count"] == 40
    assert result["summary"]["filtering"]["matched_document_count"] == 40


# ---------------------------------------------------------------------------
# Tool-level: a stand-in mcp captures the registered tool functions
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


# ---------------------------------------------------------------------------
# (e) PFW_get_oa_text: section_returned must describe what you are holding
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_oa_text_says_all_when_the_section_matched_nothing(oa_tools, monkeypatch):
    """A section='103' request that matched nothing used to return the ENTIRE
    office action while section_returned still said '103'."""
    tools, mod = oa_tools
    body = "Full office action body. " * 40
    client = _FakeOAClient([{"_body": body, "legacyDocumentCodeIdentifier": ["CTFR"]}])
    monkeypatch.setattr(mod, "_get_oa_text_client", lambda: client)

    result = await tools["PFW_get_oa_text"]("15992176", section="103")

    assert result["section_requested"] == "103"
    assert result["section_returned"] == "all"
    assert "no separately indexed" in result["section_note"]
    assert result["text"] == body


@pytest.mark.asyncio
async def test_oa_text_keeps_the_section_label_when_the_section_exists(oa_tools, monkeypatch):
    tools, mod = oa_tools
    section = "Claims 1-9 are rejected under 35 USC 103. " * 5
    client = _FakeOAClient(
        [{"_body": "Full body. " * 40, "legacyDocumentCodeIdentifier": ["CTFR"]}],
        section_text=section,
    )
    monkeypatch.setattr(mod, "_get_oa_text_client", lambda: client)

    result = await tools["PFW_get_oa_text"]("15992176", section="103")

    assert result["section_returned"] == "103"
    assert "section_note" not in result


# ---------------------------------------------------------------------------
# PFW_get_oa_text: the text cursor
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_oa_text_windows_a_long_office_action(oa_tools, monkeypatch):
    tools, mod = oa_tools
    body = "z" * 50_000
    client = _FakeOAClient([{"_body": body, "legacyDocumentCodeIdentifier": ["CTNF"]}])
    monkeypatch.setattr(mod, "_get_oa_text_client", lambda: client)

    result = await tools["PFW_get_oa_text"]("15992176", max_chars=10_000)

    assert result["text_total_chars"] == 50_000
    assert result["text_returned_chars"] == 10_000
    assert result["text_length_chars"] == 10_000  # legacy alias of RETURNED
    window = result[WINDOW_KEY]
    assert window["total"] == 50_000
    assert window["has_more"] is True
    assert window["next_offset"] == 10_000
    assert result["truncated"] is True

    # The cursor walks the rest.
    rest = await tools["PFW_get_oa_text"](
        "15992176", char_offset=window["next_offset"], max_chars=10_000
    )
    assert rest[WINDOW_KEY]["offset"] == 10_000


@pytest.mark.asyncio
async def test_oa_text_short_document_gets_no_window(oa_tools, monkeypatch):
    tools, mod = oa_tools
    client = _FakeOAClient([{"_body": "short body", "legacyDocumentCodeIdentifier": ["NOA"]}])
    monkeypatch.setattr(mod, "_get_oa_text_client", lambda: client)

    result = await tools["PFW_get_oa_text"]("15992176")

    assert WINDOW_KEY not in result
    assert BOUNDS_KEY not in result
    assert result["text_total_chars"] == result["text_returned_chars"] == 10


@pytest.mark.asyncio
async def test_oa_text_splits_the_budget_across_office_actions(oa_tools, monkeypatch):
    """One 70K-char final rejection used to be able to crowd out the nine
    office actions after it."""
    tools, mod = oa_tools
    docs = [
        {"_body": "z" * 30_000, "legacyDocumentCodeIdentifier": ["CTNF"]}
        for _ in range(5)
    ]
    client = _FakeOAClient(docs)
    monkeypatch.setattr(mod, "_get_oa_text_client", lambda: client)

    result = await tools["PFW_get_oa_text"]("15992176", latest_only=False, max_chars=50_000)

    assert result["per_document_char_budget"] == 10_000
    assert result["rows_applied"] == mod.OA_TEXT_ROWS_ALL
    for entry in result["office_actions"]:
        assert entry["text_total_chars"] == 30_000
        assert entry["text_returned_chars"] == 10_000
        assert entry[WINDOW_KEY]["has_more"] is True


@pytest.mark.asyncio
async def test_oa_text_rejects_bad_cursor_params(oa_tools):
    tools, _ = oa_tools

    assert (await tools["PFW_get_oa_text"]("1", char_offset=-1))["error"]
    assert (await tools["PFW_get_oa_text"]("1", max_chars=0))["error"]


# ---------------------------------------------------------------------------
# (h) PFW_get_oa_rejections: rows went to Solr with no clamp at all
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [0, -1, 101, 100_000])
async def test_oa_rejections_rejects_out_of_range_rows(oa_tools, monkeypatch, rows):
    tools, mod = oa_tools
    client = _FakeOAClient([])
    monkeypatch.setattr(mod, "_get_oa_rejection_client", lambda: client)

    result = await tools["PFW_get_oa_rejections"]("15992176", rows=rows)

    assert result.get("error")
    assert client.calls == []  # nothing reached USPTO


@pytest.mark.asyncio
async def test_oa_rejections_surfaces_the_rows_applied(oa_tools, monkeypatch):
    tools, mod = oa_tools
    docs = [{"hasRej103": 1, "submissionDate": "2020-01-01"} for _ in range(10)]
    client = _FakeOAClient(docs, num_found=42)
    monkeypatch.setattr(mod, "_get_oa_rejection_client", lambda: client)

    result = await tools["PFW_get_oa_rejections"]("15992176", rows=10)

    assert client.calls[0]["rows"] == 10
    assert result["rows_requested"] == 10
    assert result["rows_applied"] == 10
    assert result["showing"] == 10
    assert result["num_found"] == 42
    assert result["has_more"] is True


# ---------------------------------------------------------------------------
# PFW_get_document_content_with_ocr: the text cursor
# ---------------------------------------------------------------------------

class _FakeExtractionClient:
    def __init__(self, content, extra=None):
        self._content = content
        self._extra = extra or {}

    async def extract_document_content_hybrid(self, app_number, document_identifier,
                                              auto_optimize, progress_cb=None,
                                              page_from=1, page_to=None):
        return {
            "success": True,
            "application_number": app_number,
            "document_identifier": document_identifier,
            "extracted_content": self._content,
            "extraction_method": "PyPDF2",
            **self._extra,
        }


@pytest.mark.asyncio
async def test_ocr_content_cursor_pages_long_text(document_tools, monkeypatch):
    tools, mod = document_tools
    content = "\n\n".join(f"=== PAGE {i} ===\n{'word ' * 400}" for i in range(1, 21))
    monkeypatch.setattr(mod, "_client", lambda: _FakeExtractionClient(content))

    result = await tools["PFW_get_document_content_with_ocr"](
        "17896175", "ABC123", max_chars=6_000
    )

    window = result[WINDOW_KEY]
    # Page-unit: the window edge lands exactly on a page marker, so a page is
    # never split mid-way.
    assert window["unit"] == "page"
    assert window["has_more"] is True
    assert content[window["next_offset"]:].startswith("=== PAGE ")
    assert result["content_total_chars"] == len(content)
    assert result["content_returned_chars"] == window["returned"]
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_ocr_content_cursor_walks_the_whole_document(document_tools, monkeypatch):
    tools, mod = document_tools
    content = "\n\n".join(f"=== PAGE {i} ===\n{'word ' * 400}" for i in range(1, 11))
    monkeypatch.setattr(mod, "_client", lambda: _FakeExtractionClient(content))

    seen, offset, guard = [], 0, 0
    while True:
        guard += 1
        assert guard < 50
        result = await tools["PFW_get_document_content_with_ocr"](
            "17896175", "ABC123", char_offset=offset, max_chars=6_000
        )
        seen.append(result["extracted_content"])
        window = result.get(WINDOW_KEY)
        if not window or not window["has_more"]:
            break
        offset = window["next_offset"]

    assert "".join(seen) == content  # nothing lost, nothing duplicated


@pytest.mark.asyncio
async def test_ocr_content_short_document_is_untouched(document_tools, monkeypatch):
    tools, mod = document_tools
    monkeypatch.setattr(mod, "_client", lambda: _FakeExtractionClient("a short document"))

    result = await tools["PFW_get_document_content_with_ocr"]("17896175", "ABC123")

    assert WINDOW_KEY not in result
    assert BOUNDS_KEY not in result
    assert result["extracted_content"] == "a short document"


@pytest.mark.asyncio
async def test_ocr_content_reports_a_page_cap_and_a_window_separately(document_tools, monkeypatch):
    """They mean different things: a page cap is text never extracted (not
    reachable by paging), a window is text not yet read."""
    tools, mod = document_tools
    content = "z" * 200_000
    monkeypatch.setattr(mod, "_client", lambda: _FakeExtractionClient(
        content,
        extra={"pages_truncated": 250, "truncated": True,
               "truncation_note": "Document has 300 pages; the first 50 were OCR'd."},
    ))

    result = await tools["PFW_get_document_content_with_ocr"](
        "17896175", "ABC123", max_chars=10_000
    )

    assert result["pages_truncated"] == 250
    assert "300 pages" in result["truncation_note"]          # the page cap
    assert "char_offset" in result["truncation_note"]        # ...and the window
    assert result[WINDOW_KEY]["has_more"] is True


@pytest.mark.asyncio
async def test_ocr_content_rejects_bad_cursor_params(document_tools):
    tools, _ = document_tools

    assert (await tools["PFW_get_document_content_with_ocr"]("1", "D", char_offset=-1))["error"]
    assert (await tools["PFW_get_document_content_with_ocr"]("1", "D", max_chars=0))["error"]


# ---------------------------------------------------------------------------
# One-liner: include_raw_xml defaults to False
# ---------------------------------------------------------------------------

def test_include_raw_xml_defaults_to_false(document_tools):
    """It defaulted True "for backward compatibility", putting a ~50K-token raw
    XML blob into every response by default."""
    import inspect

    tools, _ = document_tools
    signature = inspect.signature(tools["PFW_get_patent_or_application_xml"])

    assert signature.parameters["include_raw_xml"].default is False


@pytest.mark.asyncio
async def test_xml_tool_passes_the_flag_through(document_tools, monkeypatch):
    tools, mod = document_tools
    captured = {}

    class _FakeXmlClient:
        async def get_patent_or_application_xml(self, identifier, content_type,
                                                include_fields, include_raw_xml):
            captured["include_raw_xml"] = include_raw_xml
            return {"success": True, "identifier_used": identifier,
                    "application_number": identifier, "xml_type": "PTGRXML",
                    "structured_content": {"abstract": "x"}}

    monkeypatch.setattr(mod, "_client", lambda: _FakeXmlClient())

    await tools["PFW_get_patent_or_application_xml"]("7971071")
    assert captured["include_raw_xml"] is False

    await tools["PFW_get_patent_or_application_xml"]("7971071", include_raw_xml=True)
    assert captured["include_raw_xml"] is True
