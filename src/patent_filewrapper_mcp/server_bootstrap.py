"""Server bootstrap: process entry point, transport selection, and proxy
lifecycle (carved out of main.py — audit metrics 6/10 God File item).

Imports of the FastMCP app object happen lazily inside functions so this
module never participates in an import cycle with main.py.
"""

import asyncio
import os

from .shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)


# Global proxy server state
_proxy_server_running = False
_proxy_server_task = None


def _handle_background_task_exception(task: asyncio.Task):
    """
    Handle exceptions from background asyncio tasks

    This prevents silent failures in background tasks by logging errors
    and ensuring proper error handling for critical async operations.

    Args:
        task: The completed asyncio Task to check for exceptions
    """
    try:
        task.result()  # This will raise if the task failed
    except asyncio.CancelledError:
        logger.info("Background task was cancelled (this is normal during shutdown)")
    except Exception as e:
        logger.exception(f"Background task failed with unhandled exception: {e}")
        # Additional error handling can be added here:
        # - Restart critical tasks
        # - Send alerts
        # - Update health status
        global _proxy_server_running
        if task == _proxy_server_task:
            _proxy_server_running = False
            logger.error("Proxy server task failed - proxy server is no longer running")



async def _ensure_proxy_server_running(port: int = 8080):
    """Ensure the proxy server is running.

    If the port is already in use (e.g. Claude Desktop has a copy running),
    skip starting a second instance so MCP tools remain fully operational.
    """
    global _proxy_server_running, _proxy_server_task

    if not _proxy_server_running:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            port_free = s.connect_ex(("127.0.0.1", port)) != 0

        if not port_free:
            logger.info(
                "Port %d already in use — skipping proxy server startup "
                "(another instance is running; MCP tools are still fully available)",
                port,
            )
            _proxy_server_running = True  # treat as running so tools work
            return

        logger.info(f"Starting HTTP proxy server on port {port}")
        _proxy_server_task = asyncio.create_task(_run_proxy_server(port))

        # Add error handler to catch background task failures
        _proxy_server_task.add_done_callback(_handle_background_task_exception)

        _proxy_server_running = True
        # Give the server a moment to start
        await asyncio.sleep(0.5)

async def _run_proxy_server(port: int = 8080):
    """Run the FastAPI proxy server"""
    try:
        import uvicorn
        from .proxy.server import create_proxy_app

        # Share the MCP tools' client so circuit breaker / cache / retry
        # budget are one set of state, not two (audit F5). Falls back to a
        # proxy-local client when the tools haven't initialized one yet.
        shared_client = None
        try:
            from . import main as _main
            shared_client = _main.get_api_client()
        except Exception:
            logger.info("Shared API client unavailable — proxy will build its own")
        app = create_proxy_app(shared_client=shared_client)
        # Proxy bind host: defaults to 127.0.0.1 (localhost-only, secure default).
        # Set PROXY_BIND_HOST=0.0.0.0 in Docker so the host browser can reach
        # the download proxy via the container's exposed port.
        proxy_bind_host = os.getenv("PROXY_BIND_HOST", "127.0.0.1")
        config = uvicorn.Config(
            app,
            host=proxy_bind_host,
            port=port,
            log_level="info",
            access_log=False,  # Reduce noise in logs
            # Honor X-Forwarded-For only from trusted proxy peers (audit M2):
            # behind NPM/reverse proxy every request otherwise shares the
            # proxy's IP — one rate-limit bucket, wrong audit attribution.
            proxy_headers=True,
            forwarded_allow_ips=os.getenv("PROXY_TRUSTED_IPS", "127.0.0.1"),
        )
        server = uvicorn.Server(config)
        logger.info(f"HTTP proxy server starting on http://127.0.0.1:{port}")
        await server.serve()

    except Exception as e:
        global _proxy_server_running
        _proxy_server_running = False
        logger.error(f"Proxy server failed: {e}")
        raise



async def run_hybrid_server():
    """Run both MCP server and HTTP proxy server concurrently"""
    from .main import mcp
    try:
        # Start both servers concurrently
        logger.info("Starting hybrid MCP + HTTP proxy server")

        # Check if always-on proxy is enabled (default: true)
        enable_always_on_proxy = os.getenv("ENABLE_ALWAYS_ON_PROXY", "true").lower() == "true"
        # Check PFW_PROXY_PORT first (MCP-specific), then PROXY_PORT (generic)
        proxy_port = int(os.getenv('PFW_PROXY_PORT', os.getenv('PROXY_PORT', 8080)))

        if enable_always_on_proxy:
            logger.info("Always-on proxy mode enabled - starting proxy server immediately")
            # Start proxy server immediately for Resources and persistent links
            await _ensure_proxy_server_running(proxy_port)
        else:
            logger.info("On-demand proxy mode - proxy will start when first download is requested")

        # Run MCP server in a separate task
        mcp_task = asyncio.create_task(
            asyncio.to_thread(lambda: mcp.run(transport='stdio'))
        )

        # Add error handler to catch MCP task failures
        mcp_task.add_done_callback(_handle_background_task_exception)

        # Wait for MCP server to complete (it runs indefinitely)
        await mcp_task

    except KeyboardInterrupt:
        logger.info("Shutting down servers...")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise

def _asyncio_exception_handler(loop, context):
    """
    Global exception handler for asyncio event loop

    Catches unhandled exceptions in async tasks and coroutines
    to prevent silent failures.

    Args:
        loop: The event loop where the exception occurred
        context: Dictionary with exception information
    """
    exception = context.get('exception')
    message = context.get('message', 'Unhandled exception in async task')

    if exception:
        logger.exception(
            f"Uncaught async exception: {message}",
            exc_info=(type(exception), exception, exception.__traceback__)
        )
    else:
        logger.error(f"Async error: {message}")

    # Log full context for debugging
    logger.error(f"Async error context: {context}")


def main():
    """
    Main entry point for the MCP server.

    Transport is controlled by FASTMCP_TRANSPORT:
      FASTMCP_TRANSPORT=stdio  (default) — Claude Desktop / Claude Code compatible
      FASTMCP_TRANSPORT=http             — HTTP/SSE mode for Docker, reverse proxy, basic-host

    HTTP mode environment variables:
      FASTMCP_HOST=0.0.0.0       Bind address (default: 127.0.0.1)
      FASTMCP_PORT=8000           Port (default: 8000)
      CORS_EXTRA_ORIGIN=https://… Additional CORS origin beyond localhost (comma-separated)

    STDIO mode environment variables:
      ENABLE_PROXY_SERVER=true    Enable document download proxy (default: true)
      ENABLE_ALWAYS_ON_PROXY=true Start proxy at startup vs on-demand (default: true)
      PFW_PROXY_PORT=8080         Document proxy port (default: 8080)
      PROXY_PORT=8080             Fallback proxy port
    """
    import re

    from .main import _AUTH_PROVIDER, mcp
    from .middleware import (
        APIKeyAuthMiddleware,
        SecurityHeadersMiddleware,
        _StreamableHTTPProbeMiddleware,
    )

    logger.info("Starting Patent File Wrapper MCP server")

    transport = os.getenv("FASTMCP_TRANSPORT", "stdio")

    if transport == "http":
        # HTTP/SSE mode — for Docker, reverse proxy, or basic-host testing

        # Fail fast if INTERNAL_AUTH_SECRET is missing — open-access HTTP is a misconfiguration.
        # In STDIO mode this is fine (local process, no network exposure).
        # In OAuth mode the surface is bearer-protected by FastMCP instead, so
        # the shared-secret guard (and this check) is skipped.
        if _AUTH_PROVIDER is None:
            from .shared_secure_storage import get_internal_auth_secret
            _auth_secret_check = get_internal_auth_secret() or os.environ.get("INTERNAL_AUTH_SECRET")
            if not _auth_secret_check:
                logger.error(
                    "INTERNAL_AUTH_SECRET is required for HTTP transport mode. "
                    "Set it as an environment variable or store it via the key management system. "
                    "Refusing to start an unauthenticated HTTP server."
                )
                raise SystemExit(1)

        host = os.getenv("FASTMCP_HOST", "127.0.0.1")
        port = int(os.getenv("FASTMCP_PORT", "8000"))

        # Build CORS origins list
        origins = [f"http://localhost:{port}", f"http://127.0.0.1:{port}"]
        extra_origins = os.getenv("CORS_EXTRA_ORIGIN", "")
        for o in extra_origins.split(","):
            o = o.strip()
            if not o:
                continue
            if not re.match(r"^https?://[a-zA-Z0-9.\-]+(:[0-9]+)?$", o):
                raise ValueError(f"CORS_EXTRA_ORIGIN must be a valid HTTP/HTTPS URL, got: {o}")
            origins.append(o)
            logger.info(f"CORS: added extra origin {o}")

        try:
            from starlette.middleware.cors import CORSMiddleware
            import uvicorn
            # Middleware stack (outermost first): SecurityHeaders → CORS →
            # ProbeMiddleware → APIKeyAuth → mcp app.
            # CORS sits OUTSIDE auth (audit L10): browser OPTIONS preflights
            # carry no x-api-key, so with auth outside they 401'd before CORS
            # could answer — breaking legitimate browser clients. CORS
            # preflight responses carry no data, so answering them pre-auth
            # is safe. ProbeMiddleware stays outside auth for claude.ai
            # format probes; security headers wrap everything (401s too).
            def _wrap_cors(app_to_wrap):
                return CORSMiddleware(
                    app_to_wrap,
                    allow_origins=origins,
                    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
                    allow_headers=["Content-Type", "Accept", "Mcp-Session-Id"],
                    expose_headers=["Mcp-Session-Id"],
                )

            if _AUTH_PROVIDER is not None:
                # OAuth mode: FastMCP's bearer middleware guards /mcp (401 +
                # WWW-Authenticate — which already gives claude.ai's format
                # probe the 401 it needs, so the probe shim is redundant), and
                # the OAuth routes (/authorize, /token, /register, /auth/*,
                # /.well-known/*) must be reachable without a shared secret.
                # Headless clients present PFW_AUTH_INTERNAL_TOKEN as bearer.
                logger.warning(
                    "PFW_AUTH_MODE=oauth: x-api-key guard and probe shim "
                    "disabled; the MCP surface is protected by bearer tokens."
                )
                app = SecurityHeadersMiddleware(_wrap_cors(mcp.http_app()))
            else:
                app = SecurityHeadersMiddleware(
                    _wrap_cors(
                        _StreamableHTTPProbeMiddleware(
                            APIKeyAuthMiddleware(mcp.http_app())
                        )
                    )
                )
            # Start download proxy in a background daemon thread.
            # uvicorn.run() blocks, so the proxy must be in a separate thread.
            # This mirrors the STDIO hybrid-server pattern but without asyncio.run()
            # wrapping — each thread gets its own event loop via asyncio.run().
            _proxy_port_http = int(os.getenv('PFW_PROXY_PORT', os.getenv('PROXY_PORT', 8080)))
            _enable_proxy_http = os.getenv("ENABLE_ALWAYS_ON_PROXY", "true").lower() == "true"
            if _enable_proxy_http:
                import threading
                def _proxy_thread_target():
                    asyncio.run(_run_proxy_server(_proxy_port_http))
                _pt = threading.Thread(target=_proxy_thread_target, daemon=True, name="download-proxy")
                _pt.start()
                logger.info(f"Download proxy server starting on port {_proxy_port_http} (background thread)")
            logger.info(f"Starting HTTP transport on {host}:{port} (CORS origins: {origins})")
            # access_log off: access lines include request paths, and
            # /document/persistent/{hash} paths embed the link credential
            uvicorn.run(
                app, host=host, port=port, access_log=False,
                # Trust X-Forwarded-For only from these peers (audit M2)
                proxy_headers=True,
                forwarded_allow_ips=os.getenv("PROXY_TRUSTED_IPS", "127.0.0.1"),
            )
        except ImportError as e:
            raise ImportError(
                f"HTTP transport requires uvicorn and starlette: {e}. "
                "Run: uv add uvicorn starlette"
            )
    else:
        # STDIO mode (default) — Claude Desktop / Claude Code
        logger.info("Starting in STDIO mode with proxy support")
        enable_proxy = os.getenv("ENABLE_PROXY_SERVER", "true").lower() == "true"

        if enable_proxy:
            loop = asyncio.new_event_loop()
            loop.set_exception_handler(_asyncio_exception_handler)
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(run_hybrid_server())
            finally:
                loop.close()
        else:
            logger.info("Proxy server disabled via ENABLE_PROXY_SERVER=false")
            mcp.run(transport="stdio")

