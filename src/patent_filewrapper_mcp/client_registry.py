"""Per-event-loop EnhancedPatentClient registry (audit F2/F28).

Owns the lazily-initialized client so main.py and the tools/ package do not
need import-cycle gymnastics. main.py re-exports these names for backward
compatibility.

ONE CLIENT PER EVENT LOOP. This server runs two loops in two threads —
FastMCP's and the :8080 download proxy's (`server_bootstrap.py:139-152` for
stdio, `:303-315` for http) — and a single client object was handed to both.
`EnhancedPatentClient` carries an `asyncio.Semaphore`, which is not
thread-safe and binds to the first loop that WAITS on it: the release runs on
the holder's loop and calls `set_result` on a future belonging to the other
loop with no `call_soon_threadsafe`, so the waiter never wakes. With
`MAX_CONCURRENT_REQUESTS = 10` the uncontended path never touches that
machinery, which is why it read as an intermittent hang under load rather
than a startup failure. The same object also carried unsynchronized
`CircuitBreaker`, `ResponseCache` and `RetryBudget` state across threads.

This deliberately REVERSES "audit F5" (one shared client so resilience state
agrees). Shared state across two loops is not worth a hang; the proxy's
resilience counters are reported on its own health route.
"""
import asyncio
from typing import Any, Dict, Optional

from .api.enhanced_client import EnhancedPatentClient
from .shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)

#: Registry key for a caller with no running event loop (import time,
#: synchronous helpers). Its client is the one `api_client` below holds.
_NO_LOOP = "no-running-loop"

# Clients keyed by the loop that created them. Both loops in this process
# live for its whole lifetime, so holding a reference to them is not a leak;
# `reset_api_client()` clears the table for tests.
_clients: Dict[Any, EnhancedPatentClient] = {}
_api_client_error: Optional[Exception] = None


def _loop_key() -> Any:
    """The running event loop, or `_NO_LOOP` for a synchronous caller."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return _NO_LOOP


def reset_api_client() -> None:
    """Drop every cached client AND the cached initialization failure.

    The failure used to be cached for the life of the process, so a transient
    secure-store read error at the first call permanently disabled the client
    even after the operator fixed the configuration.
    """
    global api_client, _api_client_error
    _clients.clear()
    _api_client_error = None
    api_client = None


def get_api_client() -> EnhancedPatentClient:
    """
    Get this event loop's API client, creating it on first use.

    Returns:
        EnhancedPatentClient instance bound to the running loop

    Raises:
        Exception: If API client cannot be initialized (with helpful error
            message). Call `reset_api_client()` to retry after fixing the
            configuration.
    """
    global _api_client_error

    key = _loop_key()
    existing = _clients.get(key)
    if existing is not None:
        return existing

    # If we've already failed once, return cached error
    if _api_client_error is not None:
        logger.error(
            "API client initialization previously failed - check configuration "
            "(reset_api_client() clears this)"
        )
        raise _api_client_error

    try:
        logger.info("Initializing USPTO API client...")
        client = EnhancedPatentClient()
        _clients[key] = client
        logger.info("USPTO API client initialized successfully")
        return client
    except Exception as e:
        # Cache the error to avoid repeated failed attempts
        _api_client_error = Exception(
            f"Failed to initialize USPTO API client: {str(e)}. "
            f"Please check:\n"
            f"  1. USPTO_API_KEY environment variable is set\n"
            f"  2. API key is valid (get one from developer.uspto.gov)\n"
            f"  3. Network connectivity to USPTO API\n"
            f"Original error: {type(e).__name__}: {str(e)}"
        )
        logger.exception(f"Failed to initialize API client: {e}")
        raise _api_client_error


# Get initial API client for package manager (with fallback)
try:
    api_client = get_api_client()
except Exception as e:
    logger.warning(f"Could not initialize API client at startup: {e}")
    logger.warning("API client will be initialized on first use")
    api_client = None

#: What `api_client` was at import. Anything else in that name is an
#: INJECTED client (tests do `monkeypatch.setattr(client_registry,
#: "api_client", fake)`), which `_client()` honors verbatim.
_startup_client = api_client


def _client() -> EnhancedPatentClient:
    """Single lazy-init seam for the API client (audit F28): replaces six
    per-tool `global api_client` boilerplate blocks and is the one place a
    test can inject a fake client.

    An injected client wins. Otherwise this resolves through
    `get_api_client()`, so a coroutine gets ITS OWN loop's client rather than
    whichever one import time happened to build on no loop at all.
    """
    global api_client
    if api_client is not None and api_client is not _startup_client:
        return api_client
    client = get_api_client()
    if api_client is None:
        api_client = client
    return client
