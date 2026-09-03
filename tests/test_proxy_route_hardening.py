"""Proxy route hardening: diagnostics are gated, upstream failures keep their
status, the rate limiter is charged once, and no route ships raw exception
text (audits M-4, M-6, M-21, exception-flow F-2, resilience F-7).
"""

import inspect

import pytest
from httpx import ASGITransport, AsyncClient

from patent_filewrapper_mcp.proxy.routes import admin, downloads, reference


@pytest.fixture
def proxy_app():
    from patent_filewrapper_mcp.proxy.rate_limiter import rate_limiter
    from patent_filewrapper_mcp.proxy.server import create_proxy_app

    rate_limiter.requests.clear()
    return create_proxy_app()


async def _get(app, path):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(path)


@pytest.mark.asyncio
class TestDiagnosticsAreGated:
    """These reported circuit-breaker, retry-budget and store statistics to
    anyone who could reach the port (audit M-4)."""

    @pytest.mark.parametrize(
        "path", ["/ptab-stats", "/fpd-stats", "/reflections/stats"]
    )
    async def test_stats_endpoints_require_the_proxy_token(self, proxy_app, path):
        resp = await _get(proxy_app, path)
        assert resp.status_code == 401, (
            f"{path} answered {resp.status_code} without a token"
        )

    async def test_the_liveness_root_stays_open(self, proxy_app):
        """`/` is what _port_serves_healthy_proxy probes and what an
        orchestrator polls; gating it would break both."""
        resp = await _get(proxy_app, "/")
        assert resp.status_code in (200, 503)
        assert resp.json()["service"] == "USPTO Document Proxy"


class TestUpstreamStatusMapping:
    """Every client error envelope became 404 'Document not found', so a user
    retrying during a USPTO outage was told the document does not exist."""

    @pytest.mark.parametrize(
        "upstream, expected",
        [
            (404, 404),  # genuinely unknown application
            (408, 502),  # USPTO timeout
            (401, 502),  # auth failure
            (429, 503),  # rate limited
            (503, 503),  # circuit breaker open
            (None, 502),  # no status at all
            ("junk", 502),  # unparseable
        ],
    )
    def test_the_upstream_status_is_carried_through(self, upstream, expected):
        envelope = {"error": True}
        if upstream is not None:
            envelope["status_code"] = upstream
        assert downloads._upstream_status(envelope) == expected


class TestPdfOptionSelection:
    def test_a_missing_document_is_404(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            downloads._select_pdf_option([], "NOPE")
        assert exc.value.status_code == 404

    def test_a_document_with_no_pdf_option_says_so(self):
        from fastapi import HTTPException

        docs = [{"documentIdentifier": "D1", "downloadOptionBag": [
            {"mimeTypeIdentifier": "XML", "downloadUrl": "https://x"}]}]
        with pytest.raises(HTTPException) as exc:
            downloads._select_pdf_option(docs, "D1")
        assert exc.value.status_code == 404
        assert "PDF not available" in exc.value.detail

    def test_a_pdf_option_with_no_url_says_so(self):
        from fastapi import HTTPException

        docs = [{"documentIdentifier": "D1", "downloadOptionBag": [
            {"mimeTypeIdentifier": "PDF"}]}]
        with pytest.raises(HTTPException) as exc:
            downloads._select_pdf_option(docs, "D1")
        assert "Download URL not available" in exc.value.detail

    def test_the_pdf_option_is_returned_when_present(self):
        docs = [{"documentIdentifier": "D1", "downloadOptionBag": [
            {"mimeTypeIdentifier": "XML", "downloadUrl": "https://x"},
            {"mimeTypeIdentifier": "PDF", "downloadUrl": "https://y"}]}]
        target, option = downloads._select_pdf_option(docs, "D1")
        assert target["documentIdentifier"] == "D1"
        assert option["downloadUrl"] == "https://y"


class TestRateLimiterChargedOnce:
    def test_the_persistent_resolver_calls_the_unlimited_inner_function(self):
        """It charged the limiter itself and then called download_document,
        which charged it again: the advertised 5-per-10s was 2 (audit M-21)."""
        source = inspect.getsource(downloads.download_document_persistent)
        assert "_dispatch_download(" in source
        assert "await download_document(" not in source, (
            "the persistent path still calls the rate-limiting wrapper"
        )

    def test_the_dispatch_function_does_not_touch_the_limiter(self):
        source = inspect.getsource(downloads._dispatch_download)
        assert "rate_limiter" not in source, (
            "_dispatch_download must stay unlimited; its callers own the charge"
        )

    def test_the_public_route_still_rate_limits(self):
        source = inspect.getsource(downloads.download_document)
        assert "rate_limiter.is_allowed" in source


class TestNoRawExceptionText:
    """A codebase that scrubs this carefully on the log path was shipping it
    on the response path (audit M-6)."""

    @pytest.mark.parametrize("module", [admin, downloads, reference])
    def test_no_httpexception_detail_interpolates_the_exception(self, module):
        source = inspect.getsource(module)
        offenders = [
            line.strip()
            for line in source.splitlines()
            if "detail=" in line and ("str(e)" in line or "{e}" in line)
        ]
        assert not offenders, f"raw exception text in a response detail: {offenders}"

    @pytest.mark.parametrize("module", [admin, reference])
    def test_no_route_returns_http_200_with_an_error_key(self, module):
        source = inspect.getsource(module)
        offenders = [
            line.strip()
            for line in source.splitlines()
            if 'return {"error": str(e)}' in line
            or 'return {"success": False, "error": str(e)}' in line
        ]
        assert not offenders, (
            f"route returns 200 with raw exception text: {offenders}"
        )


class TestDatabaseHealth:
    def test_the_probe_targets_real_databases_not_a_temp_file(self):
        """It used to create a NEW temp SQLite file, SELECT 1 and unlink it,
        which only proves the SQLite library works (audit resilience F-7)."""
        source = inspect.getsource(admin._database_health)
        assert "NamedTemporaryFile" not in source
        assert "PFW_AUTH_DB_PATH" in source

    def test_the_probe_reports_healthy_when_no_store_exists_yet(self, monkeypatch):
        monkeypatch.setenv("PFW_AUTH_DB_PATH", "/nonexistent/mcp_auth.db")
        result = admin._database_health()
        assert result["status"] == "healthy"

    def test_the_probe_does_not_leak_exception_text(self):
        source = inspect.getsource(admin._database_health)
        assert "str(db_error)" not in source
        assert "str(e)" not in source
