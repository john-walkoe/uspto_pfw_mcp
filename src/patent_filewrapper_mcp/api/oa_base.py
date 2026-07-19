"""Shared base for the Office Action API clients (audits F19/F23).

The OA rejections/text clients previously made single unprotected httpx
calls (no retry, no typed errors, hardcoded timeouts) while the primary
USPTO path had full resilience. This base gives both clients:
- typed AuthenticationError instead of bare ValueError for a missing key
- a bounded retry loop with exponential backoff on transient failures
  (5xx, timeouts, connection errors) — never on 4xx
- env-configurable timeout (USPTO_OA_TIMEOUT) and retry cap
  (USPTO_OA_MAX_RETRIES)
"""
import asyncio
import os
from typing import Any, Dict, Optional

import httpx

from ..exceptions import AuthenticationError, USPTOAPIError
from ..shared.safe_logger import get_safe_logger
from ..shared.uspto_shared_rate_limiter import get_shared_limiter

logger = get_safe_logger(__name__)


class OAClientBase:
    """Common auth, timeout, and retry behavior for OA API clients."""

    def __init__(self, api_key: Optional[str] = None, timeout: Optional[float] = None):
        self.api_key = api_key or os.getenv("USPTO_API_KEY", "")
        if not self.api_key:
            raise AuthenticationError("USPTO_API_KEY environment variable is required")
        self.timeout = timeout if timeout is not None else float(os.getenv("USPTO_OA_TIMEOUT", "30.0"))
        self.max_retries = int(os.getenv("USPTO_OA_MAX_RETRIES", "2"))

    def _headers(self) -> Dict[str, str]:
        return {"X-API-KEY": self.api_key}

    async def _send_once(self, client: httpx.AsyncClient, method: str, url: str, **kwargs) -> httpx.Response:
        """Perform exactly one HTTP send, gated by the shared cross-process
        rate limiter (token + concurrency slot) — off unless
        USPTO_SHARED_RATE_LIMIT_DIR is set. Called once per retry ATTEMPT
        from _request_json's loop; the OA APIs are api.uspto.gov ODP
        endpoints under the same per-key limits as the primary PFW path."""
        send = client.request(method, url, headers=self._headers(), **kwargs)
        limiter = get_shared_limiter()
        if limiter is not None:
            async with limiter:
                return await send
        return await send

    async def _request_json(self, method: str, url: str, **kwargs) -> Dict[str, Any]:
        """One OA API call with bounded retry on transient failures."""
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await self._send_once(client, method, url, **kwargs)
                    if resp.status_code >= 500:
                        raise USPTOAPIError(f"OA API server error: {resp.status_code}", resp.status_code)
                    resp.raise_for_status()
                    return resp.json()
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
        raise last_exc
