"""Health, cache-admin, stats, and recent-downloads routes for the PFW proxy
(carved out of create_proxy_app() — audit F4)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
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
            "status": "healthy" if budget_utilization < 80 else "degraded" if budget_utilization < 95 else "unhealthy",
            "retries_used": budget_stats["retries_used"],
            "retries_remaining": budget_stats["retries_remaining"],
            "max_retries_per_hour": budget_stats["max_retries_per_hour"],
            "utilization": f"{budget_utilization:.1f}%"
        }

        # Mark overall health as degraded if retry budget is nearly exhausted
        if budget_utilization >= 95:
            overall_healthy = False
    else:
        health_data["components"]["api_client"] = {"status": "unhealthy", "reason": "Not initialized"}
        overall_healthy = False

    # Database health check
    try:
        from ...util.database import create_secure_connection
        import os
        import tempfile

        # Test database connectivity with temporary database
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_db:
            tmp_db_path = tmp_db.name

        try:
            conn = create_secure_connection(tmp_db_path, timeout=5.0)
            conn.execute("SELECT 1").fetchone()
            conn.close()
            os.unlink(tmp_db_path)

            health_data["components"]["database"] = {
                "status": "healthy",
                "message": "SQLite connectivity verified"
            }
        except Exception as db_error:
            health_data["components"]["database"] = {
                "status": "unhealthy",
                "error": str(db_error)
            }
            overall_healthy = False
            # Clean up temp file if exists
            if os.path.exists(tmp_db_path):
                os.unlink(tmp_db_path)

    except Exception as e:
        health_data["components"]["database"] = {
            "status": "unknown",
            "error": f"Health check failed: {str(e)}"
        }

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
    except Exception as e:
        logger.error(f"Error getting cache stats: {e}")
        return {"error": str(e)}

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
    except Exception as e:
        logger.error(f"Error during cache cleanup: {e}")
        return {"error": str(e)}


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


@router.get("/ptab-stats")
async def get_ptab_stats():
    """Get PTAB document store statistics for monitoring"""
    try:
        ptab_store = get_ptab_store()
        return ptab_store.get_statistics()
    except Exception as e:
        logger.error(f"Error getting PTAB stats: {e}")
        return {"error": str(e)}

@router.get("/fpd-stats")
async def get_fpd_stats():
    """Get FPD document store statistics for monitoring"""
    try:
        fpd_store = get_fpd_store()
        return fpd_store.get_statistics()
    except Exception as e:
        logger.error(f"Error getting FPD stats: {e}")
        return {"error": str(e)}


@router.get("/api/recent-downloads", dependencies=[Depends(_check_proxy_token)])
async def get_recent_downloads():
    """Return the last 10 documents generated via pfw_get_document_download
    or pfw_get_granted_patent_documents_download.

    Token-gated (audit C2): each entry contains a working
    /document/persistent/{hash} credential, so this must not be an
    anonymous endpoint. The Recent Downloads MCP App iframe populates
    from tool results and degrades gracefully when this fetch 401s.

    Returns JSON array of download entries (newest first).
    """
    from ..recent_downloads_store import get_recent
    return get_recent()

@router.post("/api/register-download", dependencies=[Depends(_check_proxy_token)])
async def post_register_download(request: Request):
    """Register a download entry from the MCP tool process.

    Called by pfw_get_document_download and pfw_get_granted_patent_documents_download
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
    )
    logger.info("register-download: registered '%s' for app %s", payload.get("title"), payload.get("app_number"))
    return {"ok": True}
