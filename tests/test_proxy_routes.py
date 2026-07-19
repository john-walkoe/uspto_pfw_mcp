"""Test proxy route auth — verifies the production bug fix for persistent link route."""
import pytest
from httpx import AsyncClient, ASGITransport
from patent_filewrapper_mcp.proxy.server import create_proxy_app


@pytest.fixture
def proxy_app():
    """Create a fresh proxy app for each test."""
    return create_proxy_app()


@pytest.mark.asyncio
class TestProxyRoutes:
    async def test_persistent_link_no_token_required(self, proxy_app):
        """GET /document/persistent/{hash} must NOT require X-Proxy-Token.
        Browser-facing. Missing/unknown hash → 404, not 401."""
        async with AsyncClient(
            transport=ASGITransport(app=proxy_app),
            base_url="http://test"
        ) as client:
            resp = await client.get("/document/persistent/deadbeefdeadbeef")
            assert resp.status_code == 404, (
                f"Expected 404 for unknown hash, got {resp.status_code}. "
                f"If 401: ProxyTokenDependency was incorrectly re-added to this route."
            )

    async def test_register_download_requires_token(self, proxy_app):
        """POST /api/register-download without token → 401."""
        async with AsyncClient(
            transport=ASGITransport(app=proxy_app),
            base_url="http://test"
        ) as client:
            resp = await client.post("/api/register-download", json={})
            assert resp.status_code == 401, (
                f"Expected 401 without token, got {resp.status_code}"
            )

    async def test_recent_downloads_requires_token(self, proxy_app):
        """GET /api/recent-downloads without token → 401 (audit C2: entries
        contain live persistent-link download credentials)."""
        async with AsyncClient(
            transport=ASGITransport(app=proxy_app),
            base_url="http://test"
        ) as client:
            resp = await client.get("/api/recent-downloads")
            assert resp.status_code == 401, (
                f"Expected 401 without token, got {resp.status_code}"
            )

    async def test_recent_downloads_with_token_ok(self, proxy_app):
        """GET /api/recent-downloads with the proxy token → 200 JSON list."""
        from patent_filewrapper_mcp.proxy.server import _get_proxy_token as get_proxy_token
        async with AsyncClient(
            transport=ASGITransport(app=proxy_app),
            base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/recent-downloads",
                headers={"X-Proxy-Token": get_proxy_token()},
            )
            assert resp.status_code == 200
            assert isinstance(resp.json(), list)

    async def test_download_requires_token(self, proxy_app):
        """GET /download/{app}/{doc} without token → 401."""
        async with AsyncClient(
            transport=ASGITransport(app=proxy_app),
            base_url="http://test"
        ) as client:
            resp = await client.get("/download/12345678/SOMEID")
            assert resp.status_code == 401, (
                f"Expected 401 without token, got {resp.status_code}"
            )

    async def test_root_health_responds(self, proxy_app):
        """GET / (health check) must respond — the proxy health endpoint.

        Note: /health and / are the same route in the proxy (line 729).
        """
        async with AsyncClient(
            transport=ASGITransport(app=proxy_app),
            base_url="http://test"
        ) as client:
            resp = await client.get("/")
            # 200 or 503 both indicate the endpoint is responding
            # (503 may occur if USPTO API is unreachable — that's fine for proxy)
            assert resp.status_code in (200, 503), f"Health check failed: {resp.status_code}"
