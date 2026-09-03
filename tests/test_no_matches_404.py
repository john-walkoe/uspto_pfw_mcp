"""Unit tests for the no-matches-404 -> empty-result mapping (audit fix,
ported from the sibling uspto_fpd_mcp / uspto_ptab_mcp repos).

The USPTO PFW API signals zero matching records with HTTP 404 +
detailedMessage "No matching records found, refine your search criteria and
try again". Before this fix, EnhancedPatentClient.search_applications()
surfaced that 404 as a raw error envelope instead of an empty result set.

These tests mock EnhancedPatentClient._make_request so no network access is
required, following the pattern in tests/test_ocr_hybrid_tiers.py.
"""
import pytest

from patent_filewrapper_mcp import client_registry
from patent_filewrapper_mcp.api.enhanced_client import EnhancedPatentClient, _is_no_matches_error
from patent_filewrapper_mcp.api.helpers import format_error_response

# Representative raw USPTO 404 body for a zero-match search. The exact JSON
# shape doesn't matter to the fix -- format_error_response() folds the whole
# response body into "message", and the marker check is a substring test.
_NO_MATCH_BODY = (
    '{"error":"Not Found","errorDetails":['
    '{"detailedMessage":"No matching records found, refine your search '
    'criteria and try again"}]}'
)


def _no_match_404():
    return format_error_response(f"API error: {_NO_MATCH_BODY}", 404, "req-1")


def _real_404():
    """A genuine by-id 404 (application/document truly not found) -- does
    NOT carry the no-matching-records marker and must pass through raw."""
    return format_error_response('API error: {"error":"Not Found"}', 404, "req-2")


def _auth_failure_500():
    return format_error_response("API error: server error", 500, "req-3")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("USPTO_API_KEY", "test-uspto-key-0123456789")
    return EnhancedPatentClient()


# ---------------------------------------------------------------------------
# _is_no_matches_error marker check
# ---------------------------------------------------------------------------

def test_is_no_matches_error_true_for_marker_in_message():
    assert _is_no_matches_error(_no_match_404()) is True


def test_is_no_matches_error_false_for_plain_404():
    assert _is_no_matches_error(_real_404()) is False


def test_is_no_matches_error_false_for_non_404():
    err = dict(_no_match_404())
    err["status_code"] = 500
    assert _is_no_matches_error(err) is False


def test_is_no_matches_error_checks_message_not_error_bool():
    # format_error_response()'s "error" key is a bool (True), never text --
    # the marker must be matched against "message", not "error".
    result = _no_match_404()
    assert result["error"] is True
    assert _is_no_matches_error(result) is True


# ---------------------------------------------------------------------------
# EnhancedPatentClient.search_applications chokepoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_applications_no_matches_returns_empty_with_note(client, monkeypatch):
    async def fake_request(endpoint, method="GET", **kwargs):
        return _no_match_404()

    monkeypatch.setattr(client, "_make_request", fake_request)

    result = await client.search_applications("applicantName:NoSuchCompanyXYZ", limit=10, offset=0)

    assert result["success"] is True
    assert result["count"] == 0
    assert result["total"] == 0
    assert result["applications"] == []
    assert "note" in result
    assert "HTTP 404" in result["note"]


@pytest.mark.asyncio
async def test_search_applications_real_404_passes_through_raw(client, monkeypatch):
    async def fake_request(endpoint, method="GET", **kwargs):
        return _real_404()

    monkeypatch.setattr(client, "_make_request", fake_request)

    result = await client.search_applications("applicationNumberText:00000000", limit=1, offset=0)

    assert result.get("error") is True
    assert result.get("status_code") == 404
    assert "note" not in result
    assert "applications" not in result


@pytest.mark.asyncio
async def test_search_applications_non_404_error_passes_through_raw(client, monkeypatch):
    async def fake_request(endpoint, method="GET", **kwargs):
        return _auth_failure_500()

    monkeypatch.setattr(client, "_make_request", fake_request)

    result = await client.search_applications("query", limit=1, offset=0)

    assert result.get("error") is True
    assert result.get("status_code") == 500
    assert "note" not in result


# ---------------------------------------------------------------------------
# search_inventor path: pre-existing "swallow all dict errors" behavior must
# stay exactly as-is (not touched by this fix, not newly broken by it).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_inventor_no_matches_stays_empty_no_crash(client, monkeypatch):
    async def fake_request(endpoint, method="GET", **kwargs):
        return _no_match_404()

    monkeypatch.setattr(client, "_make_request", fake_request)

    result = await client.search_inventor("Nobody Nowhere", strategy="exact", limit=10)

    assert result["success"] is True
    assert result["total_unique_applications"] == 0
    assert result["unique_applications"] == []


@pytest.mark.asyncio
async def test_search_inventor_real_error_stays_empty_no_crash(client, monkeypatch):
    # Pre-existing bug (deliberately untouched): search_inventor swallows
    # ALL dict-shaped errors -- including real ones -- into an empty result
    # rather than surfacing them. Confirms that behavior is unchanged.
    async def fake_request(endpoint, method="GET", **kwargs):
        return _auth_failure_500()

    monkeypatch.setattr(client, "_make_request", fake_request)

    result = await client.search_inventor("Someone", strategy="exact", limit=10)

    assert result["success"] is True
    assert result["total_unique_applications"] == 0
    assert result["unique_applications"] == []


# ---------------------------------------------------------------------------
# Tool layer: pfw_search_applications_minimal / _balanced (imported from
# main.py, which exposes the registered tool callables -- see main.py's
# _registered_tool_fn / tests/test_download.py for the established pattern).
# ---------------------------------------------------------------------------

@pytest.fixture
def registered_client(monkeypatch, client):
    """Install `client` as the process-wide singleton so the mcp.tool
    callables (which call client_registry._client()) pick it up."""
    monkeypatch.setattr(client_registry, "api_client", client)
    return client


@pytest.mark.asyncio
async def test_pfw_search_applications_minimal_no_matches(registered_client, monkeypatch):
    from patent_filewrapper_mcp.main import pfw_search_applications_minimal

    async def fake_request(endpoint, method="GET", **kwargs):
        return _no_match_404()

    monkeypatch.setattr(registered_client, "_make_request", fake_request)

    result = await pfw_search_applications_minimal(applicant_name="NoSuchCompanyXYZ")

    assert result["success"] is True
    assert result["count"] == 0
    assert result["applications"] == []
    assert "note" in result
    assert "HTTP 404" in result["note"]


@pytest.mark.asyncio
async def test_pfw_search_applications_balanced_no_matches(registered_client, monkeypatch):
    from patent_filewrapper_mcp.main import pfw_search_applications_balanced

    async def fake_request(endpoint, method="GET", **kwargs):
        return _no_match_404()

    monkeypatch.setattr(registered_client, "_make_request", fake_request)

    result = await pfw_search_applications_balanced(applicant_name="NoSuchCompanyXYZ")

    assert result["success"] is True
    assert result["count"] == 0
    assert result["applications"] == []
    assert "note" in result
    assert "HTTP 404" in result["note"]


@pytest.mark.asyncio
async def test_pfw_search_applications_minimal_real_404_stays_error(registered_client, monkeypatch):
    from patent_filewrapper_mcp.main import pfw_search_applications_minimal

    async def fake_request(endpoint, method="GET", **kwargs):
        return _real_404()

    monkeypatch.setattr(registered_client, "_make_request", fake_request)

    result = await pfw_search_applications_minimal(applicant_name="Anything")

    assert result.get("error") is True
    assert result.get("status_code") == 404
    assert "note" not in result
