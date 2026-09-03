"""Health, cache-admin, stats, and recent-downloads routes for the PFW proxy
(carved out of create_proxy_app() — audit F4)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
import os
import time

from ...shared.safe_logger import get_safe_logger
from ..fpd_document_store import get_fpd_store
from ..ptab_document_store import get_ptab_store
from ..rate_limiter import rate_limiter

from .. import server as _server
from ..server import (
    _check_proxy_token,
)

logger = get_safe_logger(__name__)

router = APIRouter()

#: Capacity thresholds for the health report, named because the numbers encode
#: a policy rather than a fact (audit R-7).
_CAPACITY_WARN_PCT = 80
_CAPACITY_CRITICAL_PCT = 95


def _database_health() -> dict:
    """Probe the databases whose failure would actually break the service.

    Read-only and best-effort: a store that has never been written to has no
    file yet, which is healthy, not broken.
    """
    import os

    from ...util.database import create_secure_connection

    candidates = {
        "auth": os.getenv("PFW_AUTH_DB_PATH", "data/mcp_auth.db"),
    }
    try:
        from ..secure_link_cache import get_link_cache

        candidates["link_cache"] = get_link_cache().db_path
    except Exception:
        pass

    checked = []
    for name, path in candidates.items():
        if not path or not os.path.exists(path):
            continue
        try:
            conn = create_secure_connection(path, timeout=5.0)
            try:
                conn.execute("SELECT 1").fetchone()
            finally:
                conn.close()
            checked.append(name)
        except Exception:
            # Path only; the exception text can carry the filesystem layout.
            logger.exception(f"Database health check failed for {name}")
            return {"status": "unhealthy", "database": name}

    return {
        "status": "healthy",
        "checked": checked or ["none present yet"],
    }


@router.get("/")
async def health_check():
    """
    Enhanced health check endpoint with component status

    Returns health status of all system components including:
    - Circuit breaker state
    - Database connectivity
    - Response cache statistics
    - Retry budget tracking
    """
    health_data = {
        "service": "USPTO Document Proxy",
        "timestamp": time.time(),
        "components": {}
    }

    overall_healthy = True

    # Circuit breaker health
    if _server.api_client:
        cb_state = _server.api_client.circuit_breaker.state.value
        cb_failures = _server.api_client.circuit_breaker.failure_count

        health_data["components"]["circuit_breaker"] = {
            "status": "healthy" if cb_state == "closed" else "degraded" if cb_state == "half_open" else "unhealthy",
            "state": cb_state,
            "failure_count": cb_failures,
            "threshold": _server.api_client.circuit_breaker.failure_threshold
        }

        if cb_state == "open":
            overall_healthy = False

        # Response cache statistics
        cache_stats = _server.api_client.response_cache.get_stats()
        health_data["components"]["response_cache"] = {
            "status": "healthy",
            "size": cache_stats["size"],
            "max_size": cache_stats["max_size"],
            "utilization": f"{(cache_stats['size'] / cache_stats['max_size'] * 100):.1f}%"
        }

        # Retry budget statistics
        budget_stats = _server.api_client.retry_budget.get_stats()
        budget_utilization = budget_stats["utilization_percent"]
        health_data["components"]["retry_budget"] = {
            "status": "healthy" if budget_utilization < _CAPACITY_WARN_PCT else "degraded" if budget_utilization < _CAPACITY_CRITICAL_PCT else "unhealthy",
            "retries_used": budget_stats["retries_used"],
            "retries_remaining": budget_stats["retries_remaining"],
            "max_retries_per_hour": budget_stats["max_retries_per_hour"],
            "utilization": f"{budget_utilization:.1f}%"
        }

        # Mark overall health as degraded if retry budget is nearly exhausted
        if budget_utilization >= _CAPACITY_CRITICAL_PCT:
            overall_healthy = False
    else:
        health_data["components"]["api_client"] = {"status": "unhealthy", "reason": "Not initialized"}
        overall_healthy = False

    # Database health check. This used to create a NEW temporary SQLite file,
    # SELECT 1 from it and unlink it, which verifies that the SQLite library
    # works — always true — and never touched a database whose failure would
    # actually break the service (audit resilience F-7). It now opens the real
    # ones read-only.
    health_data["components"]["database"] = _database_health()
    if health_data["components"]["database"]["status"] != "healthy":
        overall_healthy = False

    # Which backend actually served each encryption key. backend_available()
    # returns False in the containers this ships to, so the 0600-file fallback
    # is the live path there and an operator otherwise has no way to tell
    # (audit M-9). Backend NAMES only — never a key, never a path.
    try:
        from ...shared.fernet_key_store import active_key_backends

        backends = active_key_backends()
        health_data["components"]["key_storage"] = {
            "status": "healthy",
            "backends": backends or {"note": "no keys resolved yet"},
            "degraded_to_file": [
                name for name, backend in backends.items() if backend == "file"
            ],
        }
    except Exception:
        logger.exception("Key-backend health check failed")

    # Alert counter: distinguishes "no alerts have fired" from "alerts fire
    # but nothing leaves the box", which was indistinguishable before M-17.
    try:
        from ...util.security_logger import security_logger

        health_data["components"]["security_alerts"] = {
            "status": "healthy",
            "alerts_sent": security_logger.alerts_sent,
            "transport_configured": bool(
                os.getenv("PFW_ALERT_WEBHOOK_URL") or os.getenv("PFW_ALERT_LOG_PATH")
            ),
        }
    except Exception:
        logger.exception("Alert-counter health check failed")

    # Set overall status
    health_data["status"] = "healthy" if overall_healthy else "degraded"

    # Return appropriate HTTP status code
    status_code = 200 if overall_healthy else 503

    return JSONResponse(content=health_data, status_code=status_code)


@router.get("/cache/stats", dependencies=[Depends(_check_proxy_token)])
async def get_cache_stats():
    """Get persistent link cache statistics for monitoring"""
    try:
        from ..secure_link_cache import get_link_cache
        link_cache = get_link_cache()
        return link_cache.get_cache_stats()
    except Exception:
        # Was HTTP 200 with the raw exception text. The proxy's own
        # general_exception_handler already produces a 500 with a request id
        # and a dev/prod gate (audit M-6, error-handling F-2).
        logger.exception("Error getting cache stats")
        raise

@router.post("/cache/cleanup", dependencies=[Depends(_check_proxy_token)])
async def cleanup_expired_links():
    """Clean up expired persistent links"""
    try:
        from ..secure_link_cache import get_link_cache
        link_cache = get_link_cache()
        deleted_count = link_cache.cleanup_expired_links()
        return {
            "success": True,
            "deleted_links": deleted_count,
            "message": f"Cleaned up {deleted_count} expired links"
        }
    except Exception:
        # Was HTTP 200 with the raw exception text. The proxy's own
        # general_exception_handler already produces a 500 with a request id
        # and a dev/prod gate (audit M-6, error-handling F-2).
        logger.exception("Error during cache cleanup")
        raise


@router.get("/rate-limit/{client_ip}", dependencies=[Depends(_check_proxy_token)])
async def check_rate_limit(client_ip: str):
    """Check rate limit status for a client IP"""
    return {
        "client_ip": client_ip,
        "remaining_requests": rate_limiter.get_remaining_requests(client_ip),
        "max_requests": rate_limiter.max_requests,
        "time_window": rate_limiter.time_window,
        "reset_time": rate_limiter.get_reset_time(client_ip)
    }


@router.get("/ptab-stats", dependencies=[Depends(_check_proxy_token)])
async def get_ptab_stats():
    """Get PTAB document store statistics for monitoring"""
    try:
        ptab_store = get_ptab_store()
        return ptab_store.get_statistics()
    except Exception:
        # Was HTTP 200 with the raw exception text. The proxy's own
        # general_exception_handler already produces a 500 with a request id
        # and a dev/prod gate (audit M-6, error-handling F-2).
        logger.exception("Error getting PTAB stats")
        raise

@router.get("/fpd-stats", dependencies=[Depends(_check_proxy_token)])
async def get_fpd_stats():
    """Get FPD document store statistics for monitoring"""
    try:
        fpd_store = get_fpd_store()
        return fpd_store.get_statistics()
    except Exception:
        # Was HTTP 200 with the raw exception text. The proxy's own
        # general_exception_handler already produces a 500 with a request id
        # and a dev/prod gate (audit M-6, error-handling F-2).
        logger.exception("Error getting FPD stats")
        raise


@router.get("/api/recent-downloads", dependencies=[Depends(_check_proxy_token)])
async def get_recent_downloads(request: Request):
    """Return the last 10 documents generated via PFW_get_document_download
    or PFW_get_granted_patent_documents_download.

    Token-gated (audit C2): each entry contains a working
    /document/persistent/{hash} credential, so this must not be an
    anonymous endpoint. The Recent Downloads MCP App iframe populates
    from tool results and degrades gracefully when this fetch 401s.

    Scoped to ONE owner (audit M-3): a single process-global list handed
    every caller the last ten documents any caller had fetched, with their
    application numbers and titles. Outside OAuth mode there is one owner and
    the behavior is unchanged.

    Returns JSON array of download entries (newest first).
    """
    from ..recent_downloads_store import get_recent
    return get_recent(owner=request.headers.get("x-download-owner"))

@router.post("/api/register-download", dependencies=[Depends(_check_proxy_token)])
async def post_register_download(request: Request):
    """Register a download entry from the MCP tool process.

    Called by PFW_get_document_download and PFW_get_granted_patent_documents_download
    via HTTP so the registration works whether the proxy is in-process or a
    separately-running instance (e.g. ENABLE_ALWAYS_ON_PROXY=true across sessions).
    """
    from ..recent_downloads_store import register_download
    payload = await request.json()
    register_download(
        title=payload.get("title", "Document"),
        doc_type=payload.get("doc_type", ""),
        app_number=payload.get("app_number", ""),
        proxy_url=payload.get("proxy_url", ""),
        filename=payload.get("filename"),
        # The tool process passes its identity through when it has one; the
        # header, not the body, so a caller cannot claim another owner's
        # bucket by editing the JSON it posts.
        owner=request.headers.get("x-download-owner"),
    )
    logger.info("register-download: registered '%s' for app %s", payload.get("title"), payload.get("app_number"))
    return {"ok": True}
