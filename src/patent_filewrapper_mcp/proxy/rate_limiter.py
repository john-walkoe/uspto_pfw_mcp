"""
Rate limiting for USPTO API compliance

Implements USPTO's download limit of 5 files per 10 seconds per IP address.
"""
import time
from collections import defaultdict, deque
from typing import Dict, Deque, Optional
from ..shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)

class RateLimiter:
    """Rate limiter for USPTO document downloads"""

    def __init__(self, max_requests: int = 5, time_window: int = 10):
        """
        Initialize rate limiter

        Args:
            max_requests: Maximum requests allowed in time window (default: 5)
            time_window: Time window in seconds (default: 10)
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests: Dict[str, Deque[float]] = defaultdict(deque)
        # Idle-IP eviction bookkeeping (audit F47): without it the per-IP
        # dict grows unbounded on a long-running proxy
        self._last_evict = time.time()
        self._evict_interval = 300.0  # seconds

    def _evict_idle(self, now: float) -> None:
        """Drop IPs whose entire request history is outside the window."""
        if now - self._last_evict < self._evict_interval:
            return
        self._last_evict = now
        cutoff = now - max(self.time_window, 60)
        idle = [ip for ip, dq in self.requests.items() if not dq or dq[-1] < cutoff]
        for ip in idle:
            del self.requests[ip]
        if idle:
            logger.info(f"Rate limiter evicted {len(idle)} idle IP bucket(s)")

    def is_allowed(
        self,
        client_ip: str,
        limit: Optional[int] = None,
        window: Optional[float] = None,
    ) -> bool:
        """
        Check if a request from the given IP is allowed.

        Args:
            client_ip: Client IP address.
            limit: Optional request-count cap (defaults to self.max_requests).
            window: Optional time window in seconds (defaults to self.time_window).
        """
        max_req = limit if limit is not None else self.max_requests
        time_win = window if window is not None else self.time_window
        now = time.time()
        self._evict_idle(now)
        client_requests = self.requests[client_ip]

        # Remove requests outside the (custom or default) time window
        while client_requests and client_requests[0] < now - time_win:
            client_requests.popleft()

        if len(client_requests) >= max_req:
            logger.warning(
                f"Rate limit exceeded for IP {client_ip}: "
                f"{len(client_requests)}/{max_req} requests in {time_win}s"
            )
            return False

        client_requests.append(now)
        logger.info(
            f"Request allowed for IP {client_ip}: "
            f"{len(client_requests)}/{max_req} in {time_win}s"
        )
        return True

    def get_remaining_requests(self, client_ip: str) -> int:
        """
        Get number of remaining requests for the IP

        Args:
            client_ip: Client IP address

        Returns:
            Number of remaining requests in current window
        """
        now = time.time()
        client_requests = self.requests[client_ip]

        # Remove old requests
        while client_requests and client_requests[0] < now - self.time_window:
            client_requests.popleft()

        return max(0, self.max_requests - len(client_requests))

    def get_reset_time(self, client_ip: str) -> float:
        """
        Get time when rate limit will reset for the IP

        Args:
            client_ip: Client IP address

        Returns:
            Unix timestamp when oldest request will expire
        """
        client_requests = self.requests[client_ip]
        if not client_requests:
            return time.time()

        return client_requests[0] + self.time_window

# Global rate limiter instance
rate_limiter = RateLimiter()
