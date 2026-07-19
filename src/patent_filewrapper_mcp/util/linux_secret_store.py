"""OS-managed secret encryption for Linux — the DPAPI analog (audit M1).

Backend: `systemd-creds encrypt --user` (systemd >= 256). Secrets are
encrypted with a key derived from the invoking user's credential host key,
so the resulting blob is user + machine bound — the same guarantee DPAPI
gives on Windows. When the host has the tss2 libraries installed the key is
additionally sealed to the TPM2 chip (`systemd-creds has-tpm2`).

Where it fits: `shared_secure_storage._store_single_key` /
`_load_single_key` call these functions on non-Windows platforms. Files on
disk carry a magic prefix so encrypted blobs and legacy plaintext files are
distinguishable; legacy plaintext is migrated to encrypted form on first
read (see shared_secure_storage).

Unavailable backend (no systemd — e.g. Docker, macOS) degrades to the
previous behavior: plaintext file at 0600, with a warning at store time.
"""

import shutil
import subprocess
from typing import Optional, Tuple

from ..shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)

# File-format magic for systemd-creds encrypted secrets
MAGIC = b"SDCREDS1\n"

_CREDS_TIMEOUT = 15  # seconds; systemd-creds is local and fast

# Probe result cache: None = not probed yet
_backend_ok: Optional[bool] = None


def _run_creds(args: list, input_bytes: bytes) -> bytes:
    result = subprocess.run(
        ["systemd-creds", *args, "-", "-"],
        input=input_bytes,
        capture_output=True,
        timeout=_CREDS_TIMEOUT,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"systemd-creds {args[0]} failed (rc={result.returncode}): "
            f"{result.stderr.decode('utf-8', 'replace')[:200]}"
        )
    return result.stdout


def backend_available() -> bool:
    """True when user-scoped systemd-creds encryption works on this host.

    Probed once per process with a real encrypt/decrypt roundtrip (binary
    presence alone is not enough — user scope needs systemd >= 256 and a
    working per-user credential key).
    """
    global _backend_ok
    if _backend_ok is not None:
        return _backend_ok
    try:
        if shutil.which("systemd-creds") is None:
            _backend_ok = False
            return False
        blob = _run_creds(["encrypt", "--user", "--name=pfw_probe"], b"probe")
        plain = _run_creds(["decrypt", "--user", "--name=pfw_probe"], blob)
        _backend_ok = plain == b"probe"
    except Exception as e:
        logger.info(f"systemd-creds backend unavailable: {type(e).__name__}")
        _backend_ok = False
    if _backend_ok:
        logger.debug("systemd-creds user-scoped secret encryption available")
    return _backend_ok


def _credential_name(name: str) -> str:
    # systemd credential names: lowercase, no spaces; keep it deterministic
    return "pfw_" + "".join(c if c.isalnum() else "_" for c in name.lower())


def encrypt_to_file_bytes(plaintext: bytes, name: str) -> Tuple[bytes, bool]:
    """Encrypt `plaintext` for at-rest storage.

    Returns (file_bytes, encrypted). When the backend is unavailable the
    plaintext is returned unchanged with encrypted=False — caller keeps the
    0600-file fallback behavior and logs the downgrade.
    """
    if not backend_available():
        return plaintext, False
    try:
        blob = _run_creds(
            ["encrypt", "--user", f"--name={_credential_name(name)}"], plaintext
        )
        return MAGIC + blob, True
    except Exception as e:
        logger.warning(
            f"systemd-creds encrypt failed for {name} ({type(e).__name__}); "
            "falling back to plaintext 0600 file"
        )
        return plaintext, False


def decrypt_from_file_bytes(file_bytes: bytes, name: str) -> Tuple[Optional[bytes], bool]:
    """Decrypt file content written by encrypt_to_file_bytes.

    Returns (plaintext, was_encrypted). Content without the magic prefix is
    treated as legacy plaintext and returned as-is with was_encrypted=False.
    Returns (None, True) when an encrypted blob cannot be decrypted (wrong
    user/machine, corrupted file).
    """
    if not file_bytes.startswith(MAGIC):
        return file_bytes, False
    try:
        plain = _run_creds(
            ["decrypt", "--user", f"--name={_credential_name(name)}"],
            file_bytes[len(MAGIC):],
        )
        return plain, True
    except Exception as e:
        logger.error(f"systemd-creds decrypt failed for {name}: {type(e).__name__}")
        return None, True
