"""ASGI middleware for the HTTP transport (carved out of main.py — audit
metrics 6/10 God File item). Module-level so the stack is testable.
"""

import os

from .shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)


_EXPECTED_SECRET_CANDIDATES = None


def _expected_secret_candidates():
    """The internal auth secret's rotation candidates, resolved ONCE per process.

    This used to run on every HTTP request: a Path.home() build, an exists(),
    a read_bytes(), and — where the secret is a systemd-creds blob — a
    BLOCKING subprocess.run with a 15-second timeout, on the ASGI event loop,
    on the hot path of every MCP call (audit error-handling F-4). A transient
    read failure also answered EVERY request with 500 until it recovered.

    The secret cannot change without a restart, and server_bootstrap already
    refuses to start on the HTTP transport without one, so resolving once is
    consistent with the existing fail-fast posture.

    INTERNAL_AUTH_SECRET may be a comma-separated list (current secret first,
    then any secret still being retired) — a rotation overlap window; a
    single value round-trips as a one-element list.
    """
    global _EXPECTED_SECRET_CANDIDATES
    if _EXPECTED_SECRET_CANDIDATES is None:
        from .shared_secure_storage import (
            get_internal_auth_secret,
            split_secret_candidates,
        )

        raw = get_internal_auth_secret() or os.environ.get("INTERNAL_AUTH_SECRET")
        _EXPECTED_SECRET_CANDIDATES = split_secret_candidates(raw)
    return _EXPECTED_SECRET_CANDIDATES


def reset_expected_secret() -> None:
    """Drop the memoized secret candidates (tests, and an explicit operator reload)."""
    global _EXPECTED_SECRET_CANDIDATES
    _EXPECTED_SECRET_CANDIDATES = None


def _matches_any_candidate(presented, candidates) -> bool:
    """Constant-time membership test against every rotation candidate.

    Every candidate is compared, never short-circuited on the first match, so
    the timing of a request cannot reveal how many secrets are in the
    rotation window or which one (if any) validated.
    """
    if not presented:
        return False
    import secrets as _secrets

    matched = False
    for candidate in candidates:
        if _secrets.compare_digest(presented, candidate):
            matched = True
    return matched


#: Headers both apps send. HSTS is here rather than proxy-only because the
#: two sets had diverged with neither a superset of the other (audit L-15);
#: each app then overrides only the CSP it actually needs.
#: X-XSS-Protection is deliberately ABSENT: it is a dead header in every
#: current browser and, in its legacy form, was itself an XSS vector (I-6).
COMMON_SECURITY_HEADERS = (
    ("x-content-type-options", "nosniff"),
    ("x-frame-options", "DENY"),
    ("strict-transport-security", "max-age=31536000; includeSubDomains"),
    ("referrer-policy", "strict-origin-when-cross-origin"),
)

#: The MCP transport serves the App iframes, whose inline scripts are the
#: point; the proxy serves only PDFs and JSON and needs nothing.
MCP_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'"
)
PROXY_CSP = "default-src 'none'"


class APIKeyAuthMiddleware:
    """Validates X-API-KEY header on all non-health requests in HTTP mode.

    Checks against INTERNAL_AUTH_SECRET (the shared cross-MCP secret).
    Health endpoint is intentionally open for load balancer probes.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        from starlette.requests import Request
        request = Request(scope, receive)
        if request.url.path == "/health":
            await self.app(scope, receive, send)
            return
        key = request.headers.get("x-api-key")
        candidates = _expected_secret_candidates()
        if not candidates:
            from starlette.responses import JSONResponse
            response = JSONResponse({"error": "Server misconfigured: INTERNAL_AUTH_SECRET not set"}, status_code=500)
            await response(scope, receive, send)
            return
        if not _matches_any_candidate(key, candidates):
            # Log the event only — never the presented key or the path
            logger.warning("HTTP auth failed (x-api-key missing or mismatch)")
            from starlette.responses import JSONResponse
            response = JSONResponse({"error": "Unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)

class SecurityHeadersMiddleware:
    """Adds browser security headers to all HTTP responses."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        _SECURITY_HEADERS = [
            (name.encode(), value.encode())
            for name, value in COMMON_SECURITY_HEADERS
        ] + [(b"content-security-policy", MCP_CSP.encode())]
        _OWNED = {name for name, _ in _SECURITY_HEADERS}

        async def patched_send(message):
            if message["type"] == "http.response.start":
                # REPLACE, do not append (audit L-14): appending meant a
                # framework upgrade that started emitting its own CSP or
                # X-Frame-Options would ship two conflicting values, and which
                # one a browser honors is not something to leave to chance.
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() not in _OWNED
                ]
                headers.extend(_SECURITY_HEADERS)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, patched_send)

def _accept_kinds(scope) -> tuple[bool, bool]:
    """(has_json, has_sse) for an ASGI scope's Accept header.

    RFC 7231 §5.3.2 wildcards, byte-for-byte the rule the MCP SDK's own
    `check_accept_headers` applies: `*/*` satisfies both, `application/*`
    satisfies JSON, `text/*` satisfies SSE, and parameters (`;q=0.8`) are
    stripped before comparison.

    Reimplemented rather than imported so this middleware stays a pure ASGI
    wrapper that needs no Starlette `Request` and no SDK-internal import; the
    parity is pinned by tests/test_probe_middleware_accept.py, which asserts
    against the SDK function itself.
    """
    accept = ""
    for name, value in scope.get("headers", []):
        if name == b"accept":
            accept = value.decode("latin-1")
            break
    kinds = [part.split(";")[0].strip().lower() for part in accept.split(",")]
    wildcard = "*/*" in kinds
    has_json = wildcard or any(k in ("application/json", "application/*") for k in kinds)
    has_sse = wildcard or any(k in ("text/event-stream", "text/*") for k in kinds)
    return has_json, has_sse


class _StreamableHTTPProbeMiddleware:
    """Return 401 for MCP probe requests the transport would answer with 406.

    claude.ai's MCP client first probes POST /mcp with an older format that
    omits 'text/event-stream' from Accept. FastMCP's StreamableHTTP handler
    rejects those with 406, which puts claude.ai into a permanent
    "format-incompatible" state where it never indexes the server's tools.
    Returning 401 instead causes claude.ai to attempt OAuth discovery (which
    returns 404 — expected), and then fall back to an anonymous connection
    that completes the full MCP handshake successfully.

    The interception mirrors the transport's OWN Accept rule so it can only
    ever pre-empt a request that was going to be refused anyway: POST needs
    both JSON and SSE (`mcp.server.streamable_http._validate_accept_header`,
    and `_streamable_http_modern` for the 2026-07-28 era), GET needs SSE. The
    original test was a substring search for 'text/event-stream', which 401'd
    conformant clients sending `Accept: */*` or `text/*` — values both eras of
    the transport accept. Under the modern era a `server/discover` POST from
    such a client was rejected before the SDK ever saw it, so the connection
    never formed.

    Must be the outermost middleware layer.
    """
    def __init__(self, inner_app):
        self.app = inner_app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            method = scope.get("method", "")
            path = scope.get("path", "")
            has_json, has_sse = _accept_kinds(scope)
            unacceptable = (
                (method == "POST" and not (has_json and has_sse))
                or (method == "GET" and not has_sse)
            )
            if path == "/mcp" and unacceptable:
                from starlette.responses import JSONResponse
                response = JSONResponse({"error": "Unauthorized"}, status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


