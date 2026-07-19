"""Linux OS-managed secret storage (audit M1) + Fernet key consolidation (F7/L14).

The systemd-creds roundtrip tests auto-skip on hosts without a working
user-scoped backend (e.g. Docker, macOS, CI containers).
"""

import sys

import pytest
from cryptography.fernet import Fernet

from patent_filewrapper_mcp.util import linux_secret_store as lss

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Linux-only backend")

_backend = lss.backend_available()


@pytest.mark.skipif(not _backend, reason="systemd-creds user scope unavailable")
class TestSystemdCredsBackend:
    def test_roundtrip(self):
        blob, encrypted = lss.encrypt_to_file_bytes(b"secret-value-123", "TEST_KEY")
        assert encrypted
        assert blob.startswith(lss.MAGIC)
        assert b"secret-value-123" not in blob  # actually encrypted
        plain, was_encrypted = lss.decrypt_from_file_bytes(blob, "TEST_KEY")
        assert was_encrypted
        assert plain == b"secret-value-123"

    def test_legacy_plaintext_passthrough(self):
        plain, was_encrypted = lss.decrypt_from_file_bytes(b"legacy-plain-key", "TEST_KEY")
        assert not was_encrypted
        assert plain == b"legacy-plain-key"

    def test_corrupted_blob_returns_none(self):
        plain, was_encrypted = lss.decrypt_from_file_bytes(
            lss.MAGIC + b"not-a-real-credential-blob", "TEST_KEY"
        )
        assert was_encrypted
        assert plain is None


@pytest.mark.skipif(not _backend, reason="systemd-creds user scope unavailable")
def test_storage_roundtrip_and_plaintext_migration(tmp_path, monkeypatch):
    """_store/_load_single_key encrypt on disk and migrate legacy plaintext."""
    from patent_filewrapper_mcp.shared_secure_storage import UnifiedSecureStorage

    storage = UnifiedSecureStorage()
    key_file = tmp_path / ".test_key"

    # Store: file on disk must be encrypted, not plaintext
    assert storage._store_single_key("live-api-key-value", key_file, "TEST_KEY")
    raw = key_file.read_bytes()
    assert raw.startswith(lss.MAGIC)
    assert b"live-api-key-value" not in raw
    assert storage._load_single_key(key_file, "TEST_KEY") == "live-api-key-value"

    # Legacy plaintext file migrates to encrypted on first read
    legacy_file = tmp_path / ".legacy_key"
    legacy_file.write_text("legacy-key-value")
    assert storage._load_single_key(legacy_file, "LEGACY_TEST_KEY") == "legacy-key-value"
    assert legacy_file.read_bytes().startswith(lss.MAGIC), "plaintext not migrated"
    assert storage._load_single_key(legacy_file, "LEGACY_TEST_KEY") == "legacy-key-value"


def test_fernet_key_store_data_dir(tmp_path, monkeypatch):
    """get_data_dir honors PFW_DATA_DIR and creates it 0700."""
    import stat

    from patent_filewrapper_mcp.shared import fernet_key_store as fks

    monkeypatch.setenv("PFW_DATA_DIR", str(tmp_path / "data"))
    d = fks.get_data_dir()
    assert d == tmp_path / "data"
    assert d.is_dir()
    assert stat.S_IMODE(d.stat().st_mode) == 0o700


def test_get_or_create_fernet_returns_working_cipher(tmp_path, monkeypatch):
    from pathlib import Path

    from patent_filewrapper_mcp.shared import fernet_key_store as fks

    monkeypatch.setenv("PFW_DATA_DIR", str(tmp_path / "data"))
    try:
        cipher = fks.get_or_create_fernet("PYTEST_FERNET_KEY", ".pytest_fernet_key")
        assert isinstance(cipher, Fernet)
        token = cipher.encrypt(b"payload")
        # Second call must yield the same key (decrypts the first cipher's token)
        cipher2 = fks.get_or_create_fernet("PYTEST_FERNET_KEY", ".pytest_fernet_key")
        assert cipher2.decrypt(token) == b"payload"
    finally:
        # get_or_create_fernet persists via the real generic-secret store —
        # remove the test artifact from the home dir
        artifact = Path.home() / ".uspto_generic_secret_PYTEST_FERNET_KEY"
        artifact.unlink(missing_ok=True)
