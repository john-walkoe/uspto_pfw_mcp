"""Tests for the Medium-severity audit fixes (M3, M4, M5, M6)."""

import httpx
import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from patent_filewrapper_mcp.models.search_params import SearchParameters
from patent_filewrapper_mcp.proxy import server as proxy_server
from patent_filewrapper_mcp.proxy.server import (
    _get_proxy_token,
    _open_upstream_pdf_stream,
    create_proxy_app,
)
from patent_filewrapper_mcp.shared.log_sanitizer import LogSanitizer


# ---------------------------------------------------------------- M3: chunked


@pytest.mark.asyncio
async def test_chunked_body_over_limit_rejected():
    """Transfer-Encoding: chunked (no Content-Length) must not bypass the
    request size cap (audit M3)."""
    app = create_proxy_app()

    async def big_body():
        chunk = b"x" * 65536
        for _ in range(20):  # ~1.25 MB > 1 MB cap
            yield chunk

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/register-download",
            headers={
                "X-Proxy-Token": _get_proxy_token(),
                "Content-Type": "application/json",
            },
            content=big_body(),
        )
        assert resp.status_code == 413


@pytest.mark.asyncio
async def test_content_length_over_limit_rejected():
    app = create_proxy_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/register-download",
            headers={
                "X-Proxy-Token": _get_proxy_token(),
                "Content-Type": "application/json",
                "Content-Length": str(2 * 1024 * 1024),
            },
        )
        assert resp.status_code == 413


# ------------------------------------------------------------ M4: magic bytes


def _mock_async_client(payload: bytes, status_code: int = 200):
    """AsyncClient factory whose transport always returns `payload`."""

    def handler(request):
        return httpx.Response(status_code, content=payload)

    real_client = httpx.AsyncClient

    def factory(**kwargs):
        kwargs.pop("transport", None)
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    return factory


@pytest.mark.asyncio
async def test_non_pdf_upstream_body_rejected_with_502(monkeypatch):
    monkeypatch.setattr(
        proxy_server.httpx, "AsyncClient", _mock_async_client(b"<html>error page</html>")
    )
    with pytest.raises(HTTPException) as exc_info:
        await _open_upstream_pdf_stream(
            "https://api.uspto.gov/doc.pdf", {}, "req-test", "TEST"
        )
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_pdf_upstream_body_streams_fully(monkeypatch):
    payload = b"%PDF-1.7\n" + b"y" * 20000
    monkeypatch.setattr(
        proxy_server.httpx, "AsyncClient", _mock_async_client(payload)
    )
    stream = await _open_upstream_pdf_stream(
        "https://api.uspto.gov/doc.pdf", {}, "req-test", "TEST"
    )
    received = b"".join([chunk async for chunk in stream])
    assert received == payload


@pytest.mark.asyncio
async def test_upstream_http_error_propagates(monkeypatch):
    monkeypatch.setattr(
        proxy_server.httpx, "AsyncClient", _mock_async_client(b"denied", 403)
    )
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await _open_upstream_pdf_stream(
            "https://api.uspto.gov/doc.pdf", {}, "req-test", "TEST"
        )
    # Body must be pre-read so route handlers can inspect e.response
    assert exc_info.value.response.status_code == 403


# --------------------------------------------------------- M5: log injection


def test_sanitizer_strips_control_characters():
    s = LogSanitizer()
    forged = "DOC1\r\n2026-07-05 FAKE - security - INFO - forged line\x00\x1b"
    result = s.sanitize_string(forged)
    assert "\n" not in result
    assert "\r" not in result
    assert "\x00" not in result
    assert "\x1b" not in result


def test_sanitizer_still_masks_secrets_after_strip():
    s = LogSanitizer()
    result = s.sanitize_string("x-api-key=SuperSecretValue123\nnext line")
    assert "SuperSecretValue123" not in result
    assert "\n" not in result


# ------------------------------------------------------------ M6: query cap


def test_query_over_1000_chars_rejected():
    with pytest.raises(ValueError, match="Query too long"):
        SearchParameters(query="a" * 1001)


def test_query_at_1000_chars_accepted():
    assert SearchParameters(query="a" * 1000).query is not None
