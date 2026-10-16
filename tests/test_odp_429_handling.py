"""ODP 429 handling and the shared limiter's refusal on every PFW call site
(ODP rate-limit wave 2026-10-11, plan sections 2c, 2d, 4a and 4c.2 / 4c.3;
rewritten 2026-10-13 from the Wave 2 Part A tests, which encoded the 3.0 s
self-paced cap this rule replaced).

The rule (helpers.planned_429_wait): on a 429, note it on the shared key
cooldown, then wait max(5 s, Retry-After) and send ONCE more, only when that
wait is <= 10 s and fits the call's remaining budget; otherwise answer at
once with the rate-limit envelope carrying retry_after_seconds =
max(5, Retry-After). Never a second retry. The wait holds no shared slot.
The shared limiter's SharedLimiterTimeoutError is answered at once with the
`shared_uspto_limiter` envelope, no retry. The download proxy buffers the
PDF under the slot and releases it before serving, so a slow consumer never
holds the slot, and its limiter refusal is a 503 JSON with Retry-After: 5.

Covered here: the Office Action client (api/oa_base.py), the direct
XML/PDF downloads (EnhancedPatentClient._download_once) and the tools on
them, and the proxy (proxy/server.py::_open_upstream_pdf_stream).
USPTOTransport's own path is in tests/test_rate_limit_response.py.

No network: httpx is routed through a MockTransport and sleeps are recorded.
"""

import asyncio

import httpx
import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

import patent_filewrapper_mcp.shared.uspto_shared_rate_limiter as rate_limiter_module
from patent_filewrapper_mcp.api import enhanced_client as enhanced_client_module
from patent_filewrapper_mcp.api import oa_base as oa_base_module
from patent_filewrapper_mcp.api.helpers import (
    RATE_LIMIT_SOURCE_SHARED_LIMITER,
    RATE_LIMIT_SOURCE_UPSTREAM,
    RATE_LIMIT_WAIT_FLOOR_SECONDS,
    planned_429_wait,
    rate_limited_response,
    retry_after_from,
)
from patent_filewrapper_mcp.exceptions import UpstreamRateLimitedError
from patent_filewrapper_mcp.shared.uspto_shared_rate_limiter import SharedLimiterTimeoutError

_REAL_ASYNC_CLIENT = httpx.AsyncClient
_KEY = "test-key-not-a-real-credential"


@pytest.fixture(autouse=True)
def _no_limiter_singleton(monkeypatch):
    monkeypatch.setattr(rate_limiter_module, "_singleton", None)
    monkeypatch.setattr(rate_limiter_module, "_singleton_checked", False)
    monkeypatch.delenv("USPTO_SHARED_RATE_LIMIT_DIR", raising=False)
    monkeypatch.delenv("USPTO_OA_TIMEOUT", raising=False)
    monkeypatch.delenv("USPTO_OA_MAX_RETRIES", raising=False)
    yield


@pytest.fixture
def slept(monkeypatch):
    """Record the clients' sleeps instead of waiting them out."""
    waits = []

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return waits


@pytest.fixture
def noted(monkeypatch):
    """Record every note_429 the clients make on the shared key."""
    recorded = []
    monkeypatch.setattr(oa_base_module, "note_429", recorded.append)
    monkeypatch.setattr(enhanced_client_module, "note_429", recorded.append)
    return recorded


def _route(monkeypatch, handler):
    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _REAL_ASYNC_CLIENT(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def _sequence(*responses):
    """Serve the responses in order, repeating the last one."""
    calls = []

    def handler(request):
        calls.append(request)
        return responses[min(len(calls), len(responses)) - 1]

    handler.calls = calls
    return handler


def _429(retry_after=None):
    headers = {} if retry_after is None else {"Retry-After": str(retry_after)}
    return httpx.Response(429, text="slow down", headers=headers)


def _oa():
    from patent_filewrapper_mcp.api.office_action_client import OfficeActionClient

    return OfficeActionClient(api_key=_KEY)


def _client():
    from patent_filewrapper_mcp.api.enhanced_client import EnhancedPatentClient

    return EnhancedPatentClient(api_key=_KEY)


_OA_OK = httpx.Response(200, json={"count": 1, "officeActionDataBag": []})


# ---------------------------------------------------------------- the rule

class TestPlannedWait:
    @pytest.mark.parametrize("retry_after, expected", [(None, 5.0), (2, 5.0), (5, 5.0), (10, 10.0)])
    def test_waits_once_at_the_floor_or_the_header(self, retry_after, expected):
        assert planned_429_wait(retry_after, False, 30.0) == expected

    def test_a_header_above_the_absorb_ceiling_means_the_envelope(self):
        assert planned_429_wait(30, False, 60.0) is None
        assert planned_429_wait(10.5, False, 60.0) is None

    def test_a_second_429_is_never_retried(self):
        assert planned_429_wait(None, True, 60.0) is None

    def test_a_wait_outside_the_remaining_budget_means_the_envelope(self):
        assert planned_429_wait(None, False, 4.9) is None
        assert planned_429_wait(None, False, 5.0) == 5.0

    def test_retry_after_header_reading(self):
        assert retry_after_from(_429()) is None
        assert retry_after_from(_429(2)) == 2.0
        assert retry_after_from(_429("7.5")) == 7.5
        assert retry_after_from(_429("Wed, 21 Oct 2026 07:28:00 GMT")) is None
        assert retry_after_from(None) is None

    def test_the_envelope_never_names_a_wait_under_the_floor(self):
        assert rate_limited_response(retry_after_seconds=2)["retry_after_seconds"] == 5.0
        assert rate_limited_response(retry_after_seconds=30)["retry_after_seconds"] == 30.0
        assert rate_limited_response()["retry_after_seconds"] == RATE_LIMIT_WAIT_FLOOR_SECONDS
        shared = rate_limited_response(source=RATE_LIMIT_SOURCE_SHARED_LIMITER)
        assert shared["retry_after_seconds"] == 5.0
        assert shared["rate_limit_source"] == RATE_LIMIT_SOURCE_SHARED_LIMITER


# ---------------------------------------------------------------- OA client

class TestOfficeActionClient:
    @pytest.mark.parametrize("retry_after", [None, 2, 5])
    async def test_exactly_one_retry_after_at_least_five_seconds(self, monkeypatch, slept, noted, retry_after):
        handler = _sequence(_429(retry_after), _OA_OK)
        _route(monkeypatch, handler)

        result = await _oa().search_office_actions("1")

        assert result["count"] == 1
        assert len(handler.calls) == 2
        assert slept == [5.0]
        assert noted == [None if retry_after is None else float(retry_after)]

    async def test_retry_after_30_is_the_envelope_with_no_retry(self, monkeypatch, slept, noted):
        handler = _sequence(_429(30), _OA_OK)
        _route(monkeypatch, handler)

        with pytest.raises(UpstreamRateLimitedError) as caught:
            await _oa().search_office_actions("1")

        envelope = caught.value.envelope
        assert envelope["rate_limited"] is True
        assert envelope["rate_limit_source"] == RATE_LIMIT_SOURCE_UPSTREAM
        assert envelope["retry_after_seconds"] == 30.0
        assert len(handler.calls) == 1 and slept == []
        assert noted == [30.0]

    async def test_a_persistent_429_is_never_retried_twice(self, monkeypatch, slept, noted):
        handler = _sequence(_429(), _429(2), _429(2))
        _route(monkeypatch, handler)

        with pytest.raises(UpstreamRateLimitedError) as caught:
            await _oa().search_office_actions("1")

        assert len(handler.calls) == 2 and slept == [5.0]
        assert len(noted) == 2
        assert caught.value.envelope["retry_after_seconds"] == 5.0

    async def test_the_retry_does_not_spend_a_transient_retry(self, monkeypatch, slept, noted):
        """With USPTO_OA_MAX_RETRIES=0 there is no transient retry, but the
        one 429 retry still gets its second send."""
        monkeypatch.setenv("USPTO_OA_MAX_RETRIES", "0")
        handler = _sequence(_429(1), httpx.Response(200, json={"ok": 1}))
        _route(monkeypatch, handler)

        assert (await _oa().search_office_actions("1"))["ok"] == 1
        assert len(handler.calls) == 2 and slept == [5.0]

    async def test_the_wait_fits_the_calls_budget_or_it_is_the_envelope(self, monkeypatch, slept, noted):
        """A 5 s client timeout cannot fit the 5 s floor once any time has
        passed, so no wait is absorbed."""
        monkeypatch.setenv("USPTO_OA_TIMEOUT", "5")
        handler = _sequence(_429(), _OA_OK)
        _route(monkeypatch, handler)

        with pytest.raises(UpstreamRateLimitedError):
            await _oa().search_office_actions("1")

        assert len(handler.calls) == 1 and slept == []

    async def test_5xx_retries_are_unchanged(self, monkeypatch, slept, noted):
        handler = _sequence(httpx.Response(503), httpx.Response(200, json={"ok": 1}))
        _route(monkeypatch, handler)

        assert (await _oa().search_office_actions("1"))["ok"] == 1
        assert slept == [0.5]
        assert noted == []

    async def test_limiter_timeout_is_the_envelope_at_once(self, monkeypatch, slept, noted):
        handler = _sequence(_OA_OK)
        _route(monkeypatch, handler)
        client = _oa()

        async def refuse(*args, **kwargs):
            raise SharedLimiterTimeoutError("shared USPTO rate limiter: no request slot within 45s")

        monkeypatch.setattr(client, "_send_once", refuse)
        with pytest.raises(UpstreamRateLimitedError) as caught:
            await client.search_office_actions("1")

        envelope = caught.value.envelope
        assert handler.calls == [] and slept == [] and noted == []
        assert envelope["rate_limited"] is True
        assert envelope["rate_limit_source"] == RATE_LIMIT_SOURCE_SHARED_LIMITER
        assert envelope["retry_after_seconds"] == 5.0
        assert envelope["status_code"] == 429

    async def test_the_wait_holds_no_shared_slot(self, monkeypatch, tmp_path):
        monkeypatch.setenv("USPTO_SHARED_RATE_LIMIT_DIR", str(tmp_path))
        monkeypatch.setenv("USPTO_SHARED_RATE_LIMIT_RPS", "1000")
        # The real limiter is on, so the retry would wait out the 5 s
        # cooldown the 429 wrote; floor it at 0 for the test.
        monkeypatch.setattr(rate_limiter_module, "_COOLDOWN_FLOOR_SECONDS", 0.0)
        limiter = rate_limiter_module.get_shared_limiter()
        slot_free_during_wait = []
        real_sleep = asyncio.sleep

        async def fake_sleep(seconds):
            if seconds < 1.0:  # the limiter's own polls stay real
                await real_sleep(seconds)
                return
            fh = limiter._try_acquire_any_slot()
            slot_free_during_wait.append(fh is not None)
            if fh is not None:
                limiter._release_slot(fh)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)
        _route(monkeypatch, _sequence(_429(), _OA_OK))

        result = await _oa().search_office_actions("1")

        assert result["count"] == 1
        assert slot_free_during_wait == [True]
        # And the real limiter saw the 429: the cooldown is on the key.
        assert limiter._read_cooldown_until() > 0

    async def test_the_tool_returns_the_envelope(self, monkeypatch):
        from patent_filewrapper_mcp.tools import oa_tools

        envelope = {"success": False, "rate_limited": True, "retry_after_seconds": 5.0}
        result = oa_tools._oa_failure(UpstreamRateLimitedError(envelope), "16000000")

        assert result == {**envelope, "application_number": "16000000"}
        generic = oa_tools._oa_failure(ValueError("boom"), "16000000")
        assert generic == {"success": False, "error": "boom", "application_number": "16000000"}


# ---------------------------------------------------------------- downloads

class TestDirectDownloads:
    @pytest.mark.parametrize("retry_after", [None, 2, 5])
    async def test_exactly_one_retry_after_at_least_five_seconds(self, monkeypatch, slept, noted, retry_after):
        handler = _sequence(_429(retry_after), httpx.Response(200, content=b"<xml/>"))
        _route(monkeypatch, handler)

        response = await _client()._download_once("https://api.uspto.gov/x.xml")

        assert response.status_code == 200
        assert len(handler.calls) == 2 and slept == [5.0]
        assert noted == [None if retry_after is None else float(retry_after)]

    async def test_retry_after_30_raises_the_envelope_with_no_retry(self, monkeypatch, slept, noted):
        handler = _sequence(_429(30), httpx.Response(200, content=b"<xml/>"))
        _route(monkeypatch, handler)

        with pytest.raises(UpstreamRateLimitedError) as caught:
            await _client()._download_once("https://api.uspto.gov/x.pdf")

        assert caught.value.envelope["retry_after_seconds"] == 30.0
        assert caught.value.envelope["rate_limit_source"] == RATE_LIMIT_SOURCE_UPSTREAM
        assert len(handler.calls) == 1 and slept == []
        assert noted == [30.0]

    async def test_a_persistent_429_is_never_retried_twice(self, monkeypatch, slept, noted):
        handler = _sequence(_429(), _429(), _429())
        _route(monkeypatch, handler)

        with pytest.raises(UpstreamRateLimitedError) as caught:
            await _client()._download_once("https://api.uspto.gov/x.pdf")

        assert caught.value.envelope["rate_limited"] is True
        assert caught.value.envelope["retry_after_seconds"] == 5.0
        assert len(handler.calls) == 2 and slept == [5.0]
        assert len(noted) == 2

    async def test_the_wait_fits_the_download_timeout_or_it_is_the_envelope(self, monkeypatch, slept, noted):
        client = _client()
        client.download_timeout = 5.0
        handler = _sequence(_429(), httpx.Response(200, content=b"<xml/>"))
        _route(monkeypatch, handler)

        with pytest.raises(UpstreamRateLimitedError):
            await client._download_once("https://api.uspto.gov/x.pdf")

        assert len(handler.calls) == 1 and slept == []

    async def test_other_errors_still_come_back_as_the_response(self, monkeypatch, slept, noted):
        _route(monkeypatch, _sequence(httpx.Response(404)))

        response = await _client()._download_once("https://api.uspto.gov/x.pdf")

        assert response.status_code == 404
        assert noted == []

    async def test_limiter_timeout_raises_the_envelope_at_once(self, monkeypatch, slept, noted):
        handler = _sequence(httpx.Response(200, content=b"<xml/>"))
        _route(monkeypatch, handler)
        client = _client()

        async def refuse(url):
            raise SharedLimiterTimeoutError("no slot")

        monkeypatch.setattr(client, "_download_send", refuse)
        with pytest.raises(UpstreamRateLimitedError) as caught:
            await client._download_once("https://api.uspto.gov/x.pdf")

        assert handler.calls == [] and slept == [] and noted == []
        assert caught.value.envelope["rate_limit_source"] == RATE_LIMIT_SOURCE_SHARED_LIMITER
        assert caught.value.envelope["retry_after_seconds"] == 5.0

    async def test_the_extraction_path_returns_the_envelope(self, monkeypatch, slept):
        client = _client()

        async def fake_resolve(app_number, document_identifier, request_id):
            return {"documentIdentifier": "DOC1", "documentCode": "CTNF"}, {
                "pageTotalQuantity": 3, "downloadUrl": "https://api.uspto.gov/x.pdf"}

        monkeypatch.setattr(client, "_resolve_document_for_extraction", fake_resolve)
        _route(monkeypatch, _sequence(_429()))

        result = await client.extract_document_content_hybrid("16000000", "DOC1", auto_optimize=False)

        assert result["rate_limited"] is True
        assert result["extraction_method"] == "rate_limited"
        assert result["document_identifier"] == "DOC1"

    async def test_a_variant_429_is_not_followed_by_the_pdf_download(self, monkeypatch, slept):
        """2026-10-13: under the 2c rule the variant's 429 (no Retry-After)
        earns ONE retry of the same URL after 5 s; a second 429 is the
        envelope. The PDF fallback is still never fetched."""
        client = _client()
        target = {"documentIdentifier": "DOC1", "documentCode": "CTNF", "downloadOptionBag": [
            {"mimeTypeIdentifier": "MS_WORD", "downloadUrl": "https://api.uspto.gov/x.docx"},
            {"mimeTypeIdentifier": "PDF", "downloadUrl": "https://api.uspto.gov/x.pdf",
             "pageTotalQuantity": 3}]}

        async def fake_resolve(app_number, document_identifier, request_id):
            return target, target["downloadOptionBag"][1]

        monkeypatch.setattr(client, "_resolve_document_for_extraction", fake_resolve)
        handler = _sequence(_429())
        _route(monkeypatch, handler)

        result = await client.extract_document_content_hybrid("16000000", "DOC1")

        assert result["rate_limited"] is True
        assert [str(r.url) for r in handler.calls] == [
            "https://api.uspto.gov/x.docx", "https://api.uspto.gov/x.docx"]
        assert slept == [5.0]

    async def test_the_xml_tool_path_returns_the_envelope(self, monkeypatch, slept):
        client = _client()
        _route(monkeypatch, _sequence(_429(30)))

        with pytest.raises(UpstreamRateLimitedError):
            await client.fetch_xml_from_url("https://api.uspto.gov/x.xml")
        assert slept == []


# ---------------------------------------------------------------- proxy

class _FakeResponse:
    def __init__(self, chunks, status=200):
        self._chunks = chunks
        self.status_code = status

    async def aread(self):
        return b""

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://api.uspto.gov/doc.pdf")
            response = httpx.Response(self.status_code, request=request, headers={"Retry-After": "7"})
            raise httpx.HTTPStatusError("err", request=request, response=response)

    async def aiter_bytes(self, chunk_size=8192):
        for chunk in self._chunks:
            yield chunk

    async def aclose(self):
        pass


def _fake_client(monkeypatch, chunks, status=200):
    from patent_filewrapper_mcp.proxy import server as proxy_server

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        def build_request(self, *a, **kw):
            return object()

        async def send(self, request, stream=False):
            return _FakeResponse(chunks, status)

        async def aclose(self):
            pass

    monkeypatch.setattr(proxy_server.httpx, "AsyncClient", FakeClient)
    return proxy_server


_PROXY_ARGS = ("https://api.uspto.gov/y.pdf", {"X-Api-Key": _KEY}, "req-1", "PTAB")


class TestProxyBuffersUnderTheSlot:
    async def test_a_slow_consumer_does_not_hold_the_slot(self, monkeypatch, tmp_path):
        monkeypatch.setenv("USPTO_SHARED_RATE_LIMIT_DIR", str(tmp_path))
        monkeypatch.setenv("USPTO_SHARED_RATE_LIMIT_RPS", "1000")
        limiter = rate_limiter_module.get_shared_limiter()
        proxy_server = _fake_client(monkeypatch, [b"%PDF-1.7 fake", b" more", b" bytes"])

        stream = await proxy_server._open_upstream_pdf_stream(*_PROXY_ARGS)

        # Before the first byte is consumed the slot is already free.
        fh = limiter._try_acquire_any_slot()
        assert fh is not None
        limiter._release_slot(fh)

        chunks = []
        async for chunk in stream:
            await asyncio.sleep(0.05)  # a deliberately slow consumer
            fh = limiter._try_acquire_any_slot()
            assert fh is not None  # still free while the consumer dawdles
            limiter._release_slot(fh)
            chunks.append(chunk)
        assert b"".join(chunks) == b"%PDF-1.7 fake more bytes"

    async def test_limiter_timeout_is_a_503_with_retry_after(self, monkeypatch, tmp_path):
        monkeypatch.setenv("USPTO_SHARED_RATE_LIMIT_DIR", str(tmp_path))
        monkeypatch.setenv("USPTO_SHARED_MAX_WAIT_SECONDS", "0.2")
        limiter = rate_limiter_module.get_shared_limiter()
        proxy_server = _fake_client(monkeypatch, [b"%PDF-1.7 fake"])
        monkeypatch.setattr(limiter, "_try_acquire_any_slot", lambda: None)

        with pytest.raises(HTTPException) as exc_info:
            await proxy_server._open_upstream_pdf_stream(*_PROXY_ARGS)
        assert exc_info.value.status_code == 503
        assert exc_info.value.headers["Retry-After"] == "5"

    async def test_the_app_keeps_retry_after_on_the_503_json(self):
        """The proxy app's HTTPException handler rebuilds the body as JSON;
        it must carry the exception's Retry-After through."""
        from patent_filewrapper_mcp.proxy.server import create_proxy_app

        app = create_proxy_app()

        async def refuse():
            raise HTTPException(status_code=503, detail="busy", headers={"Retry-After": "5"})

        app.add_api_route("/_test/refuse", refuse, methods=["GET"])
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/_test/refuse")
        assert resp.status_code == 503
        assert resp.headers["Retry-After"] == "5"
        assert resp.json()["status_code"] == 503

    async def test_an_upstream_429_is_noted_on_the_key(self, monkeypatch, tmp_path):
        monkeypatch.setenv("USPTO_SHARED_RATE_LIMIT_DIR", str(tmp_path))
        monkeypatch.setenv("USPTO_SHARED_RATE_LIMIT_RPS", "1000")
        limiter = rate_limiter_module.get_shared_limiter()
        proxy_server = _fake_client(monkeypatch, [], status=429)

        with pytest.raises(httpx.HTTPStatusError):
            await proxy_server._open_upstream_pdf_stream(*_PROXY_ARGS)
        assert limiter._read_cooldown_until() > 0
        # The slot was released on the way out.
        fh = limiter._try_acquire_any_slot()
        assert fh is not None
        limiter._release_slot(fh)

    async def test_the_byte_cap_bounds_the_buffer(self, monkeypatch):
        proxy_server = _fake_client(monkeypatch, [b"%PDF-1.7 ", b"x" * 100])

        with pytest.raises(HTTPException) as exc_info:
            await proxy_server._open_upstream_pdf_stream(*_PROXY_ARGS, max_bytes=50)
        assert exc_info.value.status_code == 502

        stream = await proxy_server._open_upstream_pdf_stream(*_PROXY_ARGS, max_bytes=500)
        assert len(b"".join([c async for c in stream])) == 109

    async def test_the_default_cap_is_the_extraction_ceiling(self, monkeypatch):
        monkeypatch.setenv("PFW_MAX_DOCUMENT_BYTES", "20")
        proxy_server = _fake_client(monkeypatch, [b"%PDF-1.7 ", b"x" * 100])

        with pytest.raises(HTTPException) as exc_info:
            await proxy_server._open_upstream_pdf_stream(*_PROXY_ARGS)
        assert exc_info.value.status_code == 502
