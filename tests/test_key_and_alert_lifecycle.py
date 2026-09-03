"""Key provenance, secret rotation, and alert delivery
(audits M-9, M-10, M-17, L-22).
"""

import base64
import json

import pytest
from cryptography.fernet import Fernet

from patent_filewrapper_mcp.shared import fernet_key_store as fks
from patent_filewrapper_mcp.shared.internal_auth import InternalAuthToken

_SECRET = "rotation-test-secret-value-aaaaaaaa"
_PREVIOUS = "rotation-test-secret-value-bbbbbbbb"


class TestKeyProvenance:
    """`backend_available()` returns False in the containers this ships to, so
    the 0600-file fallback is the LIVE path there and encryption-at-rest
    degrades silently to a key beside the ciphertext (audit M-9)."""

    def test_a_key_supplied_by_env_is_used_and_recorded(self, monkeypatch):
        raw = Fernet.generate_key()
        monkeypatch.setenv(
            "PFW_TEST_ENV_KEY", base64.b64encode(raw).decode()
        )
        monkeypatch.setattr(
            "patent_filewrapper_mcp.shared_secure_storage.get_generic_secret",
            lambda name: None,
        )

        cipher = fks.get_or_create_fernet("TEST_ENV_KEY", ".test_env_key")

        assert cipher.decrypt(Fernet(raw).encrypt(b"x")) == b"x"
        assert fks.active_key_backends()["TEST_ENV_KEY"] == "env"

    def test_a_malformed_env_key_fails_loudly(self, monkeypatch):
        """Falling through would generate a fresh key and orphan every row
        encrypted with the real one."""
        monkeypatch.setenv("PFW_TEST_BAD_KEY", "not-base64-at-all!!")
        monkeypatch.setattr(
            "patent_filewrapper_mcp.shared_secure_storage.get_generic_secret",
            lambda name: None,
        )

        with pytest.raises(RuntimeError, match="not a valid"):
            fks.get_or_create_fernet("TEST_BAD_KEY", ".test_bad_key")

    def test_the_key_dir_can_be_moved_off_the_data_dir(self, monkeypatch, tmp_path):
        """One backup job otherwise carries the key AND the ciphertext."""
        target = tmp_path / "keys"
        monkeypatch.setenv("PFW_KEY_DIR", str(target))

        assert fks.key_dir() == target
        assert target.exists()

    def test_the_key_dir_defaults_to_the_data_dir(self, monkeypatch):
        monkeypatch.delenv("PFW_KEY_DIR", raising=False)
        assert fks.key_dir() == fks.get_data_dir()

    def test_active_backends_is_a_copy(self):
        """A caller must not be able to edit the record by mutating it."""
        snapshot = fks.active_key_backends()
        snapshot["INJECTED"] = "nonsense"
        assert "INJECTED" not in fks.active_key_backends()


class TestSecretRotation:
    """Rotating INTERNAL_AUTH_SECRET required all four MCPs to restart in the
    same instant or inter-MCP registration failed, so in practice it was never
    rotated (audit M-10)."""

    def test_a_token_signed_with_the_previous_secret_still_validates(
        self, monkeypatch
    ):
        old_issuer = InternalAuthToken(_PREVIOUS)
        token = old_issuer.create_token("fpd-mcp", metadata={"a": 1})

        monkeypatch.setenv("INTERNAL_AUTH_SECRET_PREVIOUS", _PREVIOUS)
        verifier = InternalAuthToken(_SECRET)

        valid, payload = verifier.validate_token(token)
        assert valid is True
        assert payload["service"] == "fpd-mcp"

    def test_without_the_previous_secret_the_old_token_is_rejected(
        self, monkeypatch
    ):
        token = InternalAuthToken(_PREVIOUS).create_token("fpd-mcp")

        monkeypatch.delenv("INTERNAL_AUTH_SECRET_PREVIOUS", raising=False)
        assert InternalAuthToken(_SECRET).validate_token(token)[0] is False

    def test_a_token_signed_with_the_current_secret_still_validates(
        self, monkeypatch
    ):
        monkeypatch.setenv("INTERNAL_AUTH_SECRET_PREVIOUS", _PREVIOUS)
        issuer = InternalAuthToken(_SECRET)
        assert issuer.validate_token(issuer.create_token("fpd-mcp"))[0] is True

    def test_a_token_signed_with_neither_is_rejected(self, monkeypatch):
        token = InternalAuthToken("some-third-secret-value").create_token("x")

        monkeypatch.setenv("INTERNAL_AUTH_SECRET_PREVIOUS", _PREVIOUS)
        assert InternalAuthToken(_SECRET).validate_token(token)[0] is False

    def test_tokens_are_always_signed_with_the_CURRENT_secret(self, monkeypatch):
        """The previous secret verifies; it must never sign."""
        monkeypatch.setenv("INTERNAL_AUTH_SECRET_PREVIOUS", _PREVIOUS)
        token = InternalAuthToken(_SECRET).create_token("fpd-mcp")

        monkeypatch.delenv("INTERNAL_AUTH_SECRET_PREVIOUS", raising=False)
        assert InternalAuthToken(_SECRET).validate_token(token)[0] is True
        assert InternalAuthToken(_PREVIOUS).validate_token(token)[0] is False

    def test_a_comma_separated_secret_is_current_then_previous(self):
        """INTERNAL_AUTH_SECRET="new,old" is the same overlap window as the
        separate _PREVIOUS var, expressed as one value."""
        token = InternalAuthToken(f"{_SECRET},{_PREVIOUS}").create_token("fpd-mcp")

        assert InternalAuthToken(_SECRET).validate_token(token)[0] is True
        assert InternalAuthToken(f"{_SECRET},{_PREVIOUS}").validate_token(token)[0] is True
        # A verifier that only knows the previous root, alone, rejects a
        # token signed under the current one.
        assert InternalAuthToken(_PREVIOUS).validate_token(token)[0] is False


class TestServiceTokenKeyDerivation:
    """HKDF-derived per-purpose signing key + key id, and the legacy
    raw-root-HMAC fallback for a sibling that has not rolled to it yet
    (secrets-audit S-06, PT-14)."""

    def test_hkdf_derivation_is_deterministic_and_root_specific(self):
        from patent_filewrapper_mcp.shared.internal_auth import (
            _derive_service_token_key,
        )

        key_a = _derive_service_token_key(_SECRET)
        key_a_again = _derive_service_token_key(_SECRET)
        key_b = _derive_service_token_key(_PREVIOUS)

        assert key_a == key_a_again
        assert key_a != key_b
        assert len(key_a) == 32

    def test_key_id_round_trips_on_a_minted_token(self):
        import base64
        import json

        from patent_filewrapper_mcp.shared.internal_auth import (
            _service_token_key_id,
        )

        token = InternalAuthToken(_SECRET).create_token("fpd-mcp")
        data = json.loads(base64.b64decode(token))

        assert data["key_id"] == _service_token_key_id(_SECRET)

    def test_a_token_verifies_under_a_previous_root_by_key_derivation(self):
        """New-style tokens (with key_id) verify against the HKDF-derived
        key for every candidate root, not just the current one."""
        token = InternalAuthToken(_PREVIOUS).create_token("fpd-mcp")

        verifier = InternalAuthToken(f"{_SECRET},{_PREVIOUS}")
        valid, payload = verifier.validate_token(token)

        assert valid is True
        assert payload["service"] == "fpd-mcp"

    def test_a_legacy_no_key_id_token_still_verifies(self):
        """A sibling still on the older vendored copy signs the raw root
        directly with no key_id. The verifier must accept it against every
        candidate root using the pre-HKDF scheme."""
        import base64
        import hashlib
        import hmac
        import json

        payload = {
            "service": "fpd-mcp",
            "client_ip": "127.0.0.1",
            "issued_at": 0,
            "expires_at": 2**31,
            "metadata": {},
        }
        payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
        signature = hmac.new(
            _PREVIOUS.encode("utf-8"), payload_bytes, hashlib.sha256
        ).hexdigest()
        legacy_token = base64.b64encode(
            json.dumps({"payload": payload, "signature": signature}).encode("utf-8")
        ).decode("utf-8")

        verifier = InternalAuthToken(f"{_SECRET},{_PREVIOUS}")
        assert verifier.validate_token(legacy_token)[0] is True

    def test_a_legacy_token_signed_with_an_unknown_root_is_rejected(self):
        import base64
        import hashlib
        import hmac
        import json

        payload = {
            "service": "fpd-mcp",
            "client_ip": "127.0.0.1",
            "issued_at": 0,
            "expires_at": 2**31,
            "metadata": {},
        }
        payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
        signature = hmac.new(
            b"some-unknown-root", payload_bytes, hashlib.sha256
        ).hexdigest()
        legacy_token = base64.b64encode(
            json.dumps({"payload": payload, "signature": signature}).encode("utf-8")
        ).decode("utf-8")

        verifier = InternalAuthToken(f"{_SECRET},{_PREVIOUS}")
        assert verifier.validate_token(legacy_token)[0] is False


@pytest.fixture
def alerting_logger(tmp_path, monkeypatch):
    from patent_filewrapper_mcp.util.security_logger import SecurityLogger

    monkeypatch.setenv("PFW_ALERT_LOG_PATH", str(tmp_path / "alerts.log"))
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    return SecurityLogger(enable_alerting=True)


class TestAlertDelivery:
    """Thresholds were tuned and fired correctly, but the only effect was
    another line in the same local file (audit M-17)."""

    def test_an_alert_reaches_the_separate_alert_log(self, alerting_logger, tmp_path):
        threshold = alerting_logger.alert_thresholds["auth_failure"]
        for _ in range(threshold):
            alerting_logger.log_auth_failure("/x", "10.0.0.1", "bad", "req")

        alert_log = tmp_path / "alerts.log"
        assert alert_log.exists(), "the alert never left the security log"
        entry = json.loads(alert_log.read_text().splitlines()[0])
        assert entry["event_type"] == "auth_failure"
        assert entry["alert_type"] == "threshold_exceeded"

    def test_the_alert_counter_is_observable(self, alerting_logger):
        assert alerting_logger.alerts_sent == 0
        threshold = alerting_logger.alert_thresholds["auth_failure"]
        for _ in range(threshold):
            alerting_logger.log_auth_failure("/x", "10.0.0.2", "bad", "req")
        assert alerting_logger.alerts_sent == 1

    def test_an_alert_fires_once_per_window_not_per_event(self, alerting_logger):
        """`>=` alerted again on every subsequent event, so one persistent
        scanner produced an alert per request (audit L-22)."""
        threshold = alerting_logger.alert_thresholds["auth_failure"]
        for _ in range(threshold + 20):
            alerting_logger.log_auth_failure("/x", "10.0.0.3", "bad", "req")

        assert alerting_logger.alerts_sent == 1, (
            f"{alerting_logger.alerts_sent} alerts for one scanner; an alert "
            f"storm is how a real signal gets ignored"
        )

    def test_a_sustained_attack_still_escalates_once_per_decade(
        self, alerting_logger
    ):
        threshold = alerting_logger.alert_thresholds["auth_failure"]
        for _ in range(threshold * 10):
            alerting_logger.log_auth_failure("/x", "10.0.0.4", "bad", "req")

        assert alerting_logger.alerts_sent == 2

    def test_a_broken_transport_does_not_raise(self, alerting_logger, monkeypatch):
        """An alert transport must never fail the request that produced it."""
        monkeypatch.setenv("PFW_ALERT_LOG_PATH", "/nonexistent/dir/alerts.log")
        alerting_logger._send_alert_notification({"event_type": "x", "count": 1})

    def test_no_transport_configured_is_silent_not_broken(
        self, tmp_path, monkeypatch
    ):
        from patent_filewrapper_mcp.util.security_logger import SecurityLogger

        monkeypatch.delenv("PFW_ALERT_LOG_PATH", raising=False)
        monkeypatch.delenv("PFW_ALERT_WEBHOOK_URL", raising=False)
        monkeypatch.setenv("LOG_DIR", str(tmp_path))
        logger = SecurityLogger(enable_alerting=True)

        logger._send_alert_notification({"event_type": "x", "count": 1})
        assert logger.alerts_sent == 1
