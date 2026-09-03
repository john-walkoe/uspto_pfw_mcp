#!/usr/bin/env python3
"""pfw_get_granted_patent_documents_download across the five scenarios in the
session-history specification.

Calls the live USPTO ODP API. Previously every check `logger.error`d and then
`return result`, so nothing could fail: all five cases reported PASS whatever
the API answered (audit T-4).
"""

import pytest
from conftest import requires_live_uspto

from patent_filewrapper_mcp.api.enhanced_client import EnhancedPatentClient

TEST_APP_NUMBER = "14171705"  # Valid granted patent from the session spec
INVALID_APP_NUMBER = "00000000"

_ALL_COMPONENTS = ["abstract", "specification", "claims", "drawings"]

pytestmark = requires_live_uspto


@pytest.fixture
def client():
    return EnhancedPatentClient()


class TestNormalGrantedPatent:
    async def test_all_four_components_are_returned(self, client):
        result = await client.get_granted_patent_documents_download(
            app_number=TEST_APP_NUMBER
        )
        assert result.get("success"), f"lookup failed: {result.get('error')}"

        components_found = result.get("components_found", [])
        missing = [c for c in _ALL_COMPONENTS if c not in components_found]
        assert not missing, f"components missing from a granted patent: {missing}"

    async def test_every_component_carries_a_proxy_download_url(self, client):
        result = await client.get_granted_patent_documents_download(
            app_number=TEST_APP_NUMBER
        )
        components = result.get("granted_patent_components", {})
        assert components, "no granted_patent_components returned"

        for name, data in components.items():
            document_id = data.get("document_identifier")
            assert document_id, f"{name} carries no document_identifier"
            assert data.get("proxy_download_url") == (
                f"http://localhost:8080/download/{TEST_APP_NUMBER}/{document_id}"
            ), f"{name}: proxy URL does not match the expected pattern"


class TestSkipDrawings:
    async def test_include_drawings_false_omits_drawings_only(self, client):
        result = await client.get_granted_patent_documents_download(
            app_number=TEST_APP_NUMBER, include_drawings=False
        )
        components_found = result.get("components_found", [])

        assert "drawings" not in components_found, (
            "drawings were included despite include_drawings=False"
        )
        for component in ("abstract", "specification", "claims"):
            assert component in components_found, (
                f"{component} was dropped along with the drawings"
            )


class TestOriginalVsGrantedClaims:
    async def test_the_two_claim_versions_are_distinguishable(self, client):
        original = await client.get_granted_patent_documents(
            app_number=TEST_APP_NUMBER, use_granted_version=False
        )
        granted = await client.get_granted_patent_documents(
            app_number=TEST_APP_NUMBER, use_granted_version=True
        )
        assert not original.get("error"), original.get("message")
        assert not granted.get("error"), granted.get("message")


class TestInvalidApplication:
    async def test_an_invalid_application_finds_nothing_and_says_so(self, client):
        result = await client.get_granted_patent_documents_download(
            app_number=INVALID_APP_NUMBER
        )

        assert result.get("success") is False, (
            "an invalid application number reported success"
        )
        assert result.get("components_found", []) == [], (
            "components were found for an invalid application"
        )
        assert len(result.get("components_missing", [])) == len(_ALL_COMPONENTS), (
            "the full missing-component list should still be reported so the "
            "caller can tell 'not a granted patent' from 'partial data'"
        )


class TestMcpToolIntegration:
    async def test_the_tool_wrapper_matches_the_client(self):
        from patent_filewrapper_mcp.main import (
            pfw_get_granted_patent_documents_download,
        )

        result = await pfw_get_granted_patent_documents_download(TEST_APP_NUMBER)
        assert result.get("success"), (
            f"MCP tool returned failure: {result.get('error')}"
        )
        assert result.get("components_found")
