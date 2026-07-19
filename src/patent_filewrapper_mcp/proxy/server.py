"""
FastAPI HTTP server for secure document downloads

Provides browser-accessible download URLs while keeping USPTO API keys secure.
"""
import ipaddress
import os
import re
import secrets
import time
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx

from ..api.enhanced_client import EnhancedPatentClient
from ..api.helpers import generate_request_id, is_development
from ..util.security_logger import security_logger
from .fpd_document_store import get_fpd_store
from .ptab_document_store import get_ptab_store
from ..shared.safe_logger import get_safe_logger
from ..shared.uspto_shared_rate_limiter import get_shared_limiter

logger = get_safe_logger(__name__)


# ---------------------------------------------------------------------------
# Response-header sanitization helpers
# ---------------------------------------------------------------------------
def _safe_header_value(raw: Optional[str]) -> str:
    """
    Strip CR/LF and all control characters from a string before using it
    in an HTTP response header (Content-Disposition filename, X-Enhanced-Filename,
    or any other header that could be vulnerable to header injection).
    """
    if not raw:
        return ""
    return "".join(ch for ch in raw if ord(ch) >= 32 and ord(ch) != 127)


def _safe_filename(raw: Optional[str]) -> str:
    """
    Return a filename safe for use in Content-Disposition filename="...".

    Removes path separators, dots (to prevent ../ traversal), control chars,
    and any character outside printable ASCII.
    """
    if not raw:
        return "document.pdf"
    # Strip control chars and path separators.
    # Note: '.' is intentionally NOT in this class — path traversal risk comes from
    # '/' and '\' (already stripped), not from bare dots. Stripping dots breaks the
    # .pdf extension: "FOO.pdf" → "FOO_pdf" → appends ".pdf" → "FOO_pdf.pdf".
    safe = re.sub(r"[\x00-\x1f\x7f\\/:*?\"<>|]", "_", raw)
    safe = "".join(ch for ch in safe if ord(ch) >= 32 and ord(ch) != 127)
    if not safe.strip():
        return "document.pdf"
    if not safe.lower().endswith(".pdf"):
        safe += ".pdf"
    return safe[:200]

# =============================================================================
# Proxy Token — defense-in-depth auth for download/document endpoints
# =============================================================================
# Token source: PROXY_TOKEN env var (user-provided) or auto-generated at startup.
# All /download/* and /document/* endpoints require X-Proxy-Token: <token> header.
_PROXY_TOKEN: Optional[str] = None


def _get_proxy_token() -> str:
    """Get or generate the proxy auth token."""
    global _PROXY_TOKEN
    if _PROXY_TOKEN is None:
        _PROXY_TOKEN = os.getenv("PROXY_TOKEN", "")
        if not _PROXY_TOKEN:
            _PROXY_TOKEN = secrets.token_urlsafe(32)
            logger.info("Proxy token auto-generated (set PROXY_TOKEN env var to override)")
        else:
            logger.info("Proxy token loaded from PROXY_TOKEN env var")
    return _PROXY_TOKEN


class ProxyTokenDependency:
    """
    FastAPI dependency that requires X-Proxy-Token header on protected endpoints.

    Applies to all /download/* and /document/* routes.
    """

    async def __call__(self, request: Request) -> None:
        token = request.headers.get("x-proxy-token", "")
        expected = _get_proxy_token()
        if not secrets.compare_digest(token, expected):
            client_ip = request.client.host if request.client else "unknown"
            request_id = generate_request_id()
            logger.warning(
                f"[{request_id}] Proxy token missing or invalid from {client_ip} "
                f"(path={request.url.path})"
            )
            security_logger.log_auth_failure(
                str(request.url.path),
                client_ip,
                "invalid_proxy_token",
                request_id=request_id,
            )
            raise HTTPException(
                status_code=401,
                detail="Missing or invalid X-Proxy-Token header",
            )


# Reusable dependency instance
_check_proxy_token = ProxyTokenDependency()

# Request size limit configuration
MAX_REQUEST_SIZE = 1024 * 1024  # 1MB limit


class _BodyTooLarge(Exception):
    """Raised by the counting receive wrapper when a body exceeds the cap."""

    def __init__(self, received: int):
        self.received = received


class RequestSizeLimitMiddleware:
    """
    ASGI middleware to limit request body size for security.

    Prevents DoS attacks via large request bodies. Checks Content-Length when
    present AND keeps a running byte count while the body streams in, so
    Transfer-Encoding: chunked requests (no Content-Length) cannot bypass the
    cap (audit M3, CWE-400).
    """

    def __init__(self, app, max_request_size: int = MAX_REQUEST_SIZE):
        self.app = app
        self.max_request_size = max_request_size

    def _log_too_large(self, path: str, client_ip: str, detail: str, request_id: str) -> None:
        logger.warning(f"[{request_id}] Request body too large: {detail} from {client_ip}")
        security_logger.log_validation_error(
            path, client_ip, "request_body_too_large",
            f"{detail} exceeds {self.max_request_size} bytes", request_id,
        )

    async def _send_413(self, send, request_id: str) -> None:
        import json as _json
        body = _json.dumps({
            "error": True,
            "message": f"Request body too large. Maximum size: {self.max_request_size} bytes",
            "max_allowed": self.max_request_size,
            "request_id": request_id,
        }).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("latin-1")),
            ],
        })
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        client = scope.get("client")
        client_ip = client[0] if client else "unknown"

        content_length = None
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    content_length = int(value)
                except ValueError:
                    pass
                break

        if content_length is not None and content_length > self.max_request_size:
            request_id = generate_request_id()
            self._log_too_large(path, client_ip, f"Content-Length: {content_length} bytes", request_id)
            await self._send_413(send, request_id)
            return

        received = 0
        response_started = False

        async def counting_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_request_size:
                    raise _BodyTooLarge(received)
            return message

        async def tracking_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _BodyTooLarge as exc:
            request_id = generate_request_id()
            self._log_too_large(path, client_ip, f"streamed body: {exc.received}+ bytes", request_id)
            if not response_started:
                await self._send_413(send, request_id)
            # If the response already started there is nothing safe to send;
            # the connection is torn down by the server.

async def _limiter_acquire(limiter) -> None:
    """No-op when the shared rate limiter is disabled. Extracted so callers
    with an already-complex control flow (e.g. _open_upstream_pdf_stream)
    don't pick up an extra branch toward their own cyclomatic complexity."""
    if limiter is not None:
        await limiter.__aenter__()


async def _limiter_release(limiter) -> None:
    """No-op when the shared rate limiter is disabled. See _limiter_acquire."""
    if limiter is not None:
        await limiter.__aexit__(None, None, None)


async def _open_upstream_pdf_stream(download_url: str, headers: dict, request_id: str, source: str):
    """Open an upstream USPTO PDF stream with the body verified as a PDF.

    Prefetches the first chunk and checks the %PDF- magic bytes BEFORE any
    response headers go to the client, so a non-PDF upstream body becomes a
    clean 502 instead of being served as application/pdf (audit M4).

    Returns an async generator yielding the validated body. Mid-transfer
    upstream failures get a distinct log line instead of a silently truncated
    file (audit F21). Raises httpx.HTTPStatusError on non-2xx (body pre-read
    so callers may inspect it) and HTTPException(502) on magic-byte failure.

    Shared cross-process rate limiter (token + concurrency slot) — off unless
    USPTO_SHARED_RATE_LIMIT_DIR is set. A streamed PDF download legitimately
    occupies one of the shared slots for its FULL duration (USPTO's burst=1
    guidance), not just connection setup, so the limiter can't be a single
    `async with` here — it's acquired manually below and released either on
    an early-exit path or in stream_body()'s `finally`, since the generator
    this function returns outlives the function call.
    """
    # Bulkhead (audit F46): reuse the API client's download pool limits so
    # proxy download traffic can't starve tool traffic of connections
    client_kwargs = {"timeout": 60.0, "follow_redirects": True}
    download_limits = getattr(api_client, "download_limits", None)
    if download_limits is not None:
        client_kwargs["limits"] = download_limits
    client = httpx.AsyncClient(**client_kwargs)

    limiter = get_shared_limiter()
    await _limiter_acquire(limiter)
    try:
        response = await client.send(
            client.build_request("GET", download_url, headers=headers), stream=True
        )
    except BaseException:
        await _limiter_release(limiter)
        await client.aclose()
        raise
    try:
        if response.status_code >= 400:
            await response.aread()
        response.raise_for_status()
        byte_iter = response.aiter_bytes(chunk_size=8192)
        first_chunk = b""
        async for chunk in byte_iter:
            first_chunk = chunk
            break
        if not first_chunk.startswith(b"%PDF-"):
            logger.error(
                f"[{request_id}] Upstream {source} response failed PDF magic-byte check"
            )
            raise HTTPException(status_code=502, detail="Upstream document is not a PDF")
    except BaseException:
        await _limiter_release(limiter)
        await response.aclose()
        await client.aclose()
        raise

    async def stream_body():
        try:
            yield first_chunk
            async for chunk in byte_iter:
                yield chunk
        except Exception as exc:
            logger.error(
                f"[{request_id}] {source} PDF stream interrupted mid-transfer: "
                f"{type(exc).__name__}"
            )
            raise
        finally:
            await response.aclose()
            await client.aclose()
            await _limiter_release(limiter)

    return stream_body()


# Global client instance
api_client = None

async def _periodic_store_cleanup(interval_seconds: int = 3600):
    """Hourly expiry sweep (audit L8): expired persistent links and stale
    FPD/PTAB document registrations (which hold encrypted API keys) are
    deleted instead of accumulating until a manual /cache/cleanup call."""
    import asyncio

    from .secure_link_cache import get_link_cache

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            get_link_cache().cleanup_expired_links()
            get_fpd_store().cleanup_expired_documents()
            get_ptab_store().cleanup_expired_documents()
        except Exception as e:
            logger.error(f"Periodic store cleanup failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan"""
    import asyncio

    global api_client
    try:
        if api_client is None:
            api_client = EnhancedPatentClient()
            logger.info("USPTO API client initialized for proxy server")
        else:
            logger.info("Proxy using shared USPTO API client (audit F5)")
        cleanup_task = asyncio.create_task(_periodic_store_cleanup())
        try:
            yield
        finally:
            cleanup_task.cancel()
    except Exception as e:
        logger.error(f"Failed to initialize USPTO API client: {e}")
        raise

def create_proxy_app(shared_client: Optional[EnhancedPatentClient] = None) -> FastAPI:
    """Create FastAPI application for document proxy.

    Args:
        shared_client: pass the MCP tools' EnhancedPatentClient so the proxy
            shares its circuit breaker / response cache / retry budget (audit
            F5 — two independent instances meant resilience state never
            agreed and the health endpoint reported only the proxy's copy).
            When None (standalone runs, tests) a dedicated client is built
            in the lifespan.
    """
    global api_client
    if shared_client is not None:
        api_client = shared_client

    app = FastAPI(
        title="USPTO Document Proxy",
        description="Secure proxy for USPTO patent document downloads",
        version="1.0.0",
        lifespan=lifespan
    )

    # Add request size limit middleware
    app.add_middleware(RequestSizeLimitMiddleware, max_request_size=MAX_REQUEST_SIZE)

    # Add CORS middleware.
    # Default: localhost only (secure). Set CORS_EXTRA_ORIGIN env var to allow
    # additional origins — e.g. when behind a reverse proxy or MCP gateway.
    # Format: comma-separated URLs, e.g. "https://mcp.example.com,https://proxy.internal"
    import re as _re
    _proxy_cors_origins = ["http://localhost:*", "http://127.0.0.1:*"]
    _extra = os.getenv("CORS_EXTRA_ORIGIN", "").strip()
    if _extra:
        for _origin in _extra.split(","):
            _origin = _origin.strip()
            if not _origin:
                continue
            if not _re.match(r"^https?://[a-zA-Z0-9.\-]+(:[0-9]+)?$", _origin):
                raise ValueError(f"CORS_EXTRA_ORIGIN must be valid HTTP/HTTPS URLs, got: {_origin}")
            _proxy_cors_origins.append(_origin)
            logger.info(f"Proxy CORS: added extra origin {_origin}")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_proxy_cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Accept", "User-Agent", "Content-Type"],
    )

    # Add IP whitelist middleware for additional security.
    # Default: localhost only. Set PROXY_ALLOWED_IPS to extend (comma-separated IPs or CIDRs).
    # Example: PROXY_ALLOWED_IPS=172.19.0.0/16 (Docker proxy network range)
    _ip_allowlist = ["127.0.0.1", "::1"]
    _ip_networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    _extra_ips = os.getenv("PROXY_ALLOWED_IPS", "").strip()
    if _extra_ips:
        for _entry in _extra_ips.split(","):
            _entry = _entry.strip()
            if not _entry:
                continue
            try:
                _ip_networks.append(ipaddress.ip_network(_entry, strict=False))
                logger.info(f"Proxy IP allowlist: added network {_entry}")
            except ValueError:
                raise ValueError(f"PROXY_ALLOWED_IPS entry is not a valid IP or CIDR: {_entry!r}")

    def _ip_is_allowed(ip: str) -> bool:
        if ip in _ip_allowlist:
            return True
        try:
            addr = ipaddress.ip_address(ip)
            return any(addr in net for net in _ip_networks)
        except ValueError:
            return False

    @app.middleware("http")
    async def add_ip_access_control(request: Request, call_next):
        """Restrict access to localhost IPs (and any configured PROXY_ALLOWED_IPS networks)"""
        client_ip = request.client.host if request.client else "unknown"

        if not _ip_is_allowed(client_ip):
            request_id = generate_request_id()
            logger.warning(f"[{request_id}] Access denied from IP: {client_ip}")
            security_logger.log_auth_failure(
                str(request.url.path),
                client_ip,
                "ip_not_whitelisted",
                f"IP {client_ip} not in allowed list",
                request_id
            )
            return JSONResponse(
                status_code=403,
                content={"error": "Access denied from this IP address"}
            )

        response = await call_next(request)
        return response

    # Add security headers middleware
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        """Add standard security headers to all responses"""
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = "default-src 'none'"
        return response

    # =========================================================================
    # Global Exception Handlers
    # =========================================================================

    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException
    import traceback

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        """
        Handle HTTP exceptions with consistent error format

        This ensures all HTTP errors (404, 403, etc.) return consistent
        JSON responses with proper logging and request IDs.
        """
        request_id = generate_request_id()
        client_ip = request.client.host if request.client else "unknown"

        logger.warning(
            f"[{request_id}] HTTP {exc.status_code}: {exc.detail} "
            f"(path={request.url.path}, client={client_ip})"
        )

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": True,
                "success": False,
                "status_code": exc.status_code,
                "message": str(exc.detail),
                "request_id": request_id,
                "path": str(request.url.path),
                "timestamp": import_time().strftime('%Y-%m-%dT%H:%M:%SZ', import_time().gmtime())
            }
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """
        Handle request validation errors with actionable guidance

        This catches malformed requests (missing params, wrong types, etc.)
        and returns user-friendly error messages.
        """
        request_id = generate_request_id()
        client_ip = request.client.host if request.client else "unknown"

        # Pydantic v2 puts the raw exception object in ctx['error'] — not
        # JSON-serializable, which turned every model-validator rejection
        # (e.g. the SSRF download_url check) into a 500 instead of a 422.
        errors = []
        for err in exc.errors():
            err = dict(err)
            err.pop("url", None)
            ctx = err.get("ctx")
            if isinstance(ctx, dict) and "error" in ctx:
                err["ctx"] = {**ctx, "error": str(ctx["error"])}
            errors.append(err)

        logger.warning(
            f"[{request_id}] Validation error: {errors} "
            f"(path={request.url.path}, client={client_ip})"
        )

        security_logger.log_validation_error(
            str(request.url.path),
            client_ip,
            "request_validation_failed",
            str(errors),
            request_id
        )

        return JSONResponse(
            status_code=422,
            content={
                "error": True,
                "success": False,
                "status_code": 422,
                "message": "Request validation failed",
                "request_id": request_id,
                "errors": errors,
                "guidance": "Check request parameters and try again",
                "timestamp": import_time().strftime('%Y-%m-%dT%H:%M:%SZ', import_time().gmtime())
            }
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """
        Handle all unhandled exceptions with environment-aware detail levels

        This is the catch-all handler for any exception that wasn't caught
        by more specific handlers. It provides different detail levels for
        development vs production environments.
        """
        request_id = generate_request_id()
        client_ip = request.client.host if request.client else "unknown"

        logger.exception(
            f"[{request_id}] Unhandled exception: {str(exc)} "
            f"(path={request.url.path}, client={client_ip})"
        )

        # Security log for unexpected errors
        security_logger.log_validation_error(
            str(request.url.path),
            client_ip,
            "unhandled_exception",
            type(exc).__name__,
            request_id
        )

        # Return different detail levels for dev vs production (audit F27:
        # single owner in api.helpers.is_development)

        response_content = {
            "error": True,
            "success": False,
            "status_code": 500,
            "message": "An unexpected error occurred",
            "request_id": request_id,
            "guidance": "Please try again. If the problem persists, contact support with request ID.",
            "timestamp": import_time().strftime('%Y-%m-%dT%H:%M:%SZ', import_time().gmtime())
        }

        if is_development():
            response_content["debug"] = {
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "traceback": traceback.format_exc()
            }

        return JSONResponse(
            status_code=500,
            content=response_content
        )

    def import_time():
        """Import time module to avoid circular imports"""
        return time

    # =========================================================================
    # Helper Functions
    # =========================================================================


    # Routers (audit F4): handlers live in proxy/routes/*, imported here
    # (after this module is fully loaded) so there is no import cycle.
    from .routes.admin import router as admin_router
    from .routes.downloads import router as downloads_router
    from .routes.reference import router as reference_router
    from .routes.registration import router as registration_router
    app.include_router(admin_router)
    app.include_router(downloads_router)
    app.include_router(registration_router)
    app.include_router(reference_router)


    return app
