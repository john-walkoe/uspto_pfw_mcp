"""Error dispatch, guidance accuracy, and the two apps' header sets
(audits Q-3, D-10, R-6, L-14, L-15, I-6, error-handling F-4, F-5,
exception-flow F-5, F-7).
"""

import inspect

import pytest

from patent_filewrapper_mcp import server_bootstrap
from patent_filewrapper_mcp.api.helpers import ERROR_TEMPLATES
from patent_filewrapper_mcp.exceptions import (
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
    PatentFileWrapperError,
    RateLimitError,
    RequestTimeoutError,
    USPTOAPIError,
    ValidationError,
)
from patent_filewrapper_mcp.util.error_handlers import _handle_exception


class TestErrorDispatch:
    """`_handle_exception` had ten `elif isinstance` arms and `util/` had
    17 of 84 statements executed, so most arms had never run: a wrong arm
    returns a plausible envelope with the wrong status and nothing fails
    (audits Q-3, T-2)."""

    @pytest.mark.parametrize(
        "exc, expected_status, expected_type",
        [
            (ValidationError("bad"), 400, "validation_error"),
            (AuthenticationError("no key"), 401, "api_auth_failed"),
            (AuthorizationError("nope"), 403, "authorization_error"),
            (NotFoundError("gone"), 404, "document_not_found"),
            (RequestTimeoutError("slow"), 408, "api_timeout"),
            (RateLimitError("too fast"), 429, "rate_limit_exceeded"),
            (ValueError("plain"), 400, "validation_error"),
            (RuntimeError("boom"), 500, "unexpected_error"),
        ],
    )
    def test_every_dispatch_arm(self, exc, expected_status, expected_type):
        result = _handle_exception(exc, "some_tool")
        assert result["success"] is False
        assert result["status_code"] == expected_status
        assert result["error_type"] == expected_type

    @pytest.mark.parametrize(
        "exc",
        [
            ValidationError("bad"),
            AuthenticationError("no key"),
            NotFoundError("gone"),
            RequestTimeoutError("slow"),
            RateLimitError("too fast"),
            ValueError("plain"),
        ],
    )
    def test_every_templated_error_carries_actionable_guidance(self, exc):
        """This failed for ValidationError before: "validation_error" was not
        a key in ERROR_TEMPLATES, so it fell through to the generic
        "Please check your request parameters and try again." (audit Q-3)."""
        result = _handle_exception(exc, "some_tool")
        assert result.get("guidance"), "every error must carry guidance"
        assert "check your request parameters and try again" not in result[
            "guidance"
        ].lower(), "still falling through to the generic default"

    def test_a_keyerror_is_a_server_error_not_a_client_one(self):
        """A KeyError walking a USPTO response is a schema change or a bug,
        not bad client input (audit exception-flow F-7)."""
        result = _handle_exception(KeyError("grantDocumentMetaData"), "some_tool")
        assert result["status_code"] == 500
        assert result["error_type"] == "upstream_schema_error"

    def test_a_keyerror_does_not_name_the_internal_field_to_the_caller(self):
        result = _handle_exception(KeyError("grantDocumentMetaData"), "some_tool")
        assert "grantDocumentMetaData" not in result["message"]

    def test_subclass_ordering_is_preserved(self):
        """PatentFileWrapperError is the base of five entries above it and
        must stay last, USPTOAPIError before it."""
        assert _handle_exception(RateLimitError("x"), "t")["status_code"] == 429
        assert (
            _handle_exception(USPTOAPIError("x", 503), "t")["error_type"]
            == "uspto_api_error"
        )
        assert (
            _handle_exception(PatentFileWrapperError("x"), "t")["error_type"]
            == "patent_filewrapper_error"
        )


class TestGuidanceAccuracy:
    """These strings are read by the MODEL that called the tool, so a stale
    number produces a wrong retry (audits D-10, R-6)."""

    def test_the_limit_guidance_names_the_real_ceiling(self):
        from patent_filewrapper_mcp.models.search_params import MAX_SEARCH_LIMIT

        guidance = ERROR_TEMPLATES["invalid_limit"]["guidance"]
        assert str(MAX_SEARCH_LIMIT) in guidance
        assert "500" not in guidance, "still advertises the old 1-500 ceiling"

    def test_the_limit_guidance_says_over_ceiling_clamps(self):
        assert "clamp" in ERROR_TEMPLATES["invalid_limit"]["guidance"].lower()

    def test_the_inventor_name_guidance_names_the_real_length(self):
        from patent_filewrapper_mcp.api.enhanced_client import EnhancedPatentClient

        guidance = ERROR_TEMPLATES["invalid_inventor_name"]["guidance"]
        assert str(EnhancedPatentClient.MAX_NAME_LENGTH) in guidance

    def test_the_guidance_numbers_are_interpolated_not_restated(self):
        """guidance.py already interpolates; these two were the holdouts."""
        import patent_filewrapper_mcp.api.helpers as helpers

        source = inspect.getsource(helpers)
        assert "_MAX_SEARCH_LIMIT" in source

    @pytest.mark.parametrize("key", ["validation_error", "missing_field"])
    def test_the_keys_the_dispatcher_asks_for_exist(self, key):
        assert key in ERROR_TEMPLATES


class TestSecurityHeaders:
    def test_the_two_apps_share_one_header_set(self):
        """Neither set was a superset of the other: the MCP side had HSTS and
        no Referrer-Policy, the proxy the reverse (audit L-15)."""
        from patent_filewrapper_mcp.middleware import COMMON_SECURITY_HEADERS

        names = {name for name, _ in COMMON_SECURITY_HEADERS}
        assert names == {
            "x-content-type-options",
            "x-frame-options",
            "strict-transport-security",
            "referrer-policy",
        }

    def test_the_dead_xss_header_is_gone(self):
        """X-XSS-Protection does nothing in any current browser and its legacy
        form was itself an XSS vector (audit I-6)."""
        from patent_filewrapper_mcp.middleware import COMMON_SECURITY_HEADERS
        from patent_filewrapper_mcp.proxy import server

        assert "x-xss-protection" not in {
            name.lower() for name, _ in COMMON_SECURITY_HEADERS
        }
        # Code, not prose: the name legitimately appears in the comment
        # recording why it was removed.
        code = [
            line for line in inspect.getsource(server).splitlines()
            if not line.lstrip().startswith("#")
        ]
        assert not [line for line in code if "X-XSS-Protection" in line]

    def test_the_mcp_middleware_replaces_rather_than_appends(self):
        """Appending meant a framework upgrade emitting its own CSP would ship
        two conflicting values (audit L-14)."""
        from patent_filewrapper_mcp.middleware import SecurityHeadersMiddleware

        source = inspect.getsource(SecurityHeadersMiddleware)
        assert "name.lower() not in _OWNED" in source

    async def test_a_duplicate_header_from_the_app_is_replaced(self):
        from patent_filewrapper_mcp.middleware import SecurityHeadersMiddleware

        sent = []

        async def _app(scope, receive, send):
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"x-frame-options", b"SAMEORIGIN")],
                }
            )

        async def _send(message):
            sent.append(message)

        await SecurityHeadersMiddleware(_app)({"type": "http"}, None, _send)

        frame_options = [
            value for name, value in sent[0]["headers"]
            if name.lower() == b"x-frame-options"
        ]
        assert frame_options == [b"DENY"], (
            f"expected exactly one X-Frame-Options, got {frame_options}"
        )

    def test_the_two_apps_keep_different_csps(self):
        """The MCP transport serves App iframes whose inline scripts are the
        point; the proxy serves only PDFs and JSON."""
        from patent_filewrapper_mcp.middleware import MCP_CSP, PROXY_CSP

        assert "unsafe-inline" in MCP_CSP
        assert PROXY_CSP == "default-src 'none'"


class TestInternalSecretMemoization:
    """The middleware resolved the secret per request: a Path.home(), an
    exists(), a read_bytes() and possibly a BLOCKING 15-second subprocess, on
    the event loop, on every MCP call (audit error-handling F-4)."""

    def test_the_secret_is_resolved_once(self, monkeypatch):
        from patent_filewrapper_mcp import middleware

        middleware.reset_expected_secret()
        calls = []

        def _fake():
            calls.append(1)
            return "the-secret"

        monkeypatch.setattr(
            "patent_filewrapper_mcp.shared_secure_storage.get_internal_auth_secret",
            _fake,
        )
        for _ in range(5):
            assert middleware._expected_secret_candidates() == ["the-secret"]
        assert len(calls) == 1, f"resolved {len(calls)} times, expected 1"
        middleware.reset_expected_secret()

    def test_the_middleware_no_longer_reads_it_per_request(self):
        from patent_filewrapper_mcp.middleware import APIKeyAuthMiddleware

        source = inspect.getsource(APIKeyAuthMiddleware)
        assert "get_internal_auth_secret" not in source
        assert "_expected_secret_candidates()" in source


class TestInternalSecretRotationGate:
    """S-06 / PT-14: INTERNAL_AUTH_SECRET may be a comma-separated rotation
    list (current first, then previous), giving an overlap window instead of
    a synchronized four-service restart."""

    def test_split_secret_candidates_dedupes_strips_and_orders(self):
        from patent_filewrapper_mcp.shared_secure_storage import (
            split_secret_candidates,
        )

        assert split_secret_candidates("a, b ,a,,  ") == ["a", "b"]
        assert split_secret_candidates("solo") == ["solo"]
        assert split_secret_candidates(None) == []
        assert split_secret_candidates("") == []

    def test_a_single_value_still_round_trips(self):
        from patent_filewrapper_mcp.middleware import _matches_any_candidate

        assert _matches_any_candidate("secret", ["secret"]) is True
        assert _matches_any_candidate("wrong", ["secret"]) is False

    def test_the_gate_accepts_current_and_previous(self):
        from patent_filewrapper_mcp.middleware import _matches_any_candidate

        candidates = ["current-value", "previous-value"]
        assert _matches_any_candidate("current-value", candidates) is True
        assert _matches_any_candidate("previous-value", candidates) is True

    def test_the_gate_rejects_a_value_not_in_the_rotation_window(self):
        from patent_filewrapper_mcp.middleware import _matches_any_candidate

        candidates = ["current-value", "previous-value"]
        assert _matches_any_candidate("some-other-value", candidates) is False
        assert _matches_any_candidate(None, candidates) is False
        assert _matches_any_candidate("", candidates) is False

    def test_a_comma_separated_env_secret_gates_both_values(self, monkeypatch):
        from patent_filewrapper_mcp import middleware

        middleware.reset_expected_secret()
        monkeypatch.setattr(
            "patent_filewrapper_mcp.shared_secure_storage.get_internal_auth_secret",
            lambda: None,
        )
        monkeypatch.setenv("INTERNAL_AUTH_SECRET", "new-secret,old-secret")

        candidates = middleware._expected_secret_candidates()

        assert candidates == ["new-secret", "old-secret"]
        assert middleware._matches_any_candidate("new-secret", candidates) is True
        assert middleware._matches_any_candidate("old-secret", candidates) is True
        assert middleware._matches_any_candidate("third-secret", candidates) is False
        middleware.reset_expected_secret()


class TestSafeFilename:
    def test_a_pdf_name_is_untouched(self):
        from patent_filewrapper_mcp.proxy.server import _safe_filename

        assert _safe_filename("DRW.pdf") == "DRW.pdf"

    def test_a_foreign_extension_is_replaced_not_appended(self):
        """"report.html" became "report.html.pdf", a double extension that
        misrepresents the body (audit L-21)."""
        from patent_filewrapper_mcp.proxy.server import _safe_filename

        assert _safe_filename("report.html") == "report.pdf"

    def test_interior_dots_in_a_real_name_survive(self):
        from patent_filewrapper_mcp.proxy.server import _safe_filename

        assert _safe_filename("US.11,752,072.B2") == "US.11,752,072.pdf"

    def test_an_extensionless_name_still_gets_pdf(self):
        from patent_filewrapper_mcp.proxy.server import _safe_filename

        assert _safe_filename("OfficeAction") == "OfficeAction.pdf"


class TestAsyncioHandlerParity:
    def test_the_proxy_thread_installs_the_exception_handler(self):
        """It was installed on the STDIO loop only, so the production HTTP
        path got less treatment than the development one (audit
        error-handling F-5)."""
        source = inspect.getsource(server_bootstrap._start_http_download_proxy)
        assert "set_exception_handler(_asyncio_exception_handler)" in source

