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
            return Fernet(base64.b64decode(stored.encode("utf-8")))
    except Exception as e:
        logger.warning(f"Secure storage read failed for {secret_name}: {e}")

    # 2. Legacy / fallback key files: project root first (historical
    #    location), then the data dir (current fallback location)
    for key_path in (_PROJECT_ROOT / legacy_file_name, get_data_dir() / legacy_file_name):
        key = _read_key_file(key_path)
        if not key:
            continue
        # Import into the secure store; delete the plaintext file only after
        # a verified read-back
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
        return Fernet(key)

    # 3. Generate new key
    key = Fernet.generate_key()
    key_b64 = base64.b64encode(key).decode("utf-8")
    try:
        if store_generic_secret(key_b64, secret_name):
            logger.info(f"Generated and stored new Fernet key as {secret_name}")
            return Fernet(key)
    except Exception as e:
        logger.warning(f"Secure storage write failed for {secret_name}: {e}")

    # 4. Last resort: key file in the hardened data dir
    fallback = get_data_dir() / legacy_file_name
    try:
        fallback.write_bytes(key)
        if hasattr(os, "chmod"):
            os.chmod(fallback, 0o600)
        logger.warning(
            f"Secure storage unavailable — {secret_name} stored as 0600 file "
            f"in data dir ({fallback.name})"
        )
    except Exception as e:
        logger.error(f"Could not persist fallback key file for {secret_name}: {e}")
    return Fernet(key)
