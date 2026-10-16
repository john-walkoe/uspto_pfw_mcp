"""HTTP transport for the USPTO Patent File Wrapper API (audit F3 split).

Single owner of the outbound call path: concurrency semaphore, retry loop
with jitter, circuit breaker, response cache, and retry budget.
EnhancedPatentClient composes one of these and delegates _make_request;
the OA clients keep their own lighter retry (different base URLs and
form-encoded POSTs — see api/oa_base.py).
"""
import asyncio
import random
import time
from typing import Any, Dict

import httpx

from ..shared.safe_logger import get_safe_logger
from ..shared.uspto_hosts import USPTO_KEY_EVENT_HOOKS
from ..shared.uspto_shared_rate_limiter import (
    SharedLimiterTimeoutError,
    get_shared_limiter,
    note_429,
)
from .helpers import (
    RATE_LIMIT_SOURCE_SHARED_LIMITER,
    RATE_LIMIT_SOURCE_UPSTREAM,
    create_error_response,
    format_error_response,
    generate_request_id,
    planned_429_wait,
    rate_limited_response,
    retry_after_from,
)
from .resilience import CircuitBreaker, ResponseCache, RetryBudget

logger = get_safe_logger(__name__)


class USPTOTransport:
    """Resilient HTTP layer for USPTO ODP endpoints."""

    #: Local in-memory bulkhead for THIS process only (keeps one burst of
    #: tool calls from opening unbounded connections). It is not the USPTO
    #: limit: burst 1 per key and cross-process fairness are the shared FIFO
    #: limiter's job (shared/uspto_shared_rate_limiter.py).
    MAX_CONCURRENT_REQUESTS = 10

    # Retry configuration
    RETRY_ATTEMPTS = 3
    RETRY_DELAY = 1.0  # Base delay in seconds
    RETRY_BACKOFF = 2  # Exponential backoff multiplier

    #: HTTP 429. Handled apart from the other 4xx because it is the one client
    #: error where the caller did nothing wrong and waiting is the whole fix.
    RATE_LIMIT_STATUS = 429

    def __init__(
        self,
        base_url: str,
        headers: Dict[str, str],
        default_timeout: float,
        api_limits: httpx.Limits,
        max_retries_per_hour: int = 100,
    ):
        self.base_url = base_url
        self.headers = headers
        self.default_timeout = default_timeout
        self.api_limits = api_limits

        # Local bulkhead (see MAX_CONCURRENT_REQUESTS); not a rate limit
        self.semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_REQUESTS)
        # Circuit breaker for API resilience
        self.circuit_breaker = CircuitBreaker(failure_threshold=3, timeout=30)
        # Response cache for resilience during circuit breaker open state
        self.response_cache = ResponseCache(ttl_seconds=300, max_size=100)
        # Retry budget for quota protection (prevent API quota exhaustion)
        self.retry_budget = RetryBudget(max_retries_per_hour=max_retries_per_hour)

    async def _send_once(self, method: str, url: str, **kwargs) -> "httpx.Response":
        """Perform exactly one HTTP send. Extracted out of request()'s retry
        loop into its own method (rather than a nested closure) so its
        branches are counted toward ITS OWN cyclomatic complexity instead of
        request()'s — mechanical decomposition, no behavior change.

        Shared cross-process rate limiter (token + concurrency slot), one
        acquire per ATTEMPT — off unless USPTO_SHARED_RATE_LIMIT_DIR is set.
        This is the single choke point around the actual outbound USPTO HTTP
        send. USPTO_KEY_EVENT_HOOKS (shared/uspto_hosts.py) strip the key off
        any non-uspto.gov hop.
        """
        async with httpx.AsyncClient(
            timeout=self.default_timeout, limits=self.api_limits, verify=True,
            event_hooks=USPTO_KEY_EVENT_HOOKS,
        ) as client:
            if method.upper() == "POST":
                send = client.post(url, headers=self.headers, **kwargs)
            else:
                send = client.get(url, headers=self.headers, **kwargs)
            limiter = get_shared_limiter()
            if limiter is not None:
                async with limiter:
                    return await send
            return await send

    async def _absorb_429(
        self,
        response: "httpx.Response",
        already_retried: bool,
        remaining_budget: float,
        request_id: str,
    ) -> "Dict[str, Any] | None":
        """The 429 rule (helpers.planned_429_wait) applied to one
        429 response: note it on the shared key cooldown, then either sleep
        the single allowed wait and return None (the caller sends once more)
        or return the rate-limit envelope. No shared slot is held here:
        `_send_once` released it when the response came back.

        A method rather than inline branches for the same reason `_send_once`
        is one: `request` carries a pre-existing C901 flag and this work must
        not grow it.
        """
        retry_after = retry_after_from(response)
        note_429(retry_after)
        wait = planned_429_wait(retry_after, already_retried, remaining_budget)
        if wait is None:
            logger.error(f"[{request_id}] Rate limited by USPTO (429); answering with the envelope")
            return rate_limited_response(
                retry_after_seconds=retry_after,
                source=RATE_LIMIT_SOURCE_UPSTREAM,
                request_id=request_id,
            )
        logger.warning(f"[{request_id}] Rate limited (429); one retry in {wait:.0f}s")
        await asyncio.sleep(wait)
        return None

    async def _handle_client_error(
        self,
        response: "httpx.Response",
        already_retried: bool,
        remaining_budget: float,
        request_id: str,
    ) -> "Dict[str, Any] | None":
        """The whole 4xx decision, in one place off `request`'s hot path.

        Returns the response to hand back, or None meaning "the single 429
        wait was absorbed, send once more". Every 4xx branch lives here
        together: `request` carries a pre-existing C901 flag, and adding 429
        handling beside the existing `< 500` block would have grown it. This
        keeps one exit for client errors.
        """
        if response.status_code == self.RATE_LIMIT_STATUS:
            return await self._absorb_429(
                response, already_retried, remaining_budget, request_id
            )

        # Status only — response bodies stay out of logs (the returned error
        # keeps the API detail for the user).
        logger.error(f"[{request_id}] API error {response.status_code}")
        return format_error_response(
            f"API error: {response.text}", response.status_code, request_id
        )

    async def request(self, endpoint: str, method: str = "GET", **kwargs) -> Dict[str, Any]:
        """Make HTTP request to Patent File Wrapper API with rate limiting and retry logic"""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        request_id = generate_request_id()

        # Check circuit breaker first
        if not self.circuit_breaker.can_execute():
            logger.warning(f"[{request_id}] Request blocked by circuit breaker (state: {self.circuit_breaker.state.value})")

            # Try to serve from cache when circuit breaker is open
            cached = self.response_cache.get(endpoint, **kwargs)
            if cached:
                logger.info(f"[{request_id}] Serving cached response (circuit breaker open)")
                # Mark response as coming from cache
                cached_response = cached.copy()
                cached_response["_cache_hit"] = True
                cached_response["_cached_at"] = "Circuit breaker active - serving stale data"
                cached_response["_circuit_breaker_state"] = self.circuit_breaker.state.value
                return cached_response

            logger.warning(f"[{request_id}] No cached response available for failover")
            return format_error_response(
                "USPTO API is temporarily unavailable. No cached data available.",
                503,  # Service Unavailable
                request_id
            )

        logger.info(f"[{request_id}] Starting {method} request to {endpoint}")

        # Local bulkhead: acquire the in-process semaphore before sending
        async with self.semaphore:
            last_exception = None
            # At most ONE 429 retry per request. A 429 answered by
            # waiting and sending again is pacing; a LOOP of them is the hang.
            # The wait's budget is the request timeout counted from here.
            retried_429 = False
            budget = float(kwargs.get("timeout") or self.default_timeout)
            call_started = time.monotonic()

            for attempt in range(self.RETRY_ATTEMPTS):
                try:
                    response = await self._send_once(method, url, **kwargs)

                    response.raise_for_status()
                    logger.info(f"[{request_id}] Request successful on attempt {attempt + 1}")

                    # Record success for circuit breaker
                    self.circuit_breaker.record_success()

                    # Cache successful response for resilience
                    response_data = response.json()
                    self.response_cache.set(endpoint, response_data, **kwargs)

                    return response_data

                except httpx.HTTPStatusError as e:
                    # Don't retry authentication errors or client errors (4xx).
                    # DO NOT record 4xx as circuit breaker failures - they are valid client error responses
                    # Circuit breaker should only open for 5xx errors (server failures) and timeouts
                    # 4xx errors (404 Not Found, 400 Bad Request, etc.) are expected responses, not API failures
                    if e.response.status_code < 500:
                        outcome = await self._handle_client_error(
                            e.response, retried_429,
                            budget - (time.monotonic() - call_started),
                            request_id,
                        )
                        if outcome is None:  # the single 429 wait was absorbed
                            retried_429 = True
                            continue
                        return outcome
                    last_exception = e

                except httpx.TimeoutException as e:
                    last_exception = e

                except SharedLimiterTimeoutError:
                    # The shared cross-process limiter gave up acquiring a
                    # slot or a token (USPTO_SHARED_MAX_WAIT_SECONDS, 45 s by
                    # default). RETRYING that is the hang: three attempts of
                    # up to the ceiling each, plus backoff, is well past the
                    # client's patience and it reports the connector as not
                    # responding. The key is busy or cooling down NOW, so
                    # answer now and let the caller pace itself. httpx
                    # timeouts are httpx.TimeoutException, caught above.
                    logger.error(
                        f"[{request_id}] Shared USPTO rate limiter did not "
                        f"admit the request; returning without retrying"
                    )
                    return rate_limited_response(
                        source=RATE_LIMIT_SOURCE_SHARED_LIMITER,
                        request_id=request_id,
                        message=(
                            "Rate limited by this deployment's shared USPTO "
                            "limiter. Retry this call once after "
                            "retry_after_seconds."
                        ),
                    )

                except Exception as e:
                    # Don't retry unexpected errors on final attempt
                    if attempt == self.RETRY_ATTEMPTS - 1:
                        logger.exception(f"[{request_id}] Request failed ({type(e).__name__})")
                        # Sanitized for the caller; the exception detail rides
                        # the `exception=` seam, which format_error_response
                        # reveals only in a development environment.
                        return format_error_response(
                            "Request failed", 500, request_id, exception=e
                        )
                    last_exception = e

                # Calculate delay with exponential backoff and jitter
                if attempt < self.RETRY_ATTEMPTS - 1:
                    # Check retry budget before retrying
                    if not self.retry_budget.can_retry():
                        logger.error(
                            f"[{request_id}] Retry budget exhausted after attempt {attempt + 1}. "
                            f"Aborting further retries to prevent quota exhaustion."
                        )
                        # Break out of retry loop - budget exhausted
                        break

                    # Record this retry in the budget
                    self.retry_budget.record_retry()

                    delay = self.RETRY_DELAY * (self.RETRY_BACKOFF ** attempt)
                    # Add jitter to prevent thundering herd
                    jitter = random.uniform(0.1, 0.5)
                    total_delay = delay + jitter

                    logger.warning(f"[{request_id}] Request failed on attempt {attempt + 1}/{self.RETRY_ATTEMPTS}, "
                                 f"retrying in {total_delay:.2f}s: {str(last_exception)}")
                    await asyncio.sleep(total_delay)

            # All retries failed - record failure for circuit breaker
            self.circuit_breaker.record_failure()

            if isinstance(last_exception, httpx.TimeoutException):
                logger.error(f"[{request_id}] Request timeout after {self.RETRY_ATTEMPTS} attempts")
                return create_error_response("api_timeout", request_id=request_id)
            elif isinstance(last_exception, httpx.HTTPStatusError):
                logger.error(f"[{request_id}] API error {last_exception.response.status_code} after {self.RETRY_ATTEMPTS} attempts")
                if last_exception.response.status_code in [401, 403]:
                    return create_error_response("api_auth_failed", request_id=request_id, status_code=last_exception.response.status_code)
                else:
                    return format_error_response(f"API error: {last_exception.response.text}", last_exception.response.status_code, request_id)
            else:
                logger.error(
                    f"[{request_id}] Request failed after {self.RETRY_ATTEMPTS} attempts "
                    f"({type(last_exception).__name__})"
                )
                return format_error_response(
                    "Request failed", 500, request_id, exception=last_exception
                )
