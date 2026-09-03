"""Rate-limit buckets are per policy, and rotated log backups are 0600
(audits L-1, L-3).
"""

import logging
import os
import stat

import pytest

from patent_filewrapper_mcp.config.log_config import _SecureRotatingFileHandler
from patent_filewrapper_mcp.proxy.rate_limiter import RateLimiter


@pytest.fixture
def limiter():
    return RateLimiter(max_requests=5, time_window=10)


class TestBucketsArePerPolicy:
    """Downloads (5 per 10s) and registrations (10 per 60s) shared ONE deque
    keyed only by the IP, so each consumed the other's budget and NEITHER
    advertised limit was real (audit L-1)."""

    def test_spending_the_download_budget_leaves_the_registration_budget_intact(
        self, limiter
    ):
        ip = "10.1.2.3"
        for _ in range(5):
            assert limiter.is_allowed(ip) is True
        assert limiter.is_allowed(ip) is False, "download policy should be spent"

        # The registration policy is a different budget entirely.
        for attempt in range(10):
            assert limiter.is_allowed(ip, limit=10, window=60.0) is True, (
                f"registration attempt {attempt + 1} was refused because the "
                f"download policy had spent its bucket"
            )
        assert limiter.is_allowed(ip, limit=10, window=60.0) is False

    def test_different_ips_stay_independent(self, limiter):
        for _ in range(5):
            limiter.is_allowed("10.0.0.1")
        assert limiter.is_allowed("10.0.0.1") is False
        assert limiter.is_allowed("10.0.0.2") is True

    def test_remaining_requests_reports_the_policy_it_is_asked_about(self, limiter):
        ip = "10.1.2.4"
        for _ in range(3):
            limiter.is_allowed(ip)

        assert limiter.get_remaining_requests(ip) == 2
        assert limiter.get_remaining_requests(ip, limit=10, window=60.0) == 10, (
            "the registration policy's bucket is untouched"
        )

    def test_reset_time_reports_the_policy_it_is_asked_about(self, limiter):
        import time

        ip = "10.1.2.5"
        limiter.is_allowed(ip, limit=10, window=60.0)

        # The 60s window's reset is ~60s out; the untouched 10s policy is now.
        registration_reset = limiter.get_reset_time(ip, limit=10, window=60.0)
        download_reset = limiter.get_reset_time(ip)
        assert registration_reset - time.time() > 50
        assert download_reset - time.time() < 1


class TestRotatedLogPermissions:
    """The post-hoc chmod only ever touched the CURRENT log file; rotation
    created the next one with the process umask and renamed the old one, so
    every backup was world-readable while the live file was not (audit L-3)."""

    def _mode(self, path):
        return stat.S_IMODE(os.stat(path).st_mode)

    def test_the_active_file_is_0600(self, tmp_path):
        log_file = tmp_path / "app.log"
        handler = _SecureRotatingFileHandler(log_file, maxBytes=200, backupCount=3)
        try:
            handler.emit(
                logging.LogRecord("t", logging.INFO, __file__, 1, "x", None, None)
            )
            assert self._mode(log_file) == 0o600
        finally:
            handler.close()

    def test_every_rotated_backup_is_0600(self, tmp_path):
        log_file = tmp_path / "app.log"
        handler = _SecureRotatingFileHandler(log_file, maxBytes=200, backupCount=3)
        handler.setFormatter(logging.Formatter("%(message)s"))
        try:
            for i in range(40):
                handler.emit(
                    logging.LogRecord(
                        "t", logging.INFO, __file__, 1, "x" * 60 + str(i), None, None
                    )
                )
        finally:
            handler.close()

        backups = list(tmp_path.glob("app.log.*"))
        assert backups, "no rotation happened; raise the volume or lower maxBytes"
        for backup in backups:
            assert self._mode(backup) == 0o600, (
                f"rotated backup {backup.name} is {oct(self._mode(backup))}, "
                f"not 0600 — it holds the same client IPs and audit trail"
            )

    def test_a_chmod_failure_does_not_break_logging(self, tmp_path, monkeypatch):
        """Logging must never be taken down by a permission problem."""
        log_file = tmp_path / "app.log"
        handler = _SecureRotatingFileHandler(log_file, maxBytes=200, backupCount=1)
        try:
            monkeypatch.setattr(
                os, "chmod", lambda *a, **k: (_ for _ in ()).throw(OSError("nope"))
            )
            handler.emit(
                logging.LogRecord("t", logging.INFO, __file__, 1, "x", None, None)
            )
        finally:
            handler.close()

    def test_the_security_log_uses_the_same_handler(self):
        """security.log backups carry the client IPs and the audit trail."""
        import inspect

        from patent_filewrapper_mcp.util import security_logger

        source = inspect.getsource(security_logger)
        assert "_SecureRotatingFileHandler" in source
        assert "logging.handlers.RotatingFileHandler(" not in source
