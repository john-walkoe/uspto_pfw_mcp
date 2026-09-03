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
        # Bucket per (IP, limit policy), not per IP. Downloads (5 per 10s) and
        # registrations (10 per 60s) shared ONE deque keyed only by the IP, so
        # each consumed the other's budget and NEITHER advertised limit was
        # real: five downloads left a registration caller with a partly-spent
        # window under a different policy (audit L-1).
        client_requests = self.requests[self._bucket_key(client_ip, max_req, time_win)]

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

    def _bucket_key(self, client_ip: str, max_req: int, time_win: float) -> str:
        """Bucket per (IP, limit policy), not per IP.

        Downloads (5 per 10s) and registrations (10 per 60s) shared ONE deque
        keyed only by the IP, so each consumed the other's budget and NEITHER
        advertised limit was real (audit L-1). The policy is part of the key,
        so the accessors below must be told which policy they are asking about.
        """
        return f"{client_ip}|{max_req}/{time_win}"

    def get_remaining_requests(self, client_ip: str, limit: Optional[int] = None,
                               window: Optional[float] = None) -> int:
        """
        Get number of remaining requests for the IP

        Args:
            client_ip: Client IP address
            limit: The limit policy to ask about (defaults to self.max_requests)
            window: The window policy to ask about (defaults to self.time_window)

        Returns:
            Number of remaining requests in current window
        """
        max_req = limit if limit is not None else self.max_requests
        time_win = window if window is not None else self.time_window
        now = time.time()
        client_requests = self.requests[self._bucket_key(client_ip, max_req, time_win)]

        # Remove old requests
        while client_requests and client_requests[0] < now - time_win:
            client_requests.popleft()

        return max(0, max_req - len(client_requests))

    def get_reset_time(self, client_ip: str, limit: Optional[int] = None,
                       window: Optional[float] = None) -> float:
        """
        Get time when rate limit will reset for the IP

        Args:
            client_ip: Client IP address
            limit: The limit policy to ask about (defaults to self.max_requests)
            window: The window policy to ask about (defaults to self.time_window)

        Returns:
            Unix timestamp when oldest request will expire
        """
        max_req = limit if limit is not None else self.max_requests
        time_win = window if window is not None else self.time_window
        client_requests = self.requests[self._bucket_key(client_ip, max_req, time_win)]
        if not client_requests:
            return time.time()

        return client_requests[0] + time_win

# Global rate limiter instance
rate_limiter = RateLimiter()
