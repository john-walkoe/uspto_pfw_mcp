"""Fleet review 2026-09-03, PFW client layer.

Covers: the ODP key riding cross-origin redirects, `self.api_key` bound only
inside the secure-store try, the permanently cached registry failure, one
client shared across two event loops, and the catch-alls that returned raw
exception text with no log line.
"""

import asyncio
import os
import threading

import httpx
import pytest

from patent_filewrapper_mcp import client_registry
from patent_filewrapper_mcp.api import enhanced_client as ec_mod
from patent_filewrapper_mcp.api.enhanced_client import EnhancedPatentClient
from patent_filewrapper_mcp.shared.uspto_hosts import (
    is_uspto_url,
    strip_api_key_off_uspto,
)


@pytest.fixture
def api_key_env(monkeypatch):
    monkeypatch.setenv("USPTO_API_KEY", "env-key-not-a-real-credential")


# ---------------------------------------------------------------------------
# The API key must not leave uspto.gov
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url,expected", [
    ("https://api.uspto.gov/api/v1/patent/applications", True),
    ("https://developer.uspto.gov/x", True),
    ("https://uspto.gov/x", True),
    ("http://api.uspto.gov/x", False),            # plaintext
    ("https://uspto.gov.evil.example/x", False),  # suffix confusion
    ("https://s3.amazonaws.com/signed", False),   # the real redirect target
])
def test_host_allowlist(url, expected):
    assert is_uspto_url(url) is expected


@pytest.mark.asyncio
async def test_direct_download_drops_the_key_on_a_cross_origin_redirect(
    monkeypatch, api_key_env
):
    """httpx strips only Authorization and Cookie on an origin change."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.host, request.headers.get("x-api-key")))
        if request.url.host == "api.uspto.gov":
            return httpx.Response(
                302, headers={"Location": "https://s3.example.com/signed.xml"}
            )
        return httpx.Response(200, text="<xml/>")

    real = httpx.AsyncClient

    def _mock_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(ec_mod.httpx, "AsyncClient", _mock_client)

    client = EnhancedPatentClient()
    body = await client.fetch_xml_from_url("https://api.uspto.gov/doc.xml")

    assert body == "<xml/>"
    assert seen[0] == ("api.uspto.gov", "env-key-not-a-real-credential")
    assert seen[1] == ("s3.example.com", None)


@pytest.mark.asyncio
async def test_hook_leaves_a_uspto_hop_alone():
    request = httpx.Request(
        "GET", "https://api.uspto.gov/x", headers={"X-API-KEY": "secret"}
    )
    await strip_api_key_off_uspto(request)
    assert request.headers["x-api-key"] == "secret"


# ---------------------------------------------------------------------------
# api_key is bound before the secure-store read, so the env fallback runs
# ---------------------------------------------------------------------------

def test_env_fallback_survives_a_failing_secure_store(monkeypatch, api_key_env):
    """`self.api_key` used to be assigned only inside the try, so a raising
    secure-store read produced AttributeError before the documented
    USPTO_API_KEY fallback could run."""
    import patent_filewrapper_mcp.shared_secure_storage as store

    def _boom():
        raise RuntimeError("keyring backend unavailable")

    monkeypatch.setattr(store, "get_uspto_api_key", _boom)

    client = EnhancedPatentClient()
    assert client.api_key == "env-key-not-a-real-credential"


def test_no_key_anywhere_still_raises_authentication_error(monkeypatch):
    import patent_filewrapper_mcp.shared_secure_storage as store
    from patent_filewrapper_mcp.exceptions import AuthenticationError

    monkeypatch.delenv("USPTO_API_KEY", raising=False)
    monkeypatch.setattr(store, "get_uspto_api_key", lambda: None)

    with pytest.raises(AuthenticationError):
        EnhancedPatentClient()


# ---------------------------------------------------------------------------
# The registry: one client per loop, and a resettable failure sentinel
# ---------------------------------------------------------------------------

def test_registry_failure_is_resettable(monkeypatch):
    import patent_filewrapper_mcp.shared_secure_storage as store

    monkeypatch.delenv("USPTO_API_KEY", raising=False)
    monkeypatch.setattr(store, "get_uspto_api_key", lambda: None)
    client_registry.reset_api_client()

    with pytest.raises(Exception):
        client_registry.get_api_client()
    # Sticky: the second call short-circuits on the cached error.
    with pytest.raises(Exception):
        client_registry.get_api_client()

    # ... until it is cleared, which is what the fix adds.
    client_registry.reset_api_client()
    monkeypatch.setenv("USPTO_API_KEY", "env-key-not-a-real-credential")
    try:
        assert client_registry.get_api_client() is not None
    finally:
        client_registry.reset_api_client()


def test_each_event_loop_gets_its_own_client(monkeypatch, api_key_env):
    """One client object carries an asyncio.Semaphore, which binds to the
    first loop that WAITS on it; sharing it across two loops in two threads
    is a load-dependent hang."""
    client_registry.reset_api_client()
    results = {}

    def _in_thread(name):
        async def _get():
            return client_registry.get_api_client()
        results[name] = asyncio.run(_get())

    try:
        threads = [
            threading.Thread(target=_in_thread, args=(name,))
            for name in ("mcp", "proxy")
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results["mcp"] is not results["proxy"]
    finally:
        client_registry.reset_api_client()


def test_injected_client_still_wins(monkeypatch, api_key_env):
    sentinel = object()
    monkeypatch.setattr(client_registry, "api_client", sentinel)
    assert client_registry._client() is sentinel


# ---------------------------------------------------------------------------
# Catch-alls log and return a sanitized message
# ---------------------------------------------------------------------------

def test_client_error_is_logged_and_sanitized(caplog, monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    boom = RuntimeError(
        "connect to https://api.uspto.gov/internal?key=leak failed at /srv/app/x.py"
    )

    with caplog.at_level("ERROR"):
        response = ec_mod._handle_client_error("Failed to get documents", boom)

    assert response["message"] == "Failed to get documents"
    assert "https://api.uspto.gov/internal" not in str(response)
    assert "/srv/app/x.py" not in str(response)
    # The operator does get the detail.
    assert any("Failed to get documents" in r.message for r in caplog.records)


def test_client_error_keeps_debug_detail_in_development(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    try:
        raise ValueError("upstream detail")
    except ValueError as e:
        response = ec_mod._handle_client_error("Failed to get documents", e)
    assert response["debug"]["exception_type"] == "ValueError"


# ---------------------------------------------------------------------------
# The ODP key is no longer written into a registration row
# ---------------------------------------------------------------------------

def test_registration_rows_do_not_carry_the_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("FPD_DOCUMENT_STORE_PATH", str(tmp_path / "fpd.db"))
    from patent_filewrapper_mcp.proxy.fpd_document_store import FPDDocumentStore

    store = FPDDocumentStore(db_path=str(tmp_path / "fpd.db"))
    assert store.register_document(
        petition_id="de4df959-dfe6-5b63-9ff2-d583b7333abd",
        document_identifier="TEST123",
        download_url="https://api.uspto.gov/test.pdf",
        application_number="12345678",
    )

    doc = store.get_document("de4df959-dfe6-5b63-9ff2-d583b7333abd", "TEST123")
    assert doc is not None
    assert "api_key" not in doc

    import sqlite3

    with sqlite3.connect(str(tmp_path / "fpd.db")) as conn:
        stored = conn.execute("SELECT api_key FROM fpd_documents").fetchone()[0]
    assert stored == ""


def test_download_route_resolves_the_key_live(monkeypatch):
    from patent_filewrapper_mcp.proxy.routes import downloads

    monkeypatch.setenv("USPTO_API_KEY", "env-key-not-a-real-credential")
    import patent_filewrapper_mcp.shared_secure_storage as store

    monkeypatch.setattr(store, "get_uspto_api_key", lambda: None)
    assert downloads._live_uspto_api_key() == "env-key-not-a-real-credential"

    monkeypatch.delenv("USPTO_API_KEY", raising=False)
    assert downloads._live_uspto_api_key() is None
    assert os.getenv("USPTO_API_KEY") is None
