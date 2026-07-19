"""Resilience primitives for the USPTO API client (audit F3 split).

CircuitBreaker, ResponseCache, and RetryBudget are self-contained — no
USPTO knowledge — and are composed by EnhancedPatentClient.
"""
import hashlib
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from ..shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """
    Circuit breaker pattern implementation to prevent cascading failures
    when the USPTO API is down or experiencing issues.
    """

    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        """
        Initialize circuit breaker

        Args:
            failure_threshold: Number of failures before opening circuit
            timeout: Time in seconds before trying to close circuit again
        """
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = CircuitState.CLOSED

    def can_execute(self) -> bool:
        """Check if requests can be executed"""
        if self.state == CircuitState.CLOSED:
            return True
        elif self.state == CircuitState.OPEN:
            # Check if timeout has passed
            if time.time() - self.last_failure_time > self.timeout:
                self.state = CircuitState.HALF_OPEN
                logger.info("Circuit breaker transitioning to HALF_OPEN state")
                return True
            return False
        else:  # HALF_OPEN
            return True

    def record_success(self):
        """Record a successful operation"""
        if self.state == CircuitState.HALF_OPEN:
            logger.info("Circuit breaker transitioning to CLOSED state after successful request")
        self.failure_count = 0
        self.state = CircuitState.CLOSED

    def record_failure(self):
        """Record a failed operation"""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            if self.state != CircuitState.OPEN:
                logger.warning(f"Circuit breaker OPENING after {self.failure_count} failures")
            self.state = CircuitState.OPEN

    def is_open(self) -> bool:
        """Check if circuit is open"""
        return self.state == CircuitState.OPEN


class ResponseCache:
    """
    Cache successful API responses for fallback during outages.

    Provides resilience by serving cached data when the circuit breaker
    is open, improving user experience during API failures.
    """

    def __init__(self, ttl_seconds: int = 300, max_size: int = 100):
        """
        Initialize response cache

        Args:
            ttl_seconds: Time-to-live for cached responses (default: 5 minutes)
            max_size: Maximum number of cached responses (default: 100)
        """
        self.cache: Dict[str, Tuple[Dict[str, Any], float]] = {}
        self.ttl = ttl_seconds
        self.max_size = max_size
        logger.info(f"Response cache initialized: TTL={ttl_seconds}s, max_size={max_size}")

    def _make_key(self, endpoint: str, **kwargs) -> str:
        """
        Generate cache key from request parameters

        Args:
            endpoint: API endpoint path
            **kwargs: Request parameters

        Returns:
            SHA256 hash of endpoint and parameters (first 16 chars)
        """
        # Sort kwargs to ensure consistent key generation
        key_data = f"{endpoint}:{str(sorted(kwargs.items()))}"
        return hashlib.sha256(key_data.encode()).hexdigest()[:16]

    def get(self, endpoint: str, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Retrieve cached response if still valid

        Args:
            endpoint: API endpoint path
            **kwargs: Request parameters

        Returns:
            Cached response dict or None if not found/expired
        """
        key = self._make_key(endpoint, **kwargs)
        if key in self.cache:
            value, timestamp = self.cache[key]
            age = time.time() - timestamp

            if age < self.ttl:
                logger.info(f"Cache HIT for {endpoint} (age={age:.1f}s)")
                return value
            else:
                # Expired - remove from cache
                logger.debug(f"Cache entry expired for {endpoint} (age={age:.1f}s)")
                del self.cache[key]

        logger.debug(f"Cache MISS for {endpoint}")
        return None

    def set(self, endpoint: str, value: Dict[str, Any], **kwargs) -> None:
        """
        Cache successful response

        Args:
            endpoint: API endpoint path
            value: Response data to cache
            **kwargs: Request parameters
        """
        # Enforce max cache size - remove oldest entry if needed
        if len(self.cache) >= self.max_size:
            oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k][1])
            logger.debug(f"Cache full, removing oldest entry: {oldest_key}")
            del self.cache[oldest_key]

        key = self._make_key(endpoint, **kwargs)
        self.cache[key] = (value, time.time())
        logger.debug(f"Cached response for {endpoint} (cache size: {len(self.cache)}/{self.max_size})")

    def clear(self) -> None:
        """Clear all cached responses"""
        count = len(self.cache)
        self.cache.clear()
        logger.info(f"Response cache cleared ({count} entries removed)")

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "ttl_seconds": self.ttl,
            "entries": [
                {
                    "key": key,
                    "age_seconds": time.time() - timestamp
                }
                for key, (_, timestamp) in self.cache.items()
            ]
        }


class RetryBudget:
    """
    Track retry budget to prevent API quota exhaustion during persistent failures.

    Implements a sliding window counter to limit total retries per hour,
    preventing cascading failures and quota exhaustion.
    """

    def __init__(self, max_retries_per_hour: int = 100):
        """
        Initialize retry budget tracker.

        Args:
            max_retries_per_hour: Maximum retry attempts allowed per hour
        """
        self.max_retries = max_retries_per_hour
        self.retry_timestamps: List[float] = []
        logger.info(f"Retry budget initialized: max_retries_per_hour={max_retries_per_hour}")

    def can_retry(self) -> bool:
        """
        Check if we have retry budget available.

        Returns:
            True if retry is allowed, False if budget exhausted
        """
        now = time.time()

        # Remove retries older than 1 hour (sliding window)
        self.retry_timestamps = [ts for ts in self.retry_timestamps if now - ts < 3600]

        if len(self.retry_timestamps) >= self.max_retries:
            logger.warning(
                f"Retry budget exhausted: {len(self.retry_timestamps)}/{self.max_retries} "
                f"retries in last hour"
            )
            return False

        return True

    def record_retry(self) -> None:
        """Record a retry attempt in the budget."""
        self.retry_timestamps.append(time.time())
        logger.debug(
            f"Retry recorded: {len(self.retry_timestamps)}/{self.max_retries} "
            f"used in last hour"
        )

    def get_remaining_budget(self) -> int:
        """
        Get remaining retry budget.

        Returns:
            Number of retries remaining in current window
        """
        now = time.time()
        self.retry_timestamps = [ts for ts in self.retry_timestamps if now - ts < 3600]
        return max(0, self.max_retries - len(self.retry_timestamps))

    def get_stats(self) -> Dict[str, Any]:
        """
        Get retry budget statistics.

        Returns:
            Dictionary with budget usage statistics
        """
        now = time.time()
        self.retry_timestamps = [ts for ts in self.retry_timestamps if now - ts < 3600]

        return {
            "max_retries_per_hour": self.max_retries,
            "retries_used": len(self.retry_timestamps),
            "retries_remaining": self.max_retries - len(self.retry_timestamps),
            "utilization_percent": (len(self.retry_timestamps) / self.max_retries * 100) if self.max_retries > 0 else 0
        }

