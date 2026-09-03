"""Unrecognized content_type values must fail loudly with a 400.

Until 2026-09-02, _resolve_forced_lane returned None for anything that was
not 'patent'/'application', so a typo like content_type='applicaton'
silently behaved as 'auto', putting the caller straight back into the
8-digit ambiguity they were reaching for content_type to escape.
"""

import pytest

from patent_filewrapper_mcp.util.identifier_resolution import (
    VALID_CONTENT_TYPES,
    content_type_error_message,
    resolve_or_error,
)


class _MustNotBeCalledClient:
    async def lookup_identifier_lane(self, *args, **kwargs):
        raise AssertionError("resolution queried USPTO despite invalid content_type")


def test_valid_values_produce_no_error():
    assert VALID_CONTENT_TYPES == ("auto", "patent", "application")
    for value in VALID_CONTENT_TYPES:
        assert content_type_error_message(value) is None


@pytest.mark.parametrize("bad", ["applicaton", "PATENT", "app", "", "Auto"])
def test_message_names_the_valid_values(bad):
    msg = content_type_error_message(bad)
    assert msg is not None
    for value in VALID_CONTENT_TYPES:
        assert f"'{value}'" in msg
    assert f"'{bad}'" in msg


@pytest.mark.asyncio
async def test_resolve_or_error_rejects_before_any_api_call():
    resolution, error = await resolve_or_error(
        _MustNotBeCalledClient(), "11752072", content_type="applicaton"
    )
    assert resolution is None
    assert error["status_code"] == 400
    assert "applicaton" in error["message"]


@pytest.mark.asyncio
async def test_forced_application_lane_still_short_circuits():
    # content_type='application' needs no API call; the guard must not
    # disturb the valid-value path.
    resolution, error = await resolve_or_error(
        _MustNotBeCalledClient(), "11752072", content_type="application"
    )
    assert error is None
    assert resolution.application_number == "11752072"
