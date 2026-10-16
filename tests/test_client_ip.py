"""Client-IP resolution behind a reverse proxy.

util/client_ip.py is what every rate limit and security-log line now reads
instead of the raw `request.client.host`, which behind a reverse proxy is
always the proxy's own address. These tests build Starlette Request objects directly from ASGI
scopes so no live server or network is needed.
"""
from __future__ import annotations

import pytest
from starlette.requests import Request

from patent_filewrapper_mcp.util.client_ip import (
    resolve_client_ip,
    resolve_client_ip_from_scope,
)


def _request(client_host: str, headers: dict[str, str] | None = None) -> Request:
    raw_headers = [
        (k.lower().encode("latin-1"), v.encode("latin-1"))
        for k, v in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "client": (client_host, 12345),
        "headers": raw_headers,
        "method": "GET",
        "path": "/",
    }
    return Request(scope)


def test_untrusted_peer_is_used_as_is_and_headers_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PROXY_TRUSTED_IPS", raising=False)
    request = _request("203.0.113.9", {"CF-Connecting-IP": "198.51.100.1"})
    assert resolve_client_ip(request) == "203.0.113.9"


def test_trusted_peer_uses_cf_connecting_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROXY_TRUSTED_IPS", "172.18.0.0/16")
    request = _request("172.18.0.4", {"CF-Connecting-IP": "198.51.100.1"})
    assert resolve_client_ip(request) == "198.51.100.1"


def test_trusted_peer_with_no_cf_header_falls_back_to_rightmost_untrusted_xff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROXY_TRUSTED_IPS", "172.18.0.0/16")
    request = _request(
        "172.18.0.4",
        {"X-Forwarded-For": "198.51.100.1, 172.18.0.4"},
    )
    assert resolve_client_ip(request) == "198.51.100.1"


def test_untrusted_peer_ignores_x_forwarded_for_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PROXY_TRUSTED_IPS", raising=False)
    request = _request("203.0.113.9", {"X-Forwarded-For": "198.51.100.1"})
    assert resolve_client_ip(request) == "203.0.113.9"


def test_no_trusted_proxies_configured_uses_the_raw_peer_even_with_cf_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROXY_TRUSTED_IPS", "")
    request = _request("172.18.0.4", {"CF-Connecting-IP": "198.51.100.1"})
    assert resolve_client_ip(request) == "172.18.0.4"


def test_ipv6_client_is_collapsed_to_its_56(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROXY_TRUSTED_IPS", "172.18.0.0/16")
    request = _request(
        "172.18.0.4",
        {"CF-Connecting-IP": "2001:db8:1234:5678::1"},
    )
    assert resolve_client_ip(request) == "2001:db8:1234:5600::"


def test_ipv6_raw_peer_is_also_collapsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROXY_TRUSTED_IPS", raising=False)
    request = _request("2001:db8:1234:5678::1")
    assert resolve_client_ip(request) == "2001:db8:1234:5600::"


def test_malformed_trusted_ips_entry_is_dropped_not_treated_as_trust_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROXY_TRUSTED_IPS", "*")
    request = _request("172.18.0.4", {"CF-Connecting-IP": "198.51.100.1"})
    assert resolve_client_ip(request) == "172.18.0.4"


def test_from_scope_matches_resolve_client_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROXY_TRUSTED_IPS", "172.18.0.0/16")
    scope = {
        "client": ("172.18.0.4", 12345),
        "headers": [(b"cf-connecting-ip", b"198.51.100.1")],
    }
    assert resolve_client_ip_from_scope(scope) == "198.51.100.1"


def test_from_scope_with_no_client_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROXY_TRUSTED_IPS", raising=False)
    assert resolve_client_ip_from_scope({"headers": []}) == "unknown"
