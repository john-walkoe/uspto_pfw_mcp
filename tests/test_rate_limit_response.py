"""A refused-for-pacing call answers fast and structured, and never hangs.

Five back-to-back PFW_get_document_download calls made the fifth fail three
times with the client reporting "connector's server isn't responding" before
it finally succeeded (walkthrough follow-up, 2026-09-05). Two defects:

  * a 429 came back as the generic `{"message": "API error: <raw body>"}`, so
    nothing told the model that WAITING was the fix; and
  * the shared cross-process limiter's TimeoutError (30s by default) landed in
    the transport's generic `except Exception` and was RETRIED three times.
    ~93 seconds of silence is what the client reports as "not responding".

Every failure shape below is produced with a fake transport. No live calls, no
sleeping for real: the tests that assert "does not retry" assert the ATTEMPT
COUNT, which is what makes them fast and what makes them the actual regression
guard.

2026-10-13 (ODP rate-limit wave, plan 2c / D4): the 3.0 s self-paced cap
these tests encoded is gone. The rule is now: on a 429 note it on the shared
key cooldown, wait max(5 s, Retry-After) and send ONCE more when that wait
is <= 10 s and fits the call's budget (the request timeout), otherwise the
envelope with retry_after_seconds = max(5, Retry-After); never two retries.
The transport's sleeps are recorded, not slept. The limiter's refusal is
SharedLimiterTimeoutError (a TimeoutError subclass) and is answered at once.
"""

import asyncio

import httpx
import pytest

from patent_filewrapper_mcp.api import helpers
from patent_filewrapper_mcp.api import transport as transport_module
from patent_filewrapper_mcp.api.transport import USPTOTransport
from patent_filewrapper_mcp.shared.uspto_shared_rate_limiter import SharedLimiterTimeoutError


def _transport(default_timeout: float = 30.0) -> USPTOTransport:
    # 2026-10-13: the timeout is the single 429 wait's budget (it was 1.0 s
    # here, which under the 5 s floor would answer every 429 with the
    # envelope); 30 s is EnhancedPatentClient's USPTO_TIMEOUT default.
    return USPTOTransport(
        base_url="https://api.invalid/pfw",
        headers={"X-API-KEY": "test"},
        default_timeout=default_timeout,
        api_limits=httpx.Limits(max_connections=1),
    )


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    """Record the transport's sleeps (the 429 wait and the 5xx backoff)
    instead of waiting them out."""
    recorded = []

    async def fake_sleep(seconds):
        recorded.append(seconds)

    monkeypatch.setattr(transport_module.asyncio, "sleep", fake_sleep)
    return recorded


@pytest.fixture
def noted(monkeypatch):
    """Record every note_429 the transport makes on the shared key."""
    recorded = []
    monkeypatch.setattr(transport_module, "note_429", recorded.append)
    return recorded


class _FakeSend:
    """Stands in for `_send_once`, counting attempts and replaying a script."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.attempts = 0

    async def __call__(self, method, url, **kwargs):
        self.attempts += 1
        outcome = self.outcomes[min(self.attempts - 1, len(self.outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _response(status: int, headers=None) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        headers=headers or {},
        json={"detail": "slow down"},
        request=httpx.Request("GET", "https://api.invalid/pfw/x"),
    )


def _status_error(status: int, headers=None) -> httpx.HTTPStatusError:
    response = _response(status, headers)
    return httpx.HTTPStatusError("rate limited", request=response.request, response=response)


# ===========================================================================
# The envelope
# ===========================================================================

def test_the_envelope_says_rate_limited_and_how_long_to_wait():
    envelope = helpers.rate_limited_response(retry_after_seconds=7)
    assert envelope["rate_limited"] is True
    assert envelope["retry_after_seconds"] == 7.0
    assert envelope["status_code"] == 429
    assert envelope["error"] is True
    assert envelope["error_type"] == "rate_limited"
    assert envelope["rate_limit_source"] == helpers.RATE_LIMIT_SOURCE_UPSTREAM
    assert "retry" in envelope["rate_limit_note"].lower()


def test_retry_after_seconds_is_always_a_number():
    """The model must never have to guess how long "later" means."""
    for missing in (None, 0, -5):
        envelope = helpers.rate_limited_response(retry_after_seconds=missing)
        assert envelope["retry_after_seconds"] == helpers.DEFAULT_RETRY_AFTER_SECONDS
    # 2026-10-13: the fallback is USPTO's published 5 s floor (it was 10.0).
    assert helpers.DEFAULT_RETRY_AFTER_SECONDS == helpers.RATE_LIMIT_WAIT_FLOOR_SECONDS == 5.0


def test_retry_after_seconds_is_never_under_the_floor():
    """2026-10-13: a Retry-After of 2 is reported as 5, USPTO's floor."""
    assert helpers.rate_limited_response(retry_after_seconds=2)["retry_after_seconds"] == 5.0
    assert helpers.rate_limited_response(retry_after_seconds=30)["retry_after_seconds"] == 30.0


def test_the_shared_limiter_source_says_it_was_not_uspto():
    envelope = helpers.rate_limited_response(
        source=helpers.RATE_LIMIT_SOURCE_SHARED_LIMITER
    )
    assert envelope["rate_limit_source"] == "shared_uspto_limiter"
    assert "shared USPTO rate limiter" in envelope["rate_limit_note"]
    assert "not from USPTO itself" in envelope["rate_limit_note"]


@pytest.mark.parametrize(
    "header,expected",
    [("5", 5.0), ("0.5", 0.5), ("0", 0.0), (None, None), ("", None),
     ("Wed, 21 Oct 2026 07:28:00 GMT", None), ("-3", None), ("nonsense", None)],
)
def test_parse_retry_after(header, expected):
    assert helpers.parse_retry_after(header) == expected


def test_is_rate_limited_only_matches_the_envelope():
    assert helpers.is_rate_limited(helpers.rate_limited_response())
    assert not helpers.is_rate_limited({"error": True, "status_code": 500})
    assert not helpers.is_rate_limited({"success": True})
    assert not helpers.is_rate_limited(None)
    assert not helpers.is_rate_limited("rate limited")


# ===========================================================================
# 429 from USPTO
# ===========================================================================

@pytest.mark.asyncio
async def test_a_429_returns_the_structured_envelope_not_a_raw_api_error(sleeps, noted):
    """2026-10-13: a 9 s Retry-After is under the 10 s absorb ceiling, so
    the transport waits 9 s and sends once more; the persistent 429 is then
    the envelope, carrying the 9 s. Two attempts, never three."""
    transport = _transport()
    fake = _FakeSend(_status_error(429, {"Retry-After": "9"}))
    transport._send_once = fake

    result = await transport.request("applications")

    assert fake.attempts == 2
    assert sleeps == [9.0]
    assert noted == [9.0, 9.0]
    assert result["rate_limited"] is True
    assert result["retry_after_seconds"] == 9.0
    assert result["rate_limit_source"] == "uspto_api"
    assert not str(result["message"]).startswith("API error:")


@pytest.mark.asyncio
async def test_a_429_without_retry_after_still_names_a_wait(sleeps, noted):
    """2026-10-13: no header means the 5 s floor, waited once (USPTO's own
    published floor is not sleeping blind), then reported."""
    transport = _transport()
    fake = _FakeSend(_status_error(429))
    transport._send_once = fake

    result = await transport.request("applications")

    assert fake.attempts == 2
    assert sleeps == [5.0]
    assert noted == [None, None]
    assert result["retry_after_seconds"] == helpers.DEFAULT_RETRY_AFTER_SECONDS == 5.0


@pytest.mark.parametrize("retry_after, wait", [(None, 5.0), ("2", 5.0), ("5", 5.0), ("10", 10.0)])
@pytest.mark.asyncio
async def test_exactly_one_retry_after_at_least_five_seconds(sleeps, noted, retry_after, wait):
    """The rule for Retry-After absent / 2 / 5 / 10: one retry after
    max(5, Retry-After), and the 200 comes back as data."""
    transport = _transport()
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    fake = _FakeSend(_status_error(429, headers), _response(200))
    transport._send_once = fake

    result = await transport.request("applications")

    assert fake.attempts == 2
    assert sleeps == [wait]
    assert noted == [None if retry_after is None else float(retry_after)]
    assert result.get("detail") == "slow down"  # the 200 body
    assert "rate_limited" not in result


@pytest.mark.asyncio
async def test_a_429_does_not_burn_the_retry_budget_on_a_long_wait(sleeps, noted):
    """A 30 s Retry-After is REPORTED, not slept: holding the tool call open
    that long is the hang. Exactly one attempt is made. (2026-10-13: this
    case used 10 s, which the rule now absorbs; 10 s is the ceiling.)"""
    transport = _transport()
    fake = _FakeSend(_status_error(429, {"Retry-After": "30"}))
    transport._send_once = fake

    result = await transport.request("applications")

    assert fake.attempts == 1
    assert sleeps == []
    assert noted == [30.0]
    assert result["rate_limited"] is True
    assert result["retry_after_seconds"] == 30.0


@pytest.mark.asyncio
async def test_a_short_retry_after_is_absorbed_once_then_succeeds(sleeps):
    """A caller that would have got a refusal gets data instead. 2026-10-13:
    the wait is never under the 5 s floor, whatever the header said."""
    transport = _transport()
    fake = _FakeSend(_status_error(429, {"Retry-After": "0.01"}), _response(200))
    transport._send_once = fake

    result = await transport.request("applications")

    assert fake.attempts == 2
    assert sleeps == [5.0]
    assert result.get("detail") == "slow down"  # the 200 body
    assert "rate_limited" not in result


@pytest.mark.asyncio
async def test_the_retry_happens_at_most_once(sleeps):
    """Never a loop: a second 429 after the one wait returns rather than
    waiting again."""
    transport = _transport()
    fake = _FakeSend(_status_error(429, {"Retry-After": "2"}))
    transport._send_once = fake

    result = await transport.request("applications")

    assert fake.attempts == 2  # one send, one retry, then stop
    assert sleeps == [5.0]
    assert result["rate_limited"] is True
    assert result["retry_after_seconds"] == 5.0


@pytest.mark.asyncio
async def test_the_wait_fits_the_calls_budget_or_it_is_the_envelope(sleeps):
    """A 5 s request timeout cannot fit the 5 s floor once any time has
    passed, so no wait is absorbed: one attempt, the envelope."""
    transport = _transport(default_timeout=5.0)
    fake = _FakeSend(_status_error(429), _response(200))
    transport._send_once = fake

    result = await transport.request("applications")

    assert fake.attempts == 1
    assert sleeps == []
    assert result["rate_limited"] is True


@pytest.mark.asyncio
async def test_a_per_call_timeout_is_the_budget(sleeps):
    """A caller's own `timeout=` kwarg, not the transport default, bounds
    the wait."""
    transport = _transport(default_timeout=30.0)
    fake = _FakeSend(_status_error(429), _response(200))
    transport._send_once = fake

    result = await transport.request("applications", timeout=3.0)

    assert fake.attempts == 1
    assert sleeps == []
    assert result["rate_limited"] is True


@pytest.mark.asyncio
async def test_a_429_does_not_open_the_circuit_breaker():
    """A 429 is a valid answer, not an API failure. Recording it as one would
    take the NEXT caller's unrelated request down with it."""
    transport = _transport()
    transport._send_once = _FakeSend(_status_error(429))

    await transport.request("applications")

    assert transport.circuit_breaker.can_execute()


# ===========================================================================
# The shared limiter: the actual hang
# ===========================================================================

@pytest.mark.asyncio
async def test_the_shared_limiter_timeout_returns_without_retrying(sleeps, noted):
    """THE REGRESSION GUARD. Three attempts at up to the ceiling of acquire
    wait each is the ~93 seconds of silence the client reported as "isn't
    responding". 2026-10-13: the limiter raises SharedLimiterTimeoutError
    (a TimeoutError subclass); the transport catches that class."""
    transport = _transport()
    fake = _FakeSend(
        SharedLimiterTimeoutError("shared USPTO rate limiter: no request slot within 45s")
    )
    transport._send_once = fake

    result = await transport.request("applications")

    assert fake.attempts == 1, "a limiter timeout must not be retried"
    assert sleeps == [] and noted == []
    assert result["rate_limited"] is True
    assert result["rate_limit_source"] == "shared_uspto_limiter"
    assert result["retry_after_seconds"] == 5.0
    assert result["status_code"] == 429


@pytest.mark.asyncio
async def test_the_limiter_timeout_answers_quickly(monkeypatch):
    monkeypatch.undo()  # real sleeps: the point is that none happen
    transport = _transport()
    transport._send_once = _FakeSend(SharedLimiterTimeoutError("slot unavailable after 45s"))

    loop = asyncio.get_running_loop()
    started = loop.time()
    await transport.request("applications")

    assert loop.time() - started < 1.0


@pytest.mark.asyncio
async def test_an_httpx_timeout_is_still_retried(sleeps):
    """Only the limiter's TimeoutError short-circuits. A genuine network
    timeout is transient and the existing retry is the right answer, so this
    pins that the new arm did not swallow it."""
    transport = _transport()
    fake = _FakeSend(httpx.ReadTimeout("timed out"))
    transport._send_once = fake

    result = await transport.request("applications")

    assert fake.attempts == transport.RETRY_ATTEMPTS
    assert len(sleeps) == transport.RETRY_ATTEMPTS - 1  # the backoff, recorded
    assert result.get("rate_limited") is not True


# ===========================================================================
# What the download tool does with it
# ===========================================================================

def test_the_download_tool_adds_its_own_pacing_advice():
    from patent_filewrapper_mcp.tools.document_tools import _rate_limit_passthrough

    passed = _rate_limit_passthrough(helpers.rate_limited_response())

    assert passed["rate_limited"] is True
    assert "5 downloads per 10 seconds" in passed["rate_limit_note"]
    assert "one at a time" in passed["rate_limit_note"]
    assert passed["tool"] == "PFW_get_document_download"
    assert passed["guidance"] == passed["rate_limit_note"]


def test_a_non_rate_limit_error_passes_through_untouched():
    from patent_filewrapper_mcp.tools.document_tools import _rate_limit_passthrough

    original = {"error": True, "status_code": 404, "message": "not found"}
    assert _rate_limit_passthrough(dict(original)) == original
