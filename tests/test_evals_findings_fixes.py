"""Fixes for the evals-harness findings of 2026-08-31 (open items 15-17).

* O-A  a sliced OCR window emitted `=== PAGE 1 ===` for document page 51 on
       the Mistral branch, while `page_window` in the same response said 51-53
* #1   the search `limit` ceiling was described everywhere as a CLAMP and
       enforced at the tool layer as a 400
* the DOCLING_MAX_PAGES refusal told the reader to set MISTRAL_API_KEY even on
  a deployment that already runs Docling

Hermetic: no network, no OCR spend, no USPTO key beyond a placeholder.
"""

import pytest

from patent_filewrapper_mcp.api.enhanced_client import (
    EnhancedPatentClient,
    _extraction_failure_advice,
)
from patent_filewrapper_mcp.services.ocr_service import OCRService
from patent_filewrapper_mcp.tools.search_tools import _clamp_search_limit


# ===========================================================================
# Item: sliced page windows must number pages from the DOCUMENT, not the slice
# ===========================================================================

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
def client(monkeypatch):
    monkeypatch.setenv("USPTO_API_KEY", "test-uspto-key-0123456789")
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    c = EnhancedPatentClient()
    c.mistral_api_key = None
    return c


@pytest.fixture
def fake_pypdf(monkeypatch):
    import PyPDF2

    monkeypatch.setattr(PyPDF2, "PdfReader", _FakeReader)
    return _FakeReader


# --- branch 1: PyPDF2 (already offset; pinned so it stays that way) --------

@pytest.mark.asyncio
async def test_pypdf_branch_numbers_a_window_from_the_document(client, fake_pypdf):
    """page_from=51 slices the PDF, so the reader sees 3 pages — the headers
    must still say 51, 52, 53."""
    fake_pypdf.pages_to_serve = [_FakePage(i) for i in range(1, 4)]
    status = {}

    text = await client.extract_with_pypdf2(b"%PDF-", status, page_offset=50)

    assert text.startswith("=== PAGE 51 ===")
    assert "=== PAGE 52 ===" in text and "=== PAGE 53 ===" in text
    assert "=== PAGE 1 ===" not in text
    assert status["page_offset"] == 50


# --- branch 2: Mistral OCR (the bug) --------------------------------------

class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeMistralHTTP:
    """Stands in for httpx.AsyncClient against api.mistral.ai. ZERO spend.

    Mistral indexes the pages of the payload it was GIVEN, so a sliced window
    always comes back as index 0, 1, 2 — which is precisely why the offset has
    to be applied on this side.
    """

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
        if url.endswith("/files"):
            return _FakeResponse({"id": "file-abc"})
        return _FakeResponse({
            "model": "mistral-ocr-latest",
            "usage_info": {"pages_processed": 3},
            "pages": [
                {"index": 0, "markdown": "first page of the window"},
                {"index": 1, "markdown": "second page of the window"},
                {"index": 2, "markdown": "third page of the window"},
            ],
        })


@pytest.fixture
def mistral_service(monkeypatch):
    monkeypatch.setattr("httpx.AsyncClient", _FakeMistralHTTP)
    return OCRService(api_key="test-mistral-key-0123456789")


@pytest.mark.asyncio
async def test_mistral_branch_numbers_a_window_from_the_document(mistral_service):
    """The reported defect: page_from=51 emitted `=== PAGE 1 ===` while
    `page_window` said 51-53."""
    result = await mistral_service.extract_document_content(
        b"%PDF-", page_count=3, app_number="11752072",
        document_identifier="DOC1", page_offset=50,
    )

    assert result["success"] is True
    content = result["extracted_content"]
    assert content.startswith("=== PAGE 51 ===")
    assert "=== PAGE 52 ===" in content and "=== PAGE 53 ===" in content
    assert "=== PAGE 1 ===" not in content
    assert result["page_offset"] == 50


@pytest.mark.asyncio
async def test_mistral_branch_unwindowed_still_starts_at_page_one(mistral_service):
    result = await mistral_service.extract_document_content(
        b"%PDF-", page_count=3, app_number="11752072", document_identifier="DOC1",
    )
    assert result["extracted_content"].startswith("=== PAGE 1 ===")
    assert result["page_offset"] == 0


@pytest.mark.asyncio
async def test_mistral_tier_forwards_the_page_offset(client, monkeypatch):
    seen = {}

    async def fake_extract(pdf_content, page_count, app_number, document_identifier,
                           page_offset=0):
        seen["page_offset"] = page_offset
        return {"success": True, "extracted_content": "=== PAGE 51 ===\ntext",
                "pages_processed": 3}

    client.mistral_api_key = "test-mistral-key"
    monkeypatch.setattr(client.ocr_service, "extract_document_content", fake_extract)

    update = await client._try_mistral_tier(
        b"%PDF-", 3, "11752072", "DOC1", auto_optimize=True, page_offset=50
    )

    assert update is not None
    assert seen["page_offset"] == 50


@pytest.mark.asyncio
async def test_pdf_tiers_hand_the_page_offset_to_the_mistral_tier(client, monkeypatch):
    """The offset is decided in extract_document_content_hybrid (where the PDF
    is sliced) and has to survive the trip through _run_pdf_tiers."""
    seen = {}

    async def fake_mistral_tier(pdf_content, page_count, app_number, document_identifier,
                                auto_optimize, progress_cb=None, page_offset=0):
        seen["page_offset"] = page_offset
        return {"extracted_content": "x", "extraction_method": "Mistral OCR (direct)"}

    monkeypatch.setattr(client, "_try_mistral_tier", fake_mistral_tier)

    await client._run_pdf_tiers(
        {}, {"pageTotalQuantity": 3}, b"%PDF-", "11752072", "DOC1",
        auto_optimize=False, page_offset=50, window_total_pages=120,
    )

    assert seen["page_offset"] == 50


# ===========================================================================
# Item: the search limit ceiling CLAMPS, and says so
# ===========================================================================

def test_clamp_helper_is_a_no_op_below_the_ceiling():
    applied, marker = _clamp_search_limit(50)
    assert applied == 50
    assert marker is None  # absent on a no-op, like _bounds and _window


def test_clamp_helper_clamps_and_explains():
    applied, marker = _clamp_search_limit(500)
    assert applied == EnhancedPatentClient.MAX_SEARCH_LIMIT
    assert marker["limit_clamped"]["requested"] == 500
    assert marker["limit_clamped"]["applied"] == EnhancedPatentClient.MAX_SEARCH_LIMIT
    assert "CLAMPED" in marker["limit_clamped"]["note"]


class _CaptureMCP:
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


class _FakeSearchClient:
    """Mirrors what EnhancedPatentClient.search_applications returns, including
    the wire clamp it has always applied."""

    def __init__(self):
        self.limits_seen = []

    async def search_applications(self, query, limit=10, offset=0, fields=None):
        self.limits_seen.append(limit)
        applied = min(limit, EnhancedPatentClient.MAX_SEARCH_LIMIT)
        return {
            "success": True,
            "count": 0,
            "total": 0,
            "query": query,
            "applications": [],
            "limit": applied,
            "offset": offset,
            "paging": {
                "limit_requested": limit,
                "limit_applied": applied,
                "offset": offset,
                "returned": 0,
                "total": 0,
                "has_more": False,
                "next_offset": None,
            },
        }

    async def search_inventor(self, name, strategy, limit, fields):
        self.limits_seen.append(limit)
        return {"success": True, "unique_applications": [], "total_unique_applications": 0}

    async def enhance_search_results_with_associated_docs(self, results):
        return results


@pytest.fixture
def search_tools(monkeypatch):
    monkeypatch.setenv("USPTO_API_KEY", "test-uspto-key-0123456789")
    from patent_filewrapper_mcp.tools import search_tools as mod

    fake = _CaptureMCP()
    mod.register(fake)
    client = _FakeSearchClient()
    monkeypatch.setattr(mod, "_client", lambda: client)
    return fake.tools, client


@pytest.mark.parametrize("tool_name, kwargs", [
    ("PFW_search_applications", {"query": "machine learning"}),
    ("PFW_search_applications_minimal", {"query": "machine learning"}),
    ("PFW_search_applications_balanced", {"query": "machine learning"}),
    ("PFW_search_inventor", {"name": "Smith"}),
    ("PFW_search_inventor_minimal", {"name": "Smith"}),
    ("PFW_search_inventor_balanced", {"name": "Smith"}),
])
@pytest.mark.asyncio
async def test_over_ceiling_limit_is_clamped_not_rejected(search_tools, tool_name, kwargs):
    """limit=500 used to be a 400 with no `paging` block, which cost an agent a
    turn for reading its own tool description."""
    tools, client = search_tools

    result = await tools[tool_name](limit=500, **kwargs)

    assert result.get("success") is True, result
    assert "error" not in result
    assert result["limit_clamped"]["requested"] == 500
    assert result["limit_clamped"]["applied"] == EnhancedPatentClient.MAX_SEARCH_LIMIT
    # Nothing above the ceiling ever reaches the wire.
    assert all(seen <= EnhancedPatentClient.MAX_SEARCH_LIMIT for seen in client.limits_seen)
    # ... and the paging block still reports what the CALLER asked for.
    if "paging" in result:
        assert result["paging"]["limit_requested"] == 500
        assert result["paging"]["limit_applied"] == EnhancedPatentClient.MAX_SEARCH_LIMIT


@pytest.mark.asyncio
async def test_a_limit_inside_the_ceiling_carries_no_clamp_marker(search_tools):
    tools, _ = search_tools
    result = await tools["PFW_search_applications_minimal"](query="x", limit=25)
    assert result.get("success") is True
    assert "limit_clamped" not in result


@pytest.mark.parametrize("tool_name, kwargs", [
    ("PFW_search_applications_minimal", {"query": "x"}),
    ("PFW_search_inventor_minimal", {"name": "Smith"}),
])
@pytest.mark.asyncio
async def test_a_limit_below_one_is_still_a_400(search_tools, tool_name, kwargs):
    """There is no honest value to clamp 0 to."""
    tools, _ = search_tools
    result = await tools[tool_name](limit=0, **kwargs)
    assert result.get("success") is False
    assert result["status_code"] == 400


# ===========================================================================
# Item: what to DO when Docling refuses a document for its page count
# ===========================================================================

class _FakeDocling:
    def __init__(self, available=True, within_limit=True, max_pages=25):
        self._available = available
        self._within = within_limit
        self.max_pages = max_pages

    def is_available(self):
        return self._available

    def within_page_limit(self, page_count):
        return self._within


def test_page_cap_advice_names_the_page_window_and_the_env_var():
    advice = _extraction_failure_advice(
        mistral_key_present=False,
        docling_client=_FakeDocling(within_limit=False, max_pages=25),
        page_count=60,
    )
    assert "page_from" in advice and "page_to" in advice
    assert "DOCLING_MAX_PAGES" in advice
    # The deployment already runs OCR; telling it to buy a metered vendor is
    # the wrong advice and was the defect.
    assert "MISTRAL_API_KEY" not in advice


def test_configured_docling_that_simply_failed_does_not_advertise_mistral():
    advice = _extraction_failure_advice(
        mistral_key_present=False, docling_client=_FakeDocling(), page_count=5,
    )
    assert "MISTRAL_API_KEY" not in advice
    assert "page_from" in advice


def test_unconfigured_deployment_still_gets_both_options():
    advice = _extraction_failure_advice(
        mistral_key_present=False,
        docling_client=_FakeDocling(available=False),
        page_count=5,
    )
    assert "DOCLING_SERVE_URL" in advice
    assert "MISTRAL_API_KEY" in advice


def test_a_deployment_with_a_mistral_key_is_not_told_to_add_one():
    advice = _extraction_failure_advice(
        mistral_key_present=True,
        docling_client=_FakeDocling(available=False),
        page_count=5,
    )
    assert "MISTRAL_API_KEY" not in advice
    assert "DOCLING_SERVE_URL" in advice


@pytest.mark.asyncio
async def test_terminal_envelope_carries_the_conditional_advice(client, monkeypatch):
    """The all-tiers-failed envelope is where a reader actually meets this
    message."""
    async def none_tier(*args, **kwargs):
        return None

    monkeypatch.setattr(client, "_try_pypdf2_tier", none_tier)
    monkeypatch.setattr(client, "_try_docling_tier", none_tier)
    # The injection seam is the INSTANCE attribute now, not the module global:
    # DoclingClient is constructed once in __init__ so the "is it configured /
    # within the page limit" decision and the actual call cannot read the
    # environment twice and disagree (audit design-pattern F-4).
    monkeypatch.setattr(
        client, "docling_client", _FakeDocling(within_limit=False, max_pages=25)
    )

    result = await client._run_pdf_tiers(
        {}, {"pageTotalQuantity": 60}, b"%PDF-", "11752072", "DOC1", auto_optimize=True
    )

    assert result["extraction_method"] == "failed"
    assert result["docling_page_limit_exceeded"] is True
    assert "DOCLING_MAX_PAGES" in result["suggestion"]
    assert "page_from" in result["suggestion"]
    assert "MISTRAL_API_KEY" not in result["suggestion"]
    assert "MISTRAL_API_KEY" not in result["llm_guidance"]["recommended_solution"]
