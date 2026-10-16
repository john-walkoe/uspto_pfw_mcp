"""Client-IP resolution behind a reverse proxy.

A deployment behind a tunnel or reverse proxy (for example Cloudflare in
front of nginx) sees the proxy's own address as the ASGI transport peer for
every request, so every rate limit and every security-log line that keyed on
`request.client.host` collapses onto that one address: one shared bucket for
every caller, and audit entries that name the proxy instead of who actually
connected.

`resolve_client_ip` reads Cloudflare's `CF-Connecting-IP` header (or, failing
that, the right-most `X-Forwarded-For` hop that is not itself a trusted
proxy) ONLY when the immediate transport peer is in the configured
`PROXY_TRUSTED_IPS` set. From an untrusted peer those headers are just text
the caller sent and are never honored — the difference between "the proxy
told us who called" and "the caller told us who called".

This module deliberately does NOT rely on uvicorn's `proxy_headers`/
`forwarded_allow_ips` machinery, which rewrites `request.client` itself and
would collide with the PEER allowlist in `proxy/server.py`
(`add_ip_access_control`) — that check answers "is this peer even allowed to
reach the proxy" and must keep seeing the raw transport peer, not a value
already substituted from a header. Keeping resolution here, read
independently from the raw peer plus the raw headers, means one setting
(`PROXY_TRUSTED_IPS`) now correctly serves both without either reading the
other's already-rewritten address.
"""
from __future__ import annotations

import ipaddress
import os
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from starlette.requests import Request

# Comma-separated IPs/CIDRs of proxies immediately in front of this server
# that are trusted to set CF-Connecting-IP / X-Forwarded-For honestly.
# Default empty = trust nobody = the raw transport peer, today's behavior.
# Behind a containerised reverse proxy, name the Docker network the proxy
# sits on (for example 172.18.0.0/16) rather than one container address.
_ENV_VAR = "PROXY_TRUSTED_IPS"


def _parse_trusted_proxies(
    raw: str,
) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """Parse PROXY_TRUSTED_IPS. A malformed entry is dropped rather than
    failing the whole list — a typo should narrow trust, never silently
    widen it to 'accept everything'."""
    nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            continue
    return tuple(nets)


def _trusted_proxies() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    # Read fresh each call (not cached): the env var is only ever set at
    # process start in practice, and re-reading keeps tests that monkeypatch
    # it honest with no cache to invalidate.
    return _parse_trusted_proxies(os.getenv(_ENV_VAR, ""))


def _collapse_v6(ip: str) -> str:
    """Collapse an IPv6 address to its /56 for keying: a caller who owns a
    /56 (a common residential or cloud allocation) must not be able to
    rotate through it for a fresh bucket per address. IPv4 addresses and
    anything that fails to parse pass through unchanged."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if isinstance(addr, ipaddress.IPv6Address):
        return str(ipaddress.ip_network(f"{addr}/56", strict=False).network_address)
    return ip


def _forwarded_client_ip(
    get_header: Callable[[str], str],
    trusted: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
) -> str | None:
    """CF-Connecting-IP, else the right-most X-Forwarded-For hop that is not
    itself one of the trusted proxies. Only ever consulted once the caller
    has confirmed the immediate peer IS trusted — from anywhere else these
    headers are the caller's own text."""
    cf = get_header("cf-connecting-ip").strip()
    if cf:
        return cf
    chain = [p.strip() for p in get_header("x-forwarded-for").split(",") if p.strip()]
    for hop in reversed(chain):
        try:
            ip = ipaddress.ip_address(hop)
        except ValueError:
            return hop  # not an address at all; take it as-is rather than loop forever
        if not any(ip in net for net in trusted):
            return hop
    return None


def _resolve(peer_host: str | None, get_header: Callable[[str], str]) -> str:
    trusted = _trusted_proxies()
    peer: ipaddress.IPv4Address | ipaddress.IPv6Address | None = None
    if peer_host is not None:
        try:
            peer = ipaddress.ip_address(peer_host)
        except ValueError:
            peer = None
    if trusted and peer is not None and any(peer in net for net in trusted):
        forwarded = _forwarded_client_ip(get_header, trusted)
        if forwarded:
            return _collapse_v6(forwarded)
    if peer is not None:
        return _collapse_v6(str(peer))
    return peer_host or "unknown"


def resolve_client_ip(request: "Request") -> str:
    """The client key/attribution for rate limiting and security logging on
    a Starlette/FastAPI `Request`: CF-Connecting-IP (or the right-most
    untrusted X-Forwarded-For hop) when the immediate transport peer is a
    trusted proxy, else the raw peer address, else "unknown"."""
    peer_host = request.client.host if request.client else None
    return _resolve(peer_host, lambda name: request.headers.get(name, ""))


def resolve_client_ip_from_scope(scope: dict) -> str:
    """Same resolution as `resolve_client_ip`, for raw-ASGI middleware that
    runs before a Request object exists (e.g. RequestSizeLimitMiddleware)."""
    client = scope.get("client")
    peer_host = client[0] if client else None
    headers: dict[bytes, bytes] = dict(scope.get("headers") or [])

    def get_header(name: str) -> str:
        return headers.get(name.encode("latin-1"), b"").decode("latin-1")

    return _resolve(peer_host, get_header)
