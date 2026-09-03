"""The claude.ai probe shim must only pre-empt requests the transport refuses.

`_StreamableHTTPProbeMiddleware` answers 401 where the streamable-HTTP
transport would answer 406, so claude.ai's older format probe falls through to
an anonymous connection instead of latching "format-incompatible". That trade
is only safe while the shim's Accept rule is the SAME rule the transport
applies. It was not: the original test was a substring search for
'text/event-stream', so a conformant client sending `Accept: */*` or
`text/*` — values both protocol eras accept — was 401'd before the SDK saw it.
Under the 2026-07-28 era that killed `server/discover` and the connection never
formed.

These tests assert parity against `mcp.server.streamable_http.check_accept_headers`,
the SDK's own parser, rather than restating the rule.
"""

import pytest

from patent_filewrapper_mcp.middleware import (
    _accept_kinds,
    _StreamableHTTPProbeMiddleware,
)

# Every Accept value either era of the transport treats as usable, plus the
# genuinely broken ones the shim exists to intercept.
ACCEPT_VALUES = [
    "application/json, text/event-stream",
    "text/event-stream, application/json",
    "application/json;q=0.9, text/event-stream;q=0.8",
    "*/*",
    "application/*, text/*",
    "APPLICATION/JSON, TEXT/EVENT-STREAM",
    "application/json",
    "text/event-stream",
    "text/html",
    "",
]


def _scope(method, path="/mcp", accept=None):
    headers = [(b"content-type", b"application/json")]
    if accept is not None:
        headers.append((b"accept", accept.encode()))
    return {"type": "http", "method": method, "path": path, "headers": headers}


@pytest.mark.parametrize("accept", ACCEPT_VALUES)
def test_accept_parsing_matches_the_sdk(accept):
    """Our scope-level parser and the SDK's Request-level one must agree."""
    from mcp.server.streamable_http import check_accept_headers
    from starlette.requests import Request

    sdk = check_accept_headers(Request(_scope("POST", accept=accept)))
    assert _accept_kinds(_scope("POST", accept=accept)) == sdk


async def _run(app, scope):
    """Drive one ASGI call, returning the response status (None if passed through)."""
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    passed = []

    async def inner(scope_, receive_, send_):
        passed.append(True)

    await _StreamableHTTPProbeMiddleware(inner)(scope, receive, send)
    if passed:
        return None
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


@pytest.mark.parametrize(
    "accept",
    [
        "application/json, text/event-stream",
        "*/*",
        "application/*, text/*",
        "application/json;q=0.9, text/event-stream;q=0.8",
    ],
)
async def test_conformant_post_reaches_the_transport(accept):
    """A client the SDK would serve must not be intercepted (regression: `*/*`)."""
    assert await _run(None, _scope("POST", accept=accept)) is None


@pytest.mark.parametrize("accept", ["application/json", "text/html", ""])
async def test_json_only_post_is_intercepted(accept):
    """The claude.ai format probe (no SSE accept) still gets its 401."""
    assert await _run(None, _scope("POST", accept=accept)) == 401


async def test_missing_accept_header_is_intercepted():
    assert await _run(None, _scope("POST", accept=None)) == 401


@pytest.mark.parametrize("accept", ["text/event-stream", "*/*", "text/*"])
async def test_get_with_sse_accept_reaches_the_transport(accept):
    """GET is the legacy SSE stream (405 on the modern era) — the transport's
    call to make, not the shim's."""
    assert await _run(None, _scope("GET", accept=accept)) is None


async def test_get_without_sse_accept_is_intercepted():
    assert await _run(None, _scope("GET", accept="application/json")) == 401


async def test_non_mcp_paths_are_never_intercepted():
    assert await _run(None, _scope("GET", path="/health", accept="text/html")) is None
    assert await _run(None, _scope("POST", path="/token", accept="application/json")) is None
