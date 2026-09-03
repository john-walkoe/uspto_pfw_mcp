#!/usr/bin/env python3
"""The `fields` argument reaches the ODP response for both search lanes.

Calls the live USPTO ODP API. Previously this signalled failure with
`return False`, which pytest reads as PASS, so the fields regression it was
written to catch could return unnoticed (audit T-4). The USPTO_API_KEY
assignment that used to sit here at import time is now in conftest (T-3).
"""

import pytest
from conftest import requires_live_uspto

from patent_filewrapper_mcp.api.enhanced_client import EnhancedPatentClient

_FIELDS = [
    "applicationNumberText",
    "inventionTitle",
    "parentPatentNumber",
    "patentNumber",
]
_LIMIT = 200


def _assert_requested_fields_present(applications, lane):
    """Every returned application must carry the projection it was asked for.

    Checked on the first three rather than all: the failure mode is the
    projection being dropped wholesale, not one row missing a value.
    """
    for index, app in enumerate(applications[:3]):
        assert app.get("applicationNumberText"), (
            f"{lane} result {index}: applicationNumberText missing from the "
            f"projection"
        )
        assert "applicationMetaData" in app, (
            f"{lane} result {index}: applicationMetaData missing, so "
            f"inventionTitle and patentNumber cannot be present either"
        )


@requires_live_uspto
@pytest.mark.parametrize("name", ["Wilbur Walkoe", "Walkoe"])
async def test_inventor_search_returns_the_requested_fields(name):
    client = EnhancedPatentClient()
    result = await client.search_inventor(name, "comprehensive", _LIMIT, _FIELDS)

    assert not result.get("error"), f"inventor search failed: {result.get('error')}"
    _assert_requested_fields_present(
        result.get("unique_applications", []), "search_inventor"
    )


@requires_live_uspto
async def test_applications_search_returns_the_requested_fields():
    client = EnhancedPatentClient()
    result = await client.search_applications("Wil Walkoe", _LIMIT, 0, _FIELDS)

    assert not result.get("error"), (
        f"applications search failed: {result.get('error')}"
    )
    _assert_requested_fields_present(
        result.get("applications", []), "search_applications"
    )
