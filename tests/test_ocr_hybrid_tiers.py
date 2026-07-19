"""Tier tests for the refactored OCR waterfall (audits: complexity 8/10 item,
F1 OCRService delegation, F43 untested Docling/terminal branches, F48/F49)."""

import pytest

from patent_filewrapper_mcp.api import enhanced_client as ec_mod
from patent_filewrapper_mcp.api.enhanced_client import EnhancedPatentClient

GOOD_TEXT = (
    "This is a perfectly reasonable extracted patent document text with many "
    "normal english words that passes the is_good_extraction heuristics easily. "
) * 5


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("USPTO_API_KEY", "test-uspto-key-0123456789")
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    c = EnhancedPatentClient()
    c.mistral_api_key = None  # ensure the Mistral tier is skipped by default
    return c


class _FakeDocling:
    def __init__(self, available=True, within_limit=True):
        self._available = available
        self._within = within_limit
        self.max_pages = 40

    def is_available(self):
        return self._available

    def within_page_limit(self, page_count):
        return self._within


@pytest.mark.asyncio
async def test_docling_tier_success(client, monkeypatch):
    async def fake_extract(pdf_content, document_identifier):
        return GOOD_TEXT

    monkeypatch.setattr(client, "extract_with_docling", fake_extract)
    update = await client._try_docling_tier(b"%PDF-", 5, "DOC1", _FakeDocling())
    assert update is not None
    assert update["extraction_method"] == "Docling OCR"
    assert update["processing_cost_usd"] == 0.0
    assert update["extracted_content"] == GOOD_TEXT


@pytest.mark.asyncio
async def test_docling_tier_unavailable_returns_none(client):
    assert await client._try_docling_tier(b"%PDF-", 5, "DOC1", _FakeDocling(available=False)) is None


@pytest.mark.asyncio
async def test_docling_tier_page_limit_returns_none(client):
    assert await client._try_docling_tier(b"%PDF-", 500, "DOC1", _FakeDocling(within_limit=False)) is None


@pytest.mark.asyncio
async def test_docling_tier_poor_text_returns_none(client, monkeypatch):
    async def fake_extract(pdf_content, document_identifier):
        return "@@@###"  # fails is_good_extraction

    monkeypatch.setattr(client, "extract_with_docling", fake_extract)
    assert await client._try_docling_tier(b"%PDF-", 5, "DOC1", _FakeDocling()) is None


@pytest.mark.asyncio
async def test_all_tiers_failed_terminal_result(client, monkeypatch):
    """No PyPDF2 text, no Mistral key, no Docling — the terminal branch must
    say so and carry actionable guidance (previously untested, F43)."""

    async def fake_fetch(app_number, document_identifier, request_id, progress_cb=None):
        return {"documentIdentifier": "DOC1", "documentCode": "CTNF"}, {"pageTotalQuantity": 3}, b"\x00garbage"

    async def none_tier(*args, **kwargs):
        return None

    monkeypatch.setattr(client, "_fetch_document_for_extraction", fake_fetch)
    monkeypatch.setattr(client, "_try_pypdf2_tier", none_tier)
    monkeypatch.setattr(ec_mod, "DoclingClient", lambda: _FakeDocling(available=False))

    result = await client.extract_document_content_hybrid("12345678", "DOC1")
    assert result["extraction_method"] == "failed"
    assert result["mistral_api_key_missing"] is True
    assert result["docling_not_configured"] is True
    assert "llm_guidance" in result


@pytest.mark.asyncio
async def test_download_failure_labeled_download_failed(client, monkeypatch):
    """A PDF download failure blocks every tier and must be labeled
    download_failed, not a generic extraction failure (audit F49)."""

    async def fake_get_documents(app_number):
        return {
            "documentBag": [{
                "documentIdentifier": "DOC1",
                "downloadOptionBag": [{
                    "mimeTypeIdentifier": "PDF",
                    "downloadUrl": "https://api.uspto.gov/doc.pdf",
                    "pageTotalQuantity": 3,
                }],
            }]
        }

    class _BoomClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            raise ec_mod.httpx.ConnectError("upstream down")

    monkeypatch.setattr(client, "get_documents", fake_get_documents)
    monkeypatch.setattr(ec_mod.httpx, "AsyncClient", _BoomClient)

    result = await client.extract_document_content_hybrid("12345678", "DOC1")
    assert result["success"] is False
    assert result["extraction_method"] == "download_failed"
    assert "download" in result["error"].lower()


def test_ocr_service_is_the_single_mistral_implementation(client):
    """F1: the client must delegate to OCRService — no second copy."""
    assert not hasattr(client, "extract_document_content_with_mistral")
    assert client.ocr_service.mistral_ocr_model == client.mistral_ocr_model
