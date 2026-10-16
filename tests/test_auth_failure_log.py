"""Authentication failures on /mcp reach security.log.

The reason classifier on hand-built headers and the ASGI wrapper on a stub
app: each refusal logged once with the client address and a reason code, and
the token itself never in the record."""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from patent_filewrapper_mcp.util.auth_failure_log import AuthFailureLogMiddleware, classify_auth_failure
from patent_filewrapper_mcp.util.security_logger import security_logger

ISS = "https://issuer.example"
BASE = "https://pfw.example"
AUD = f"{BASE}/mcp"
HDR = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
       "MCP-Protocol-Version": "2025-11-25"}


def _unsigned(claims: dict[str, Any]) -> str:
    def seg(d: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    return f"{seg({'alg': 'ES256', 'kid': 'k1'})}.{seg(claims)}.c2ln"


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(security_logger, "log_auth_failure", lambda **kw: seen.append(kw))
    return seen


# ------------------------------------------------------------- classifier


@pytest.mark.parametrize(("authorization", "status", "reason"), [
    (None, 401, "missing_token"),
    ("", 401, "missing_token"),
    ("Bearer ", 401, "missing_token"),
    ("Basic dXNlcjpwdw==", 401, "not_bearer"),
    ("Bearer some-opaque-internal-bearer", 401, "invalid_token"),
    ("Bearer a.b.c", 401, "malformed_token"),
    (f"Bearer {_unsigned({'exp': 1, 'aud': AUD, 'iss': ISS})}", 401, "expired"),
    (f"Bearer {_unsigned({'exp': 4e9, 'aud': 'https://other/mcp', 'iss': ISS})}", 401, "wrong_audience"),
    (f"Bearer {_unsigned({'exp': 4e9, 'aud': [AUD], 'iss': 'https://evil'})}", 401, "wrong_issuer"),
    (f"Bearer {_unsigned({'exp': 4e9, 'aud': AUD, 'iss': ISS, 'scope': 'other'})}", 401, "insufficient_scope"),
    (f"Bearer {_unsigned({'exp': 4e9, 'aud': AUD, 'iss': ISS, 'scope': 'mcp:user'})}", 401, "bad_signature"),
    ("Bearer whatever", 403, "insufficient_scope"),
])
def test_reasons(authorization: Any, status: int, reason: str) -> None:
    assert classify_auth_failure(authorization, status, audience=AUD, issuer=ISS,
                                 required_scope="mcp:user") == reason


def test_without_audience_or_issuer_a_well_formed_jwt_reads_as_bad_signature() -> None:
    token = _unsigned({"exp": 4e9, "aud": "https://anything", "iss": "https://anyone"})
    assert classify_auth_failure(f"Bearer {token}", 401) == "bad_signature"


def test_an_oversized_jwt_is_not_decoded() -> None:
    token = "a" * 20000 + ".b.c"
    assert classify_auth_failure(f"Bearer {token}", 401) == "malformed_token"


# ------------------------------------------------------------- the wrapper


def _app(status: int):
    async def app(scope: dict, receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    return app


@pytest.mark.parametrize(("path", "status", "logged"), [
    ("/mcp", 401, True), ("/mcp/", 403, True), ("/mcp", 200, False),
    ("/health", 401, False), ("/.well-known/oauth-protected-resource/mcp", 401, False),
])
def test_only_mcp_refusals_are_logged(events: list[dict[str, Any]], path: str, status: int,
                                      logged: bool) -> None:
    client = TestClient(AuthFailureLogMiddleware(_app(status)))
    client.post(path, headers={"Authorization": "Bearer opaque-secret-value"})
    assert bool(events) is logged
    if logged:
        assert events[0]["endpoint"] == path
        assert events[0]["client_ip"]
        assert "opaque-secret-value" not in json.dumps(events)


def test_a_logging_failure_never_breaks_the_response(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(**kw: Any) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(security_logger, "log_auth_failure", boom)
    r = TestClient(AuthFailureLogMiddleware(_app(401))).post("/mcp")
    assert r.status_code == 401


def test_the_client_address_comes_from_a_trusted_proxy_header(events: list[dict[str, Any]],
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROXY_TRUSTED_IPS", "testclient, 127.0.0.0/8")
    app = AuthFailureLogMiddleware(_app(401))

    async def run() -> None:
        sent: list[dict] = []

        async def receive() -> dict:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict) -> None:
            sent.append(message)

        await app({"type": "http", "path": "/mcp", "client": ("127.0.0.1", 5000),
                   "headers": [(b"cf-connecting-ip", b"203.0.113.9")]}, receive, send)

    import asyncio

    asyncio.run(run())
    assert events[0]["client_ip"] == "203.0.113.9"
    assert events[0]["reason"] == "missing_token"


# ------------------------------------------------------------- end to end


@pytest.mark.parametrize(("key", "reason"), [(None, "missing_api_key"), ("wrong", "bad_api_key")])
def test_api_key_mode_refusals_are_logged(events: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch,
                                          key: Any, reason: str) -> None:
    from patent_filewrapper_mcp import middleware

    monkeypatch.setenv("INTERNAL_AUTH_SECRET", "s" * 40)
    middleware.reset_expected_secret()
    try:
        client = TestClient(middleware.APIKeyAuthMiddleware(_app(200)))
        r = client.post("/mcp", headers={"x-api-key": key} if key else {})
        assert r.status_code == 401
        assert [(e["endpoint"], e["reason"]) for e in events] == [("/mcp", reason)]
        assert "wrong" not in json.dumps(events)
        events.clear()
        assert client.post("/mcp", headers={"x-api-key": "s" * 40}).status_code == 200
        assert events == []
    finally:
        middleware.reset_expected_secret()


def test_the_security_log_follows_log_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The containers set LOG_DIR=/app/logs (the mounted directory log_config
    announces); the security log must land there, not in the home directory."""
    import logging

    from patent_filewrapper_mcp.util.security_logger import SecurityLogger

    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    assert SecurityLogger.__init__.__defaults__ == (None, True)
    sec = logging.getLogger("security")
    saved = list(sec.handlers)
    sec.handlers.clear()
    try:
        made = SecurityLogger(enable_alerting=False)
        assert made.log_dir == str(tmp_path)
        assert (tmp_path / "security.log").exists()
    finally:
        for h in list(sec.handlers):
            h.close()
        sec.handlers[:] = saved
