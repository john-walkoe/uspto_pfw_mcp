"""Metered spend is bounded, uploaded documents are cleaned up, credentials
are scoped, and the access-token TTL is the deactivation lag
(audits M-3, M-11, M-13, M-14, resilience F-1, F-8).
"""

import inspect

import pytest

from patent_filewrapper_mcp.proxy import recent_downloads_store as store
from patent_filewrapper_mcp.services.ocr_service import OCRService


@pytest.fixture
def ocr(monkeypatch):
    monkeypatch.setenv("MISTRAL_OCR_DAILY_PAGE_BUDGET", "100")
    return OCRService(api_key="sk-not-a-real-key-just-long-enough")


class TestOcrDailyPageBudget:
    """The per-minute call limit caps the burst rate but not the total: 10
    calls/minute at 50 pages each is 720,000 pages a day of metered spend
    (audit M-14)."""

    def test_a_call_within_budget_is_allowed(self, ocr):
        ocr._check_ocr_daily_budget("req-1", 50)

    def test_a_call_that_would_exceed_the_budget_is_refused(self, ocr):
        from patent_filewrapper_mcp.exceptions import OCRRateLimitError

        ocr._record_ocr_pages(80)
        with pytest.raises(OCRRateLimitError) as exc:
            ocr._check_ocr_daily_budget("req-1", 50)
        assert "budget" in str(exc.value).lower()

    def test_the_refusal_carries_a_retry_hint(self, ocr):
        from patent_filewrapper_mcp.exceptions import OCRRateLimitError

        ocr._record_ocr_pages(100)
        with pytest.raises(OCRRateLimitError) as exc:
            ocr._check_ocr_daily_budget("req-1", 1)
        assert exc.value.retry_after_seconds > 0

    def test_the_budget_resets_on_a_new_day(self, ocr, monkeypatch):
        ocr._check_ocr_daily_budget("req-1", 1)
        ocr._record_ocr_pages(100)
        monkeypatch.setattr(ocr, "_ocr_budget_day", "1999-01-01")
        ocr._check_ocr_daily_budget("req-2", 50)  # must not raise
        assert ocr._ocr_pages_today == 0

    def test_a_budget_of_zero_disables_the_ceiling(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_OCR_DAILY_PAGE_BUDGET", "0")
        service = OCRService(api_key="sk-not-a-real-key-just-long-enough")
        service._record_ocr_pages(10_000_000)
        service._check_ocr_daily_budget("req-1", 50)  # must not raise

    def test_the_budget_is_checked_before_anything_is_uploaded(self):
        """A refusal must cost nothing."""
        source = inspect.getsource(OCRService.extract_document_content)
        budget_at = source.index("_check_ocr_daily_budget")
        upload_at = source.index("/files")
        assert budget_at < upload_at


class TestUploadedFileCleanup:
    """Every OCR'd document accumulated in the Mistral account forever: a
    retention surface for client work product (audit resilience F-8)."""

    def test_the_upload_is_deleted_in_a_finally(self):
        source = inspect.getsource(OCRService.extract_document_content)
        assert "finally:" in source
        assert "_delete_uploaded_file" in source

    async def test_a_cleanup_failure_does_not_propagate(self, ocr):
        class _Exploding:
            async def delete(self, *args, **kwargs):
                raise RuntimeError("network gone")

        await ocr._delete_uploaded_file(_Exploding(), {}, "file-1", "req-1")

    async def test_the_delete_targets_the_files_endpoint(self, ocr):
        seen = {}

        class _Recording:
            async def delete(self, url, headers=None):
                seen["url"] = url

        await ocr._delete_uploaded_file(_Recording(), {}, "file-abc", "req-1")
        assert seen["url"].endswith("/files/file-abc")


class TestOcrTimeoutScalesWithPages:
    def test_the_timeout_is_no_longer_one_flat_value(self):
        """One 30s budget covered the upload AND the OCR of up to 50 pages;
        a timeout meant Mistral had already done and billed the work
        (audit resilience F-1)."""
        source = inspect.getsource(OCRService.extract_document_content)
        assert "MISTRAL_OCR_SECONDS_PER_PAGE" in source
        assert "httpx.Timeout(" in source
        assert '{"timeout": self.ocr_timeout}' not in source


class TestRecentDownloadsScoping:
    """Each entry holds a working /document/persistent/{hash} URL, which is a
    tokenless bearer credential (audit M-3)."""

    def setup_method(self):
        store.clear()

    def test_one_owner_does_not_see_anothers_downloads(self):
        store.register_download("A's doc", "CTNF", "111", "u1", owner="a@x.com")
        store.register_download("B's doc", "CTFR", "222", "u2", owner="b@x.com")

        a_titles = [e["title"] for e in store.get_recent(owner="a@x.com")]
        assert a_titles == ["A's doc"]
        assert "B's doc" not in str(store.get_recent(owner="a@x.com"))

    def test_the_anonymous_bucket_is_separate_from_a_named_one(self):
        store.register_download("local", "CTNF", "111", "u1")
        store.register_download("named", "CTNF", "222", "u2", owner="a@x.com")

        assert [e["title"] for e in store.get_recent()] == ["local"]
        assert [e["title"] for e in store.get_recent(owner="a@x.com")] == ["named"]

    def test_a_blank_owner_falls_into_the_anonymous_bucket(self):
        store.register_download("local", "CTNF", "111", "u1", owner="   ")
        assert [e["title"] for e in store.get_recent()] == ["local"]

    def test_entries_are_newest_first_and_capped(self):
        for i in range(15):
            store.register_download(f"doc{i}", "CTNF", str(i), "u", owner="a@x.com")
        recent = store.get_recent(owner="a@x.com")
        assert len(recent) == 10
        assert recent[0]["title"] == "doc14"

    def test_clearing_one_owner_leaves_the_others(self):
        store.register_download("a", "CTNF", "1", "u", owner="a@x.com")
        store.register_download("b", "CTNF", "2", "u", owner="b@x.com")
        store.clear(owner="a@x.com")
        assert store.get_recent(owner="a@x.com") == []
        assert len(store.get_recent(owner="b@x.com")) == 1

    def test_the_owner_comes_from_a_header_not_the_json_body(self):
        """A caller must not be able to claim another owner's bucket by
        editing the JSON it posts."""
        from patent_filewrapper_mcp.proxy.routes import admin

        source = inspect.getsource(admin.post_register_download)
        assert 'request.headers.get("x-download-owner")' in source
        assert 'payload.get("owner")' not in source


class TestAccessTokenTtl:
    def test_the_access_ttl_is_fifteen_minutes_not_an_hour(self):
        """An access token cannot be revoked, so the TTL IS the deactivation
        lag (audit M-13)."""
        from patent_filewrapper_mcp.auth.settings import AuthSettings

        assert AuthSettings().auth_access_ttl == 900

    def test_the_env_default_matches_the_dataclass_default(self, monkeypatch):
        from patent_filewrapper_mcp.auth.settings import AuthSettings

        monkeypatch.delenv("PFW_AUTH_ACCESS_TTL", raising=False)
        assert AuthSettings.from_env().auth_access_ttl == 900

    def test_it_stays_overridable(self, monkeypatch):
        from patent_filewrapper_mcp.auth.settings import AuthSettings

        monkeypatch.setenv("PFW_AUTH_ACCESS_TTL", "1800")
        assert AuthSettings.from_env().auth_access_ttl == 1800


class TestProxyTokenLifecycle:
    """An auto-generated per-process token means the effective credential is
    unknown and differs between the tool process and a separately-running
    proxy (audit M-11, initial-software-design F-3)."""

    @pytest.fixture(autouse=True)
    def _reset(self, monkeypatch):
        from patent_filewrapper_mcp.proxy import server

        monkeypatch.setattr(server, "_PROXY_TOKEN", None)
        yield
        monkeypatch.setattr(server, "_PROXY_TOKEN", None)

    def test_a_supplied_token_is_used(self, monkeypatch):
        from patent_filewrapper_mcp.proxy.server import _get_proxy_token

        monkeypatch.setenv("PROXY_TOKEN", "a-sufficiently-long-token")
        assert _get_proxy_token() == "a-sufficiently-long-token"

    def test_a_short_token_is_rejected(self, monkeypatch):
        from patent_filewrapper_mcp.proxy.server import _get_proxy_token

        monkeypatch.setenv("PROXY_TOKEN", "short")
        with pytest.raises(RuntimeError, match="at least"):
            _get_proxy_token()

    def test_the_cross_process_deployment_demands_one(self, monkeypatch):
        from patent_filewrapper_mcp.proxy.server import _get_proxy_token

        monkeypatch.delenv("PROXY_TOKEN", raising=False)
        monkeypatch.setenv("ENABLE_ALWAYS_ON_PROXY", "true")
        monkeypatch.setenv("FASTMCP_TRANSPORT", "http")
        with pytest.raises(RuntimeError, match="PROXY_TOKEN is required"):
            _get_proxy_token()

    def test_the_in_process_deployment_still_auto_generates(self, monkeypatch):
        """stdio has no second process that needs to know the value."""
        from patent_filewrapper_mcp.proxy.server import _get_proxy_token

        monkeypatch.delenv("PROXY_TOKEN", raising=False)
        monkeypatch.setenv("FASTMCP_TRANSPORT", "stdio")
        assert len(_get_proxy_token()) >= 16
