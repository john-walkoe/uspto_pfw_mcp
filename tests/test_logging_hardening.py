"""Tests for the content-minimization logging posture.

Covers the three guarantees:
1. The sink-level SanitizingFilter scrubs secrets/credentials from every
   record regardless of which logger emitted it (raw logging.getLogger
   included), message and traceback alike.
2. Extraction/search code paths log character counts, never content.
3. Auth-failure paths log an event but never the presented key/token.
"""

import io
import logging
import re
from pathlib import Path

import pytest

from patent_filewrapper_mcp.shared.log_sanitizer import SanitizingFilter

SRC_DIR = Path(__file__).parent.parent / "src" / "patent_filewrapper_mcp"

# 30 alphanumeric chars — matches the USPTO API key shape the sanitizer masks
PLANTED_SECRET = "abcdefghijklmnopqrstuvwxyzabcd"
PLANTED_LINK_HASH = "deadbeefdeadbeefdeadbeef"  # sha256[:24]-style hex
PLANTED_QUERY_URL = (
    "https://ppubs.uspto.gov/dirsearch-public/searches/searchWithBeFamily"
    "?q=quantum+computing+qubit"
)


def _capture_logger(name: str):
    """Raw logging.getLogger wired to a StringIO handler with the sink filter."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(SanitizingFilter())
    raw_logger = logging.getLogger(name)
    raw_logger.setLevel(logging.DEBUG)
    raw_logger.handlers = [handler]
    raw_logger.propagate = False
    return raw_logger, stream


class TestSinkFilter:
    """SanitizingFilter must scrub records at the handler, not the call site."""

    def test_scrubs_secret_query_and_link_hash_from_raw_logger(self):
        raw_logger, stream = _capture_logger("test_raw_bypass")

        raw_logger.info(
            f"key={PLANTED_SECRET} url={PLANTED_QUERY_URL} "
            f"link=/document/persistent/{PLANTED_LINK_HASH}"
        )
        output = stream.getvalue()

        assert PLANTED_SECRET not in output
        assert "quantum" not in output
        assert PLANTED_LINK_HASH not in output
        assert "[LINK_HASH]" in output
        assert "[QUERY_REDACTED]" in output

    def test_scrubs_exception_tracebacks(self):
        # Handlers format exc_info AFTER filters run — the filter must
        # pre-render and sanitize the traceback text.
        raw_logger, stream = _capture_logger("test_raw_exc")

        try:
            raise RuntimeError(f"boom {PLANTED_SECRET}")
        except RuntimeError:
            raw_logger.error("operation failed", exc_info=True)
        output = stream.getvalue()

        assert "operation failed" in output
        assert "RuntimeError" in output
        assert PLANTED_SECRET not in output

    def test_setup_logging_attaches_filter_to_all_handlers(self, tmp_path, monkeypatch):
        from patent_filewrapper_mcp.config.log_config import setup_logging

        monkeypatch.setenv("LOG_DIR", str(tmp_path))
        root = logging.getLogger()
        saved_handlers = list(root.handlers)
        saved_level = root.level
        security = logging.getLogger("security")
        saved_security = list(security.handlers)
        try:
            setup_logging()
            # Only assert on handlers setup_logging itself added — pytest's
            # log-capture handler also lives on the root logger
            added_root = [h for h in root.handlers if h not in saved_handlers]
            added_security = [h for h in security.handlers if h not in saved_security]
            assert added_root, "setup_logging added no root handlers"
            # Single-owner rule (audit C1): setup_logging must NOT attach
            # handlers to the 'security' logger — SecurityLogger owns it.
            assert not added_security, "setup_logging must not touch the security logger"
            for handler in added_root:
                assert any(
                    isinstance(f, SanitizingFilter) for f in handler.filters
                ), f"handler {handler} missing SanitizingFilter"
        finally:
            for h in list(root.handlers):
                root.removeHandler(h)
                h.close()
            for h in saved_handlers:
                root.addHandler(h)
            root.setLevel(saved_level)
            for h in [h for h in security.handlers if h not in saved_security]:
                security.removeHandler(h)
                h.close()


class TestSecurityLoggerSanitized:
    """Audit C1: the 'security' logger must never carry an unfiltered handler,
    regardless of import order between setup_logging() and the SecurityLogger
    singleton."""

    def test_security_logger_handlers_all_carry_sanitizing_filter(self):
        # Import in the same order main.py does — singleton created on import
        import patent_filewrapper_mcp.util.security_logger  # noqa: F401
        import patent_filewrapper_mcp.proxy.server  # noqa: F401

        security = logging.getLogger("security")
        assert security.handlers, "security logger has no handlers"
        for handler in security.handlers:
            assert any(
                isinstance(f, SanitizingFilter) for f in handler.filters
            ), f"security handler {handler} missing SanitizingFilter"

    def test_security_events_are_sanitized_end_to_end(self, caplog):
        from patent_filewrapper_mcp.util.security_logger import security_logger

        # Re-check filter presence, then verify a token passed into an event
        # never reaches a handler unredacted via the filter itself
        record = logging.LogRecord(
            name="security", level=logging.INFO, pathname=__file__, lineno=1,
            msg='{"event_type": "auth_failure", "reason": "x-api-key=SuperSecretToken123456"}',
            args=(), exc_info=None,
        )
        for handler in security_logger.logger.handlers:
            for f in handler.filters:
                f.filter(record)
        assert "SuperSecretToken123456" not in record.getMessage()


class TestNoContentInLogCalls:
    """No extraction/search path may interpolate raw content into a log."""

    # f-string interpolation of a raw content variable; {len(text)} does not match
    _CONTENT_INTERPOLATION = re.compile(
        r'logger\.\w+\([^)]*\{(extracted_text|full_content|page_text|ocr_text|markdown'
        r'|response\.text|query)\}'
    )

    @pytest.mark.parametrize("relative_path", [
        "api/enhanced_client.py",
        "api/ppubs/client.py",
        "api/oa_text_client.py",
        "services/ocr_service.py",
        "api/docling_client.py",
        "util/logging.py",
    ])
    def test_no_raw_content_interpolation_in_log_calls(self, relative_path):
        source = (SRC_DIR / relative_path).read_text(encoding="utf-8")
        matches = self._CONTENT_INTERPOLATION.findall(source)
        assert not matches, (
            f"{relative_path} logs raw content variable(s): {matches} — "
            "log character counts, never content"
        )


class TestAuthFailureLogging:
    """Auth failures log an event and never the presented credential."""

    @pytest.mark.asyncio
    async def test_proxy_token_failure_logs_event_not_token(self, caplog):
        from starlette.requests import Request
        from fastapi import HTTPException
        from patent_filewrapper_mcp.proxy.server import ProxyTokenDependency

        presented = "totally-wrong-token-value-123456789"
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/download/12345678/DOC123",
            "query_string": b"",
            "headers": [(b"x-proxy-token", presented.encode())],
            "client": ("127.0.0.1", 55555),
        }
        request = Request(scope)

        with caplog.at_level(logging.WARNING):
            with pytest.raises(HTTPException) as exc_info:
                await ProxyTokenDependency()(request)

        assert exc_info.value.status_code == 401
        assert "Proxy token" in caplog.text
        assert presented not in caplog.text
