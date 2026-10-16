"""Shared base for the Office Action API client (audits F19/F23).

Since 2026-10-11 the one subclass is api/office_action_client.py (the ODP
Office Action API, /api/v1/patent/office-action). The retired OA
rejections/text clients this was written for previously made single unprotected httpx
calls (no retry, no typed errors, hardcoded timeouts) while the primary
USPTO path had full resilience. This base gives the client:
- typed AuthenticationError instead of bare ValueError for a missing key
- a bounded retry loop with exponential backoff on transient failures
  (5xx, timeouts, connection errors) — never on 4xx
- env-configurable timeout (USPTO_OA_TIMEOUT) and retry cap
  (USPTO_OA_MAX_RETRIES)
- the transport's 429 rule: the 429 is noted on the
  shared key cooldown, then one retry after max(5 s, Retry-After) when that
  wait is at most 10 s and fits the call's budget; anything else raises
  UpstreamRateLimitedError carrying the same `rate_limited_response`
  envelope USPTOTransport returns, instead of an HTTPStatusError the tool
  restated as a generic failure. The shared limiter's refusal
  (SharedLimiterTimeoutError) raises the same error at once, no retry
- USPTO_KEY_EVENT_HOOKS (shared/uspto_hosts.py): drops the API key from any
  hop that is not https on uspto.gov
"""
import asyncio
import os
import time
from typing import Any, Dict, Optional, Tuple

import httpx

from ..exceptions import AuthenticationError, UpstreamRateLimitedError, USPTOAPIError
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
    planned_429_wait,
    rate_limited_response,
    retry_after_from,
)

logger = get_safe_logger(__name__)


class OAClientBase:
    """Common auth, timeout, and retry behavior for OA API clients."""

    #: HTTP 429: the one client error where waiting is the whole fix.
    RATE_LIMIT_STATUS = 429

    def __init__(self, api_key: Optional[str] = None, timeout: Optional[float] = None):
        self.api_key = api_key or os.getenv("USPTO_API_KEY", "")
        if not self.api_key:
            raise AuthenticationError("USPTO_API_KEY environment variable is required")
        self.timeout = timeout if timeout is not None else float(os.getenv("USPTO_OA_TIMEOUT", "30.0"))
        self.max_retries = max(0, int(os.getenv("USPTO_OA_MAX_RETRIES", "2")))

    def _headers(self) -> Dict[str, str]:
        return {"X-API-KEY": self.api_key}

    async def _send_once(self, client: httpx.AsyncClient, method: str, url: str, **kwargs) -> httpx.Response:
        """Perform exactly one HTTP send, gated by the shared cross-process
        rate limiter (token + concurrency slot) — off unless
        USPTO_SHARED_RATE_LIMIT_DIR is set. Called once per retry ATTEMPT
        from _request_response's loop; the OA APIs are api.uspto.gov ODP
        endpoints under the same per-key limits as the primary PFW path."""
        send = client.request(method, url, headers=self._headers(), **kwargs)
        limiter = get_shared_limiter()
        if limiter is not None:
            async with limiter:
                return await send
        return await send

    @classmethod
    async def _absorb_429(
        cls, resp: httpx.Response, already_retried: bool, remaining_budget: float
    ) -> bool:
        """The transport's 429 rule (helpers.planned_429_wait): note the 429
        on the shared key cooldown, then True when the single wait was
        absorbed (send once more); otherwise raise the rate-limit envelope.
        No shared slot is held here: _send_once released it on return."""
        retry_after = retry_after_from(resp)
        note_429(retry_after)
        wait = planned_429_wait(retry_after, already_retried, remaining_budget)
        if wait is not None:
            logger.warning(f"OA API rate limited (429); one retry in {wait:.0f}s")
            await asyncio.sleep(wait)
            return True
        logger.error("OA API rate limited by USPTO (429); answering with the envelope")
        raise UpstreamRateLimitedError(rate_limited_response(
            retry_after_seconds=retry_after,
            source=RATE_LIMIT_SOURCE_UPSTREAM,
        ))

    async def _request_response(
        self, method: str, url: str, *, allow_status: Tuple[int, ...] = (), **kwargs
    ) -> httpx.Response:
        """One OA API call with bounded retry on transient failures; returns
        the response itself so a caller can read JSON or plain text.

        A 429 is not a transient failure to retry blind: the single 429 wait
        is absorbed once (without spending a retry), anything else raises
        UpstreamRateLimitedError (see `_absorb_429`). The shared limiter's
        refusal raises the same error at once, no retry. Statuses listed in
        `allow_status` (e.g. the Office Action API's "no matching records"
        404) come back to the caller instead of raising."""
        last_exc: Optional[Exception] = None
        retried_429 = False
        # The single 429 wait's budget: this client's timeout, from here.
        call_started = time.monotonic()
        attempt = 0
        while attempt <= self.max_retries:
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout, event_hooks=USPTO_KEY_EVENT_HOOKS
                ) as client:
                    resp = await self._send_once(client, method, url, **kwargs)
                    if resp.status_code == self.RATE_LIMIT_STATUS:
                        retried_429 = await self._absorb_429(
                            resp, retried_429,
                            self.timeout - (time.monotonic() - call_started),
                        )
                        continue
                    if resp.status_code in allow_status:
                        return resp
                    if resp.status_code >= 500:
                        raise USPTOAPIError(f"OA API server error: {resp.status_code}", resp.status_code)
                    resp.raise_for_status()
                    return resp
            except SharedLimiterTimeoutError as e:
                # The shared limiter would not give this call a slot inside
                # its ceiling: answer at once, no retry (a retry would queue
                # again behind the same backlog).
                logger.warning(f"OA API: shared limiter refusal: {e}")
                raise UpstreamRateLimitedError(rate_limited_response(
                    source=RATE_LIMIT_SOURCE_SHARED_LIMITER,
                    message=(
                        "Rate limited by this deployment's shared USPTO "
                        "limiter. Retry this call once after retry_after_seconds."
                    ),
                )) from e
            except (httpx.TimeoutException, httpx.ConnectError, USPTOAPIError) as e:
                last_exc = e
                if attempt < self.max_retries:
                    delay = 0.5 * (2 ** attempt)
                    logger.warning(
                        f"OA API transient failure ({type(e).__name__}), "
                        f"retry {attempt + 1}/{self.max_retries} in {delay:.1f}s"
                    )
                    await asyncio.sleep(delay)
            # 4xx (raise_for_status) and anything else propagate immediately
            attempt += 1
        raise last_exc  # type: ignore[misc]

    async def _request_json(self, method: str, url: str, **kwargs) -> Dict[str, Any]:
        """`_request_response` for a JSON endpoint."""
        resp = await self._request_response(method, url, **kwargs)
        return resp.json()
