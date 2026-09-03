"""Single owner of Fernet encryption-key management (audits F7, M1, L14).

Replaces three drifting copies of the same get-or-create logic in
proxy/secure_link_cache.py, proxy/ptab_document_store.py and
proxy/fpd_document_store.py.

Key storage chain:
1. shared_secure_storage generic secrets — DPAPI on Windows, systemd-creds
   (user+machine bound) on Linux.
2. Key file in the hardened data dir (0700 dir, 0600 file) as last resort.

Legacy plaintext key files at the project root (.proxy_encryption_key,
.ptab_docstore_key, .fpd_docstore_key) are migrated into the secure store on
first use and then removed — a verified read-back happens before deletion.

The data dir also hosts the proxy SQLite artifacts (audit L14): use
get_data_dir() instead of the project root for new files;
migrate_data_file() relocates existing project-root files.
"""

import base64
import os
import shutil
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet

from .safe_logger import get_safe_logger

logger = get_safe_logger(__name__)

# Project root: src/patent_filewrapper_mcp/shared/ -> repo root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def get_data_dir() -> Path:
    """Hardened data directory for keys and SQLite artifacts (audit L14).

    Default ~/.uspto_pfw_mcp/data, override with PFW_DATA_DIR. Created 0700.
    """
    env_dir = os.environ.get("PFW_DATA_DIR", "").strip()
    data_dir = Path(env_dir) if env_dir else Path.home() / ".uspto_pfw_mcp" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    if hasattr(os, "chmod"):
        try:
            os.chmod(data_dir, 0o700)
        except (OSError, PermissionError):
            pass
    return data_dir


def migrate_data_file(filename: str) -> Path:
    """Return the data-dir path for `filename`, relocating a legacy
    project-root copy if one exists and the data-dir copy does not."""
    target = get_data_dir() / filename
    legacy = _PROJECT_ROOT / filename
    if legacy.exists() and not target.exists():
        try:
            shutil.move(str(legacy), str(target))
            if hasattr(os, "chmod"):
                os.chmod(target, 0o600)
            logger.info(f"Migrated {filename} from project root to data dir")
        except Exception as e:
            logger.warning(f"Could not migrate {filename} to data dir: {e}")
            return legacy
    return target


def _read_key_file(path: Path) -> Optional[bytes]:
    try:
        if path.exists():
            return path.read_bytes().strip()
    except Exception as e:
        logger.warning(f"Error reading key file {path.name}: {e}")
    return None


#: Which backend actually served each key this process. `backend_available()`
#: returns False in the containers this ships to, so the fallback is the live
#: path there and an operator has no way to know without this (audit M-9).
_ACTIVE_BACKENDS: dict = {}


def active_key_backends() -> dict:
    """secret_name -> backend that served it ("secure_store" | "env" | "file").

    Surfaced on the health payload so "encryption at rest" can be verified
    rather than assumed: it degrades silently to a key file beside the
    ciphertext, which is a control-effectiveness gap, not a control absence.
    """
    return dict(_ACTIVE_BACKENDS)


def key_dir():
    """Where a last-resort key file lives.

    PFW_KEY_DIR exists so the key does NOT have to sit in the same directory
    as the ciphertext it protects (audit M-9, database F-1): one volume copy
    or one backup job otherwise carries both halves. Defaults to the data dir
    for backward compatibility with deployments that already have a key there.
    """
    override = os.getenv("PFW_KEY_DIR", "").strip()
    if not override:
        return get_data_dir()
    path = Path(override)
    path.mkdir(parents=True, exist_ok=True)
    if hasattr(os, "chmod"):
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass
    return path


def _env_key_name(secret_name: str) -> str:
    return f"PFW_{secret_name}"


def _fernet_from_env(secret_name: str) -> Optional[Fernet]:
    """The key from PFW_<SECRET_NAME>, or None when it is not set.

    Raises:
        RuntimeError: when the variable IS set but does not decode. Failing
            loudly matters here: falling through would generate a fresh key
            and orphan every row encrypted with the real one.
    """
    env_value = os.getenv(_env_key_name(secret_name), "").strip()
    if not env_value:
        return None
    try:
        cipher = Fernet(base64.b64decode(env_value.encode("utf-8")))
    except Exception as e:
        raise RuntimeError(
            f"{_env_key_name(secret_name)} is set but is not a valid "
            f"base64-encoded Fernet key ({type(e).__name__}). Refusing to "
            "continue, because generating a replacement would orphan every "
            "row encrypted with the real one."
        ) from e
    _ACTIVE_BACKENDS[secret_name] = "env"
    logger.info(f"{secret_name} loaded from {_env_key_name(secret_name)}")
    return cipher


def _fernet_from_legacy_files(secret_name: str, legacy_file_name: str) -> Optional[Fernet]:
    """The key from a plaintext key file, importing it into the secure store.

    Searched in historical order: project root (oldest), the key dir, then the
    data dir. The plaintext file is removed only after a VERIFIED read-back
    from the secure store.
    """
    from ..shared_secure_storage import get_generic_secret, store_generic_secret

    for key_path in (
        _PROJECT_ROOT / legacy_file_name,
        key_dir() / legacy_file_name,
        get_data_dir() / legacy_file_name,
    ):
        key = _read_key_file(key_path)
        if not key:
            continue
        try:
            key_b64 = base64.b64encode(key).decode("utf-8")
            if store_generic_secret(key_b64, secret_name) and get_generic_secret(secret_name) == key_b64:
                key_path.unlink()
                logger.info(
                    f"Imported {key_path.name} into secure storage as {secret_name} "
                    "and removed the plaintext file"
                )
        except Exception as e:
            logger.warning(f"Could not import {key_path.name} into secure storage: {e}")
        _ACTIVE_BACKENDS[secret_name] = "file"
        return Fernet(key)

    return None


def get_or_create_fernet(secret_name: str, legacy_file_name: str) -> Fernet:
    """Get (or create) the Fernet cipher identified by `secret_name`.

    Args:
        secret_name: generic-secret identifier, e.g. "PROXY_ENCRYPTION_KEY"
        legacy_file_name: historical project-root key file, e.g.
            ".proxy_encryption_key" — imported and removed if present
    """
    from ..shared_secure_storage import get_generic_secret, store_generic_secret

    # 1. Secure store (DPAPI / systemd-creds)
    try:
        stored = get_generic_secret(secret_name)
        if stored:
            _ACTIVE_BACKENDS[secret_name] = "secure_store"
            return Fernet(base64.b64decode(stored.encode("utf-8")))
    except Exception as e:
        logger.warning(f"Secure storage read failed for {secret_name}: {e}")

    # 2. Environment, i.e. a Docker/compose secret. Before the file fallback
    #    so a container has a way to supply the key that does NOT put it in
    #    the volume holding the ciphertext (audit M-9).
    from_env = _fernet_from_env(secret_name)
    if from_env is not None:
        return from_env

    from_file = _fernet_from_legacy_files(secret_name, legacy_file_name)
    if from_file is not None:
        return from_file

    # 4. Generate new key
    key = Fernet.generate_key()
    key_b64 = base64.b64encode(key).decode("utf-8")
    try:
        if store_generic_secret(key_b64, secret_name):
            logger.info(f"Generated and stored new Fernet key as {secret_name}")
            _ACTIVE_BACKENDS[secret_name] = "secure_store"
            return Fernet(key)
    except Exception as e:
        logger.warning(f"Secure storage write failed for {secret_name}: {e}")

    # 5. Last resort: key file in the hardened key dir (the data dir unless
    #    PFW_KEY_DIR moves it off the volume holding the ciphertext)
    fallback = key_dir() / legacy_file_name
    try:
        fallback.write_bytes(key)
        if hasattr(os, "chmod"):
            os.chmod(fallback, 0o600)
        _ACTIVE_BACKENDS[secret_name] = "file"
        logger.warning(
            f"Secure storage unavailable — {secret_name} stored as a 0600 file "
            f"in {fallback.parent}. Set PFW_KEY_DIR to keep the key off the "
            f"volume that holds the data it encrypts, or supply "
            f"{_env_key_name(secret_name)} from a container secret."
        )
    except Exception as e:
        logger.error(f"Could not persist fallback key file for {secret_name}: {e}")
    return Fernet(key)
