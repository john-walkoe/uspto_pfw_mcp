"""One end-to-end deadline per PFW_get_document_content_with_ocr call.

Reverse proxies and CDNs commonly cut a proxied request at about 100 s.
Mistral had no retry at all and each step budgeted itself; now one Deadline
(default 85 s, PFW_CONTENT_DEADLINE_SECONDS) is created when the tool starts,
every Mistral attempt is capped at what is left, a 429/5xx retry is taken only
when its backoff leaves room for another attempt, and Docling runs only on the
rest. A spent budget answers error "Deadline exceeded".

Time is faked: the Deadline takes an injectable clock, and asyncio.sleep is
patched to advance that clock instead of waiting. Mistral is an httpx
MockTransport. No network, no spend.
"""

import asyncio

import httpx
import pytest

from patent_filewrapper_mcp.services.ocr_service import OCRService
from patent_filewrapper_mcp.util import deadline as deadline_module
from patent_filewrapper_mcp.util.deadline import (
    DEADLINE_ERROR,
    Deadline,
    DeadlineExceeded,
    current_deadline,
    deadline_scope,
    run_within,
)


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)
        fake.t += seconds

    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    fake.slept = slept
    return fake


@pytest.fixture
def service():
    return OCRService(api_key="k" * 40)


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestDeadline:
    def test_remaining_counts_down_and_never_goes_negative(self, clock):
        d = Deadline(85, clock=clock)
        clock.t += 80
        assert d.remaining() == pytest.approx(5)
        clock.t += 10
        assert d.remaining() == 0.0 and d.expired()

    @pytest.mark.parametrize("raw, expected", [
        ("", 85.0), ("60", 60.0), ("junk", 85.0), ("0", 85.0), ("-5", 85.0)])
    def test_env(self, monkeypatch, raw, expected):
        monkeypatch.setenv("PFW_CONTENT_DEADLINE_SECONDS", raw)
        assert deadline_module.content_deadline_seconds() == expected

    def test_the_scope_is_per_call_and_resets(self, clock):
        assert current_deadline() is None
        d = Deadline(10, clock=clock)
        with deadline_scope(d):
            assert current_deadline() is d
        assert current_deadline() is None

    async def test_run_within_on_a_spent_deadline_never_starts_the_step(self, clock):
        started = []

        async def step():
            started.append(1)

        spent = Deadline(1, clock=clock)
        clock.t += 2
        with pytest.raises(DeadlineExceeded):
            await run_within(spent, step())
        assert started == []


class TestMistralRetryInsideTheDeadline:
    async def test_a_429_is_retried_while_there_is_room(self, service, clock):
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(429) if len(calls) == 1 else httpx.Response(200, json={})

        async with _client(handler) as client:
            response = await service._post_with_retry(
                client, "https://x/ocr", deadline=Deadline(85, clock=clock))

        assert response.status_code == 200
        assert len(calls) == 2

    async def test_a_5xx_retry_that_would_not_fit_is_not_taken(self, service, clock):
        """Budget 4 s: the first backoff (~1.1-1.5 s) leaves room for one more
        attempt; the second (~2.1-2.5 s) would not, so the last status comes
        back after two attempts instead of three."""
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(503)

        async with _client(handler) as client:
            response = await service._post_with_retry(
                client, "https://x/ocr", deadline=Deadline(4.0, clock=clock))

        assert response.status_code == 503
        assert len(calls) == 2
        assert len(clock.slept) == 1

    async def test_without_room_a_transport_failure_becomes_deadline_exceeded(
            self, service, clock):
        def handler(request):
            clock.t += 3.0  # the failed attempt itself used most of the budget
            raise httpx.ConnectError("reset")

        async with _client(handler) as client:
            with pytest.raises(DeadlineExceeded):
                await service._post_with_retry(
                    client, "https://x/files", deadline=Deadline(4.0, clock=clock))

    async def test_no_attempt_is_started_on_a_spent_deadline(self, service, clock):
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(200, json={})

        spent = Deadline(85, clock=clock)
        clock.t += 84.5
        async with _client(handler) as client:
            with pytest.raises(DeadlineExceeded):
                await service._post_with_retry(client, "https://x/ocr", deadline=spent)

        assert calls == []

    async def test_a_hung_attempt_is_cut_at_the_deadline(self, service, monkeypatch):
        """Real (tiny) time here: wait_for has to fire on the event loop."""
        monkeypatch.setattr(OCRService, "_MIN_ATTEMPT_SECONDS", 0.01)

        class Hang(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                await asyncio.Event().wait()

        async with httpx.AsyncClient(transport=Hang()) as client:
            with pytest.raises(DeadlineExceeded):
                await service._post_with_retry(
                    client, "https://x/ocr", deadline=Deadline(0.2))

    async def test_without_a_deadline_the_attempt_cap_holds(self, service, clock):
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(503)

        async with _client(handler) as client:
            response = await service._post_with_retry(client, "https://x/ocr")

        assert response.status_code == 503
        assert len(calls) == service._RETRY_ATTEMPTS

    async def test_a_4xx_other_than_429_is_not_retried(self, service, clock):
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(401)

        async with _client(handler) as client:
            response = await service._post_with_retry(client, "https://x/ocr")

        assert response.status_code == 401
        assert calls == [1]


def _route_mistral(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: real(
        transport=httpx.MockTransport(handler), **{x: y for x, y in k.items() if x != "transport"}))


class TestOcrEndToEnd:
    async def test_a_spent_deadline_is_its_own_error(self, service, clock, monkeypatch):
        _route_mistral(monkeypatch, lambda r: httpx.Response(200, json={"id": "f"}))
        spent = Deadline(85, clock=clock)
        clock.t += 85

        result = await service.extract_document_content(
            b"%PDF-1.4", 3, "16000000", "DOC1", deadline=spent)

        assert result["success"] is False
        assert result["error"] == DEADLINE_ERROR
        assert "$" not in result["message"]

    async def test_the_service_reads_the_running_calls_deadline(self, service, clock, monkeypatch):
        _route_mistral(monkeypatch, lambda r: httpx.Response(200, json={"id": "f"}))
        spent = Deadline(85, clock=clock)
        clock.t += 85

        with deadline_scope(spent):
            result = await service.extract_document_content(b"%PDF-1.4", 3, "16000000", "DOC1")

        assert result["error"] == DEADLINE_ERROR

    async def test_a_429_upload_then_success_completes(self, service, clock, monkeypatch):
        uploads = []

        def handler(request):
            if request.method == "DELETE":
                return httpx.Response(200, json={})
            if request.url.path.endswith("/files"):
                uploads.append(1)
                return httpx.Response(429) if len(uploads) == 1 else httpx.Response(200, json={"id": "f"})
            return httpx.Response(200, json={"pages": [{"index": 0, "markdown": "ok"}],
                                             "usage_info": {"pages_processed": 1}})

        _route_mistral(monkeypatch, handler)

        with deadline_scope(Deadline(85, clock=clock)):
            result = await service.extract_document_content(b"%PDF-1.4", 1, "16000000", "DOC1")

        assert result["success"] is True
        assert len(uploads) == 2


class _FakeDocling:
    max_pages = 20

    def __init__(self, available=True):
        self._available = available
        self.called = []

    def is_available(self):
        return self._available

    def within_page_limit(self, n):
        return True


@pytest.fixture
def pfw_client():
    from patent_filewrapper_mcp.api.enhanced_client import EnhancedPatentClient

    return EnhancedPatentClient(api_key="test-key-not-a-real-credential")


class TestContentPath:
    async def test_docling_is_skipped_when_the_budget_is_nearly_spent(
            self, pfw_client, clock, monkeypatch):
        called = []

        async def extract(*a, **k):
            called.append(1)
            return "text " * 100

        monkeypatch.setattr(pfw_client, "extract_with_docling", extract)
        nearly_spent = Deadline(85, clock=clock)
        clock.t += 83

        with deadline_scope(nearly_spent):
            with pytest.raises(DeadlineExceeded):
                await pfw_client._try_docling_tier(b"%PDF", 3, "DOC1", _FakeDocling())

        assert called == []

    async def test_a_mistral_deadline_ends_in_deadline_exceeded_not_scanned_image(
            self, pfw_client, clock, monkeypatch):
        pfw_client.mistral_api_key = "k" * 40
        pfw_client.docling_client = _FakeDocling(available=False)

        async def none_tier(*a, **k):
            return None

        async def deadline_ocr(*a, **k):
            return {"success": False, "error": DEADLINE_ERROR, "message": "m"}

        monkeypatch.setattr(pfw_client, "_try_pypdf2_tier", none_tier)
        monkeypatch.setattr(pfw_client.ocr_service, "extract_document_content", deadline_ocr)

        result = await pfw_client._run_pdf_tiers(
            {"success": True}, {"pageTotalQuantity": 3}, b"%PDF-1.4", "16000000", "DOC1", True)

        assert result["success"] is False
        assert result["error"] == DEADLINE_ERROR
        assert result["extraction_method"] == "deadline_exceeded"

    async def test_a_spent_download_answers_deadline_exceeded(self, pfw_client, clock, monkeypatch):
        async def fake_resolve(app_number, document_identifier, request_id):
            return {"documentIdentifier": "DOC1", "documentCode": "CTNF"}, {
                "pageTotalQuantity": 3, "downloadUrl": "https://api.uspto.gov/x.pdf"}

        async def slow_download(url):
            clock.t += 100
            raise AssertionError("must not run on a spent deadline")

        monkeypatch.setattr(pfw_client, "_resolve_document_for_extraction", fake_resolve)
        monkeypatch.setattr(pfw_client, "_download_once", slow_download)
        spent = Deadline(85, clock=clock)
        clock.t += 85

        with deadline_scope(spent):
            result = await pfw_client.extract_document_content_hybrid(
                "16000000", "DOC1", auto_optimize=False)

        assert result["error"] == DEADLINE_ERROR
        assert result["document_identifier"] == "DOC1"

    async def test_the_tool_runs_inside_one_deadline(self, monkeypatch):
        from patent_filewrapper_mcp import main
        from patent_filewrapper_mcp.tools import document_tools

        monkeypatch.setenv("PFW_CONTENT_DEADLINE_SECONDS", "60")
        seen = {}

        class _Client:
            async def extract_document_content_hybrid(self, *a, **k):
                seen["deadline"] = current_deadline()
                return {"success": True, "extracted_content": "text"}

        monkeypatch.setattr(document_tools, "_client", lambda: _Client())

        await main.pfw_get_document_content(app_number="16000000", document_identifier="DOC1")

        assert isinstance(seen["deadline"], Deadline)
        assert seen["deadline"].seconds == 60.0
        assert current_deadline() is None  # reset after the call
