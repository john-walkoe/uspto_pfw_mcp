"""HTTP transport for the USPTO Patent File Wrapper API (audit F3 split).

Single owner of the outbound call path: concurrency semaphore, retry loop
with jitter, circuit breaker, response cache, and retry budget.
EnhancedPatentClient composes one of these and delegates _make_request;
the OA clients keep their own lighter retry (different base URLs and
form-encoded POSTs — see api/oa_base.py).
"""
import asyncio
import random
from typing import Any, Dict

import httpx

from ..shared.safe_logger import get_safe_logger
from ..shared.uspto_shared_rate_limiter import get_shared_limiter
from .helpers import create_error_response, format_error_response, generate_request_id
from .resilience import CircuitBreaker, ResponseCache, RetryBudget

logger = get_safe_logger(__name__)


class USPTOTransport:
    """Resilient HTTP layer for USPTO ODP endpoints."""

    MAX_CONCURRENT_REQUESTS = 10

    # Retry configuration
    RETRY_ATTEMPTS = 3
    RETRY_DELAY = 1.0  # Base delay in seconds
    RETRY_BACKOFF = 2  # Exponential backoff multiplier

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

        # Rate limiting to prevent DoS - limit concurrent requests
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
        send.
        """
        async with httpx.AsyncClient(timeout=self.default_timeout, limits=self.api_limits, verify=True) as client:
            if method.upper() == "POST":
                send = client.post(url, headers=self.headers, **kwargs)
            else:
                send = client.get(url, headers=self.headers, **kwargs)
            limiter = get_shared_limiter()
            if limiter is not None:
                async with limiter:
                    return await send
            return await send

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

        # Rate limiting: acquire semaphore before making request
        async with self.semaphore:
            last_exception = None

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
                    # Don't retry authentication errors or client errors (4xx)
                    if e.response.status_code < 500:
                        # Status only — response bodies stay out of logs
                        # (the returned error keeps the API detail for the user)
                        logger.error(f"[{request_id}] API error {e.response.status_code}")
                        # DO NOT record 4xx as circuit breaker failures - they are valid client error responses
                        # Circuit breaker should only open for 5xx errors (server failures) and timeouts
                        # 4xx errors (404 Not Found, 400 Bad Request, etc.) are expected responses, not API failures
                        return format_error_response(f"API error: {e.response.text}", e.response.status_code, request_id)
                    last_exception = e

                except httpx.TimeoutException as e:
                    last_exception = e

                except Exception as e:
                    # Don't retry unexpected errors on final attempt
                    if attempt == self.RETRY_ATTEMPTS - 1:
                        logger.error(f"[{request_id}] Request failed: {str(e)}")
                        return format_error_response(f"Request failed: {str(e)}", 500, request_id)
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
                logger.error(f"[{request_id}] Request failed after {self.RETRY_ATTEMPTS} attempts: {str(last_exception)}")
                return format_error_response(f"Request failed: {str(last_exception)}", 500, request_id)
