"""One end-to-end time budget for a long tool call.

Reverse proxies and CDNs commonly cut a proxied request at about 100 s, and
the client then sees an error the server never hears about.
PFW_get_document_content_with_ocr's PDF path (download, then Mistral upload +
OCR, then Docling) used to budget every step on its own, so it could not
promise to finish inside the cut. One Deadline is created when the tool
starts and every step below takes what is left of it, so retries and
fallbacks stay inside the one budget rather than each getting a fresh one.

The content path reads the call's Deadline from a context variable
(`deadline_scope` in the tool, `current_deadline()` at each step) rather than
a parameter threaded through every tier: the tier methods are the seams the
test doubles replace, and an ambient budget leaves their signatures alone.

Env:
    PFW_CONTENT_DEADLINE_SECONDS   budget per PFW_get_document_content_with_ocr
                                   call (default 85, under the ~100 s cut)
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import os
import time
from typing import Any, Awaitable, Callable, Dict, Iterator, Optional

from ..shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)

DEFAULT_CONTENT_DEADLINE_SECONDS = 85.0

#: The `error` value of every result that stopped on the call's time budget.
DEADLINE_ERROR = "Deadline exceeded"


class DeadlineExceeded(Exception):
    """The call's time budget ran out before the step could finish."""


class Deadline:
    """A monotonic end time. `clock` is injectable so tests can fake time."""

    def __init__(self, seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.seconds = float(seconds)
        self._clock = clock
        self._end = clock() + self.seconds

    def remaining(self) -> float:
        """Seconds left, never negative."""
        return max(0.0, self._end - self._clock())

    def expired(self) -> bool:
        return self.remaining() <= 0.0


_CURRENT: contextvars.ContextVar[Optional[Deadline]] = contextvars.ContextVar(
    "pfw_call_deadline", default=None
)


@contextlib.contextmanager
def deadline_scope(deadline: Deadline) -> Iterator[Deadline]:
    """Make `deadline` the running call's budget for every step awaited
    inside the block (ContextVar: concurrent calls never share one)."""
    token = _CURRENT.set(deadline)
    try:
        yield deadline
    finally:
        _CURRENT.reset(token)


def current_deadline() -> Optional[Deadline]:
    """The running call's Deadline, or None outside a deadline_scope."""
    return _CURRENT.get()


def content_deadline_seconds() -> float:
    """PFW_CONTENT_DEADLINE_SECONDS, else 85; non-positive or junk -> 85."""
    raw = os.getenv("PFW_CONTENT_DEADLINE_SECONDS", "").strip()
    if not raw:
        return DEFAULT_CONTENT_DEADLINE_SECONDS
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Invalid PFW_CONTENT_DEADLINE_SECONDS, using default 85")
        return DEFAULT_CONTENT_DEADLINE_SECONDS
    return value if value > 0 else DEFAULT_CONTENT_DEADLINE_SECONDS


async def run_within(deadline: Optional[Deadline], awaitable: Awaitable[Any]) -> Any:
    """Await `awaitable`, cut at what is left of `deadline` (no cut without
    one). A cut, or an already-spent deadline, raises DeadlineExceeded."""
    if deadline is None:
        return await awaitable
    remaining = deadline.remaining()
    if remaining <= 0:
        close = getattr(awaitable, "close", None)
        if close is not None:
            close()  # never started: do not leave an un-awaited coroutine
        raise DeadlineExceeded("the call's time limit is spent")
    try:
        return await asyncio.wait_for(awaitable, timeout=remaining)
    except asyncio.TimeoutError as exc:
        raise DeadlineExceeded("step ran past the call's time limit") from exc


def deadline_exceeded_fields(message: str) -> Dict[str, Any]:
    """The fields a "Deadline exceeded" tool result carries. Nothing about
    cost: the message says what to do next, never what it would spend."""
    return {
        "success": False,
        "error": DEADLINE_ERROR,
        "error_type": "deadline_exceeded",
        "status_code": 504,
        "message": message,
    }
