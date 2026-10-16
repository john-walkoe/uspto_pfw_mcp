"""The ODP Office Action API port (2026-10-11).

USPTO retired the two datasets PFW_get_oa_rejections and PFW_get_oa_text read
(/api/v1/patent/oa/oa_rejections/v2/records and
/api/v1/patent/oa/oa_actions/v1/records answer an HTML 404 since about
2026-10-10). Both tools now read the ODP Office Action API through
api/office_action_client.py: POST /api/v1/patent/office-action/search for the
records and GET .../{officeActionRecordIdentifier}/download/officeActionText
for the full text.

The fixtures under tests/fixtures/office_action_api/ were RECORDED live on
2026-10-11 with the fleet key, for application 11/752,072 (US 7,971,071):
the search envelope (5 records), the 'No matching records' 404 body, and the
full text of the CTNF of 2010-10-13 and the CTFR of 2009-09-21. The default
run is hermetic: httpx is routed through a MockTransport that serves them.
One live test at the bottom runs only with PFW_RUN_LIVE_TESTS=1 and a real key.
"""

import asyncio
import json
import os
import time
import pathlib

import httpx
import pytest

from conftest import requires_live_uspto
from patent_filewrapper_mcp.api import office_action_client as oac
from patent_filewrapper_mcp.exceptions import USPTOAPIError, ValidationError

_FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "office_action_api"
_REAL_ASYNC_CLIENT = httpx.AsyncClient
_KEY = "test-key-not-a-real-credential"

CTNF_ID = "1af635b1ff383b0d75a9719b284b7b58"  # pragma: allowlist secret
CTFR_ID = "04af5606ecd10d9d8aa3e70579192948"  # pragma: allowlist secret


def _search_fixture():
    return json.loads((_FIXTURES / "search_11752072.json").read_text(encoding="utf-8"))


def _no_match_fixture():
    return json.loads((_FIXTURES / "no_match_404.json").read_text(encoding="utf-8"))


def _text_fixture(record_id):
    path = _FIXTURES / f"text_{record_id}.txt"
    return path.read_text(encoding="utf-8") if path.exists() else None


class _RecordedApi:
    """Serves the recorded responses the way the live API answered them."""

    def __init__(self, search=None, html_404=False):
        self.search = _search_fixture() if search is None else search
        self.html_404 = html_404
        self.requests = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if self.html_404:
            return httpx.Response(404, text="<html>Not Found</html>", headers={"content-type": "text/html"})
        if path.endswith("/office-action/search"):
            body = json.loads(request.content)
            app = body["filters"][0]["value"][0]
            codes = next((f["value"] for f in body["filters"] if f["name"] == "documentCode"), None)
            bag = [
                r for r in self.search["officeActionDataBag"]
                if r["applicationNumberText"] == app and (codes is None or r["documentCode"] in codes)
            ]
            if not bag:
                return httpx.Response(404, json=_no_match_fixture())
            limit = body["pagination"]["limit"]
            return httpx.Response(200, json={**self.search, "count": len(bag), "officeActionDataBag": bag[:limit]})
        if path.endswith("/download/officeActionText"):
            record_id = path.split("/")[-3]
            text = _text_fixture(record_id)
            if text is None:
                return httpx.Response(404, json=_no_match_fixture())
            return httpx.Response(
                200,
                text=text,
                headers={
                    "content-type": "text/plain",
                    "content-disposition": 'attachment;filename="results-2026-10-11T22-51-25.text/plain"',
                },
            )
        return httpx.Response(404, text="<html>Not Found</html>", headers={"content-type": "text/html"})


@pytest.fixture
def api(monkeypatch):
    recorded = _RecordedApi()

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(recorded)
        return _REAL_ASYNC_CLIENT(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return recorded


def _client():
    return oac.OfficeActionClient(api_key=_KEY)


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------

class TestClient:
    async def test_search_sends_the_documented_body(self, api):
        result = await _client().search_office_actions("11752072", document_codes=["ctnf", "CTFR"], limit=10)

        request = api.requests[0]
        assert request.method == "POST"
        assert str(request.url) == f"{oac.BASE_URL}/search"
        assert request.headers["X-API-KEY"] == _KEY
        assert json.loads(request.content) == {
            "filters": [
                {"name": "applicationNumberText", "value": ["11752072"]},
                {"name": "documentCode", "value": ["CTNF", "CTFR"]},
            ],
            "sort": [{"field": "submissionDate", "order": "desc"}],
            "pagination": {"offset": 0, "limit": 10},
        }
        assert result["count"] == 5
        assert [r["submissionDate"] for r in result["officeActionDataBag"]] == [
            "2010-10-13", "2009-09-21", "2009-01-29", "2008-09-30", "2008-09-08",
        ]

    async def test_no_matching_records_is_an_empty_result(self, api):
        result = await _client().search_office_actions("99999999")
        assert result == {"count": 0, "officeActionDataBag": []}

    async def test_an_html_404_raises_instead_of_reading_as_empty(self, monkeypatch):
        """The retired routes answer an HTML 404: that must never pass for 'no
        office actions'."""
        recorded = _RecordedApi(html_404=True)
        monkeypatch.setattr(
            httpx, "AsyncClient",
            lambda *a, **k: _REAL_ASYNC_CLIENT(*a, **{**k, "transport": httpx.MockTransport(recorded)}),
        )
        with pytest.raises(USPTOAPIError) as caught:
            await _client().search_office_actions("11752072")
        assert caught.value.status_code == 404
        assert "HTML" in str(caught.value)

    async def test_the_full_text_is_the_plain_text_download(self, api):
        text = await _client().get_office_action_text(CTNF_ID)

        assert str(api.requests[0].url) == f"{oac.BASE_URL}/{CTNF_ID}/download/officeActionText"
        assert text == _text_fixture(CTNF_ID)
        assert len(text.encode("utf-8")) == 24_178  # measured live 2026-10-11

    async def test_the_documented_json_wrapper_is_accepted_too(self, monkeypatch):
        monkeypatch.setattr(
            httpx, "AsyncClient",
            lambda *a, **k: _REAL_ASYNC_CLIENT(*a, **{**k, "transport": httpx.MockTransport(
                lambda r: httpx.Response(200, json={"officeActionText": "DETAILED ACTION x"}))}),
        )
        assert await _client().get_office_action_text(CTNF_ID) == "DETAILED ACTION x"

    async def test_a_record_without_text_reads_as_none(self, api):
        assert await _client().get_office_action_text("0" * 32) is None

    async def test_a_malformed_identifier_never_reaches_uspto(self, api):
        with pytest.raises(ValidationError):
            await _client().get_office_action_text("../../applications")
        with pytest.raises(ValidationError):
            await _client().search_office_actions("11/752,072")
        assert api.requests == []


def test_rejection_types_normalise_both_documented_forms():
    assert oac.normalize_rejection_types(["102", "103", "112", "Other"]) == ["102", "103", "112", "Other"]
    assert oac.normalize_rejection_types(["35 U.S.C. 102", "35 U.S.C. 103", "103"]) == ["102", "103"]
    assert oac.normalize_rejection_types(["Double Patenting", "DoublePatent"]) == ["DoublePatent"]
    assert oac.normalize_rejection_types(None) == []


def test_sections_are_cut_at_the_office_actions_own_headings():
    body = _text_fixture(CTNF_ID)

    excerpt_103 = oac.extract_section_text(body, "103")
    assert excerpt_103.startswith("Claim Rejections - 35 USC § 103")
    assert excerpt_103.count("rejected under 35 U.S.C. 103") == 2
    assert "Conclusion" not in excerpt_103
    excerpt_102 = oac.extract_section_text(body, "102")
    assert "102(e)" in excerpt_102 and "103(a)" not in excerpt_102
    assert oac.extract_section_text(body, "101") == ""


# ---------------------------------------------------------------------------
# The two tools over the recorded responses
# ---------------------------------------------------------------------------

class _CaptureMCP:
    def __init__(self):
        self.tools = {}

    def tool(self, *args, **kwargs):
        def decorator(fn):
            self.tools[kwargs.get("name") or fn.__name__] = fn
            return fn
        return decorator


class _ResolvingClient:
    """The PFW search client, for identifier resolution and the census only."""

    async def lookup_identifier_lane(self, query):
        if query == "applicationNumberText:11752072":
            return {"applicationNumberText": "11752072"}
        return None

    async def get_documents(self, app_number, **kwargs):
        codes = ["CTNF", "CTNF", "CTNF", "CTFR", "CTFR", "NOA", "REM"]
        return {"application_number": app_number, "documentBag": [{"documentCode": c} for c in codes]}


@pytest.fixture
def tools(api, monkeypatch):
    from patent_filewrapper_mcp.tools import oa_tools

    monkeypatch.setattr(oa_tools, "_client", lambda: _ResolvingClient())
    monkeypatch.setattr(oa_tools, "_office_action_client", _client())
    fake = _CaptureMCP()
    oa_tools.register(fake)
    return fake.tools


def _text_downloads(api):
    return [r for r in api.requests if r.url.path.endswith("/download/officeActionText")]


class TestRejectionsTool:
    async def test_rows_come_from_the_bag_and_the_text(self, tools, api):
        result = await tools["PFW_get_oa_rejections"]("11/752,072")

        assert result["success"] is True
        assert result["num_found"] == 5 and result["showing"] == 5
        assert json.loads(api.requests[0].content)["filters"][1] == {
            "name": "documentCode", "value": ["CTNF", "CTFR"],
        }
        rows = {r["submission_date"]: r for r in result["rejections"]}
        ctnf = rows["2010-10-13"]
        assert ctnf["doc_code"] == "CTNF"
        assert ctnf["office_action_id"] == CTNF_ID
        assert ctnf["document_identifier"] == "GF7AGXYVPPOPPY5"
        assert ctnf["rejection_types"] == ["102", "103", "112", "Other"]
        assert ctnf["section_counts"] == {"101": 0, "102": 1, "103": 2, "112": 1}
        assert ctnf["has_103"] is True and ctnf["has_102"] is True
        assert ctnf["cite_as"].startswith("[CTNF 2010-10-13, application 11/752,072]")
        # The bag and the text disagree on the 2009-09-21 CTFR: the bag says
        # 112, the text withdraws the § 112 rejections and rejects under § 102(e).
        ctfr = rows["2009-09-21"]
        assert ctfr["rejection_types"] == ["103", "112"]
        assert ctfr["section_counts"] == {"101": 0, "102": 1, "103": 2, "112": 0}
        assert ctfr["has_112"] is True and ctfr["has_103"] is True
        # Fields the new API does not publish stay as keys, null.
        for key in ("alice", "mayo", "bilski", "myriad", "cite_103_max", "allowed_claims", "claims"):
            assert ctnf[key] is None
        summary = result["summary"]
        # Two of the five actions have recorded text (2 + 2 statements under § 103).
        assert summary["section_counts"]["103"] == 4
        assert summary["office_actions_text_unavailable"] == 3
        assert summary["office_actions_by_rejection_type"]["103"] == 5
        assert summary["alice_indicator"] is None and summary["max_103_citations"] is None
        assert "retired" in summary["retired_fields_note"]

    async def test_text_is_fetched_only_for_the_rows_returned(self, tools, api):
        result = await tools["PFW_get_oa_rejections"]("11/752,072", rows=2)

        assert result["showing"] == 2 and result["num_found"] == 5 and result["has_more"] is True
        assert len(_text_downloads(api)) == 2
        assert {r["office_action_id"] for r in result["rejections"]} == {CTNF_ID, CTFR_ID}

    async def test_latest_only_returns_one_row(self, tools, api):
        result = await tools["PFW_get_oa_rejections"]("11/752,072", latest_only=True)

        assert result["rows_applied"] == 1
        assert [r["submission_date"] for r in result["rejections"]] == ["2010-10-13"]
        assert len(_text_downloads(api)) == 1

    async def test_a_record_with_no_text_keeps_its_bag(self, tools, api):
        result = await tools["PFW_get_oa_rejections"]("11/752,072", rows=3)

        oldest = result["rejections"][-1]
        assert oldest["submission_date"] == "2009-01-29"
        assert oldest["text_available"] is False
        assert oldest["section_counts"] is None
        assert oldest["has_103"] is True  # the bag stands alone when no text was read
        assert result["summary"]["office_actions_text_unavailable"] == 1


class TestTextTool:
    async def test_latest_ctfr_is_the_2009_final(self, tools, api):
        result = await tools["PFW_get_oa_text"]("11/752,072", action_type="CTFR")

        assert result["success"] is True
        assert result["submission_date"] == "2009-09-21"
        assert result["office_action_id"] == CTFR_ID
        assert result["text"] == _text_fixture(CTFR_ID)
        assert result["text_total_chars"] == len(_text_fixture(CTFR_ID))
        assert result["documents_by_code"]["CTFR"] == 2
        assert len(_text_downloads(api)) == 1  # the latest only, never the list

    async def test_without_action_type_the_search_is_limited_to_office_actions(self, tools, api):
        result = await tools["PFW_get_oa_text"]("11/752,072")

        sent = json.loads(api.requests[0].content)["filters"][1]
        assert sent["name"] == "documentCode"
        assert set(sent["value"]) == set(result["action_types_served"])
        assert result["submission_date"] == "2010-10-13"

    async def test_section_103_is_the_action_s_own_103_section(self, tools, api):
        result = await tools["PFW_get_oa_text"]("11/752,072", action_type="CTNF", section="103")

        assert result["section_returned"] == "103"
        assert result["text"].startswith("Claim Rejections - 35 USC § 103")
        assert "section_partial" not in result

    async def test_noa_is_served(self, tools, api):
        """NOA records exist in the ODP index (4,759,100 on 2026-10-11, with
        text). This application's NOA is not among them, which is the coverage
        gap documents_by_code makes visible."""
        result = await tools["PFW_get_oa_text"]("11/752,072", action_type="NOA")

        assert result["success"] is True and result["num_found"] == 0
        assert result["documents_by_code"]["NOA"] == 1
        assert "COVERAGE GAP" in result["documents_by_code_note"]


# ---------------------------------------------------------------------------
# Live (opt-in): PFW_RUN_LIVE_TESTS=1 and a real USPTO_API_KEY
# ---------------------------------------------------------------------------

@requires_live_uspto
async def test_live_office_action_api_still_answers_as_recorded():
    client = oac.OfficeActionClient(api_key=os.environ["USPTO_API_KEY"])

    result = await client.search_office_actions("11752072", document_codes=["CTNF", "CTFR"], limit=10)
    by_id = {r["officeActionRecordIdentifier"]: r for r in result["officeActionDataBag"]}
    assert by_id[CTNF_ID]["submissionDate"] == "2010-10-13"
    assert oac.normalize_rejection_types(by_id[CTNF_ID]["rejectionTypeBag"]) == ["102", "103", "112", "Other"]
    assert by_id[CTFR_ID]["submissionDate"] == "2009-09-21"

    text = await client.get_office_action_text(CTNF_ID)
    assert text and "rejected under 35 U.S.C. 103" in text


# ---------------------------------------------------------------------------
# Full-text fan-out cap and deadline (audit 2026-10-12 M1)
# ---------------------------------------------------------------------------


class TestTextFetchCap:
    async def test_rejections_read_text_for_the_newest_rows_only(self, tools, api, monkeypatch):
        from patent_filewrapper_mcp.tools import oa_tools

        monkeypatch.setattr(oa_tools, "OA_TEXT_FETCH_CAP", 2)
        result = await tools["PFW_get_oa_rejections"]("11/752,072", rows=5)

        assert result["showing"] == 5
        assert len(_text_downloads(api)) == 2
        dates = [r["submission_date"] for r in result["rejections"]]
        assert dates == sorted(dates, reverse=True)
        head, tail = result["rejections"][:2], result["rejections"][2:]
        assert {r["office_action_id"] for r in head} == {CTNF_ID, CTFR_ID}
        for row in tail:
            assert row["text_available"] is False
            assert row["section_counts"] is None
            assert "text_fetch_cap" in row["text_error"]
            assert row["rejection_types"]  # the bag stays
        cap = result["text_fetch_cap"]
        assert cap == {"cap": 2, "rows": 5, "texts_fetched": 2, "note": cap["note"]}
        assert "latest_only" in cap["note"] and "2 rows" in cap["note"]

    async def test_no_cap_block_when_the_cap_did_not_cut(self, tools, api):
        result = await tools["PFW_get_oa_rejections"]("11/752,072", rows=5)
        assert "text_fetch_cap" not in result
        assert len(_text_downloads(api)) == 5

    async def test_a_hundred_rows_cost_at_most_the_cap_in_downloads(self, monkeypatch):
        from patent_filewrapper_mcp.tools import oa_tools

        docs = [{"officeActionRecordIdentifier": f"{i:032x}", "submissionDate": f"2020-01-{i % 28 + 1:02d}",
                 "documentCode": "CTNF", "rejectionTypeBag": ["103"]} for i in range(100)]
        calls = []

        class _Client:
            async def search_office_actions(self, *a, **k):
                return {"count": 100, "officeActionDataBag": docs}

            async def get_office_action_text(self, record_id):
                calls.append(record_id)
                return "Claims 1-3 are rejected under 35 U.S.C. 103."

        monkeypatch.setattr(oa_tools, "_client", lambda: _ResolvingClient())
        monkeypatch.setattr(oa_tools, "_office_action_client", _Client())
        result = await oa_tools._get_oa_rejections("11/752,072", False, 100, "auto")
        assert len(calls) == oa_tools.OA_TEXT_FETCH_CAP == 10
        assert result["showing"] == 100
        assert sum(r["text_available"] for r in result["rejections"]) == 10
        assert result["text_fetch_cap"]["texts_fetched"] == 10

    async def test_the_deadline_returns_what_arrived_and_cancels_the_rest(self):
        from patent_filewrapper_mcp.tools import oa_tools

        cancelled = []

        class _Slow:
            async def get_office_action_text(self, record_id):
                if record_id == "fast":
                    return "text"
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    cancelled.append(record_id)
                    raise

        docs = [{"officeActionRecordIdentifier": rid} for rid in ("fast", "slow1", "slow2")]
        texts = await oa_tools._fetch_texts(_Slow(), docs, tolerate_errors=False, deadline_s=0.2)
        assert texts[0] == ("text", None)
        assert texts[1][0] is None and "deadline" in texts[1][1]
        assert texts[2][0] is None and "deadline" in texts[2][1]
        assert sorted(cancelled) == ["slow1", "slow2"]  # both cancelled mid-download, none left running

    async def test_a_429_cancels_the_siblings(self):
        from patent_filewrapper_mcp.tools import oa_tools

        started, cancelled = [], []

        class _Limited:
            async def get_office_action_text(self, record_id):
                started.append(record_id)
                if record_id == "a":
                    raise oa_tools.UpstreamRateLimitedError({"success": False, "rate_limited": True})
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    cancelled.append(record_id)
                    raise

        docs = [{"officeActionRecordIdentifier": rid} for rid in ("a", "b", "c", "d")]
        began = time.monotonic()
        with pytest.raises(oa_tools.UpstreamRateLimitedError):
            await oa_tools._fetch_texts(_Limited(), docs, tolerate_errors=True, deadline_s=5)
        assert time.monotonic() - began < 2  # returned on the 429, not at the deadline
        assert "d" not in started
        assert sorted(cancelled) == sorted(r for r in started if r != "a")
