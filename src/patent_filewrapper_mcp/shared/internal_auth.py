"""
Internal Authentication System for MCP Inter-Service Communication

Provides secure token-based authentication between MCPs instead of passing raw API keys.
"""

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from typing import Dict, Optional, Tuple

from .safe_logger import get_safe_logger

logger = get_safe_logger(__name__)


class _ReplayGuard:
    """TTL-bounded set of already-consumed token identities.

    Inter-MCP tokens are bearer credentials with a 5-10 minute TTL, so an
    observed token is replayable for its whole lifetime (audit L-4). This
    records each identity the first time it is accepted and refuses it after.

    Entries are pruned against the token's own ``expires_at``, so the set can
    never outgrow the number of tokens issued inside one TTL window, and the
    proxy thread and the MCP thread share one instance behind a lock.
    """

    def __init__(self) -> None:
        self._consumed: Dict[str, int] = {}
        self._lock = threading.Lock()

    def consume(self, identity: str, expires_at: int) -> bool:
        """Return True on first sight of `identity`, False on a replay."""
        now = int(time.time())
        with self._lock:
            if self._consumed:
                self._consumed = {
                    key: exp for key, exp in self._consumed.items() if exp > now
                }
            if identity in self._consumed:
                return False
            self._consumed[identity] = expires_at
            return True


# Fixed HKDF info string for deriving the inter-MCP service-token signing
# key from the shared root. A per-purpose derived key (rather than the raw
# root) means a service token can never be replayed as, or mistaken for, the
# x-api-key transport credential or the mode=none admin credential — the same
# root grants three different things, and only this one derives from it.
_SERVICE_TOKEN_HKDF_INFO = b"uspto-mcp-service-token-v1"


def _hkdf_sha256(ikm: bytes, info: bytes, length: int = 32) -> bytes:
    """RFC 5869 HKDF-SHA256 with the default (all-zero) salt.

    Stdlib-only (hashlib + hmac) rather than a `cryptography` dependency,
    matching this module's existing footprint.
    """
    zero_salt = b"\x00" * hashlib.sha256().digest_size
    prk = hmac.new(zero_salt, ikm, hashlib.sha256).digest()
    okm = b""
    block = b""
    counter = 1
    while len(okm) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        okm += block
        counter += 1
    return okm[:length]


def _derive_service_token_key(root: str) -> bytes:
    """The HKDF-derived signing key for one candidate root."""
    return _hkdf_sha256(root.encode("utf-8"), _SERVICE_TOKEN_HKDF_INFO)


def _service_token_key_id(root: str) -> str:
    """Short, non-secret identifier for a root, carried in the token so a
    verifier holding several roots (current + previous) can tell which one a
    token claims without trying every derived key blind. Never used as a
    security check by itself — the signature is."""
    return hashlib.sha256(root.encode("utf-8") + b"|key-id").hexdigest()[:8]


def ensure_internal_auth_secret() -> str:
    """
    Fail fast if INTERNAL_AUTH_SECRET is not set.

    Ephemeral secrets generated at runtime would allow any caller to forge
    inter-MCP tokens. This guard ensures the env var is provisioned before
    the server accepts requests.

    Returns:
        The validated secret string.

    Raises:
        RuntimeError: if the environment variable is missing or empty.
    """
    secret = os.getenv("INTERNAL_AUTH_SECRET", "").strip()
    if not secret:
        raise RuntimeError(
            "INTERNAL_AUTH_SECRET environment variable is not set. "
            "Inter-MCP authentication is disabled without a shared secret. "
            "Generate one with:  python -c \"import secrets; print(secrets.token_hex(32))\" "
            "and set it in your environment before starting the server."
        )
    return secret


class InternalAuthToken:
    """Generate and validate time-limited tokens for internal MCP communication."""

    def __init__(self, shared_secret: Optional[str] = None):
        """
        Initialize with shared secret for HMAC operations.

        Args:
            shared_secret: Shared secret for HMAC. If None, reads from
                           INTERNAL_AUTH_SECRET env var. May itself be a
                           comma-separated rotation list (current first).

        Raises:
            RuntimeError: if no secret is provided and INTERNAL_AUTH_SECRET is not set.
        """
        if shared_secret is None:
            shared_secret = os.getenv("INTERNAL_AUTH_SECRET")
            if not shared_secret:
                raise RuntimeError(
                    "INTERNAL_AUTH_SECRET environment variable is not set. "
                    " Ephemeral secrets must not be used in production — "
                    "set INTERNAL_AUTH_SECRET to a stable shared value "
                    "before starting the server."
                )

        from ..shared_secure_storage import split_secret_candidates

        roots = split_secret_candidates(shared_secret)
        # Accepted for VERIFICATION only; tokens are always SIGNED with the
        # CURRENT (first) root. Without an overlap window, rotating
        # INTERNAL_AUTH_SECRET required all four MCPs to restart in the same
        # instant or inter-MCP registration failed, so in practice it was
        # never rotated at all (audit M-10, secrets-audit S-06, PT-14). With
        # it, rotation is: set INTERNAL_AUTH_SECRET to "new,old", roll each
        # server, then drop the old value. INTERNAL_AUTH_SECRET_PREVIOUS is
        # still honored (appended, deduplicated) for anyone already using
        # the pre-rotation-list env var.
        previous = os.getenv("INTERNAL_AUTH_SECRET_PREVIOUS", "").strip()
        for candidate in split_secret_candidates(previous):
            if candidate not in roots:
                roots.append(candidate)
        if not roots and shared_secret:
            # Preserves prior behavior for a caller-supplied empty/odd value
            # (split_secret_candidates drops empty entries).
            roots = [shared_secret]

        self._roots = roots
        self.default_ttl_minutes = 5  # 5 minute token lifetime
        self._replay_guard = _ReplayGuard()

    def create_token(self, service_name: str, client_ip: str = "127.0.0.1",
                    ttl_minutes: Optional[int] = None, metadata: Optional[Dict] = None) -> str:
        """
        Create time-limited authorization token.

        Args:
            service_name: Name of the requesting service
            client_ip: Client IP address for binding
            ttl_minutes: Token lifetime in minutes
            metadata: Additional metadata to include in token

        Returns:
            Base64-encoded token string
        """
        if ttl_minutes is None:
            ttl_minutes = self.default_ttl_minutes

        # Create token payload
        current_time = int(time.time())
        expires_at = current_time + (ttl_minutes * 60)

        payload = {
            "service": service_name,
            # Signed but NOT an enforced binding: every issuer in the fleet
            # hardcodes "127.0.0.1", and no validator passes
            # expected_client_ip. Kept in the payload because changing the
            # signed shape would break every sibling's tokens at once; do not
            # mistake its presence for an IP restriction (audit M-10).
            "client_ip": client_ip,
            "issued_at": current_time,
            "expires_at": expires_at,
            # Unique per token so a validator can enforce single use. Without
            # it an observed token replays for its whole TTL (audit L-4).
            "jti": secrets.token_hex(16),
            "metadata": metadata or {}
        }

        # Serialize payload
        payload_json = json.dumps(payload, sort_keys=True)
        payload_bytes = payload_json.encode('utf-8')

        # Sign with the HKDF-derived per-purpose key for the CURRENT root
        # (self._roots[0]), never the previous one — rotation is a verify-only
        # overlap window, not a second signer.
        current_root = self._roots[0]
        signature = hmac.new(
            _derive_service_token_key(current_root),
            payload_bytes,
            hashlib.sha256
        ).hexdigest()

        # Combine payload, signature and the key id a verifier holding
        # several roots can use to identify which one this claims (not a
        # security check by itself).
        token_data = {
            "payload": payload,
            "signature": signature,
            "key_id": _service_token_key_id(current_root),
        }

        # Encode as base64 for transmission
        token_json = json.dumps(token_data)
        import base64
        return base64.b64encode(token_json.encode('utf-8')).decode('utf-8')

    def _signature_matches_any_root(
        self, provided_signature: str, payload_bytes: bytes, key_id: Optional[str]
    ) -> bool:
        """True when `provided_signature` validates under any candidate root.

        Every candidate root is ALWAYS compared, never short-circuited on the
        first match, so the timing does not reveal how many roots are
        configured or which one (if any) validated.

        `key_id is not None` selects the scheme: present means a new-style
        token, verified against the HKDF-derived per-purpose key for each
        root; absent means a legacy token from a sibling that has not rolled
        to the HKDF-derived scheme yet, verified the way this module always
        has — raw-root HMAC — across every candidate root.
        """
        matched = False
        if key_id is not None:
            for root in self._roots:
                derived_signature = hmac.new(
                    _derive_service_token_key(root), payload_bytes, hashlib.sha256
                ).hexdigest()
                if hmac.compare_digest(provided_signature, derived_signature):
                    matched = True
        else:
            for root in self._roots:
                legacy_signature = hmac.new(
                    root.encode("utf-8"), payload_bytes, hashlib.sha256
                ).hexdigest()
                if hmac.compare_digest(provided_signature, legacy_signature):
                    matched = True
            if matched:
                logger.info(
                    "Accepted a legacy (no key_id) internal auth token; "
                    "the issuing service has not been rolled yet"
                )
        return matched

    def validate_token(self, token: str, expected_service: Optional[str] = None,
                      expected_client_ip: Optional[str] = None,
                      single_use: bool = False) -> Tuple[bool, Optional[Dict]]:
        """
        Validate token and return payload if valid.

        Args:
            token: Base64-encoded token string
            expected_service: Expected service name (optional)
            expected_client_ip: Expected client IP (optional)
            single_use: Consume the token, so a second presentation of the same
                token fails even inside its TTL. Identity is the payload's
                ``jti`` when present; otherwise the HMAC signature, which is
                unique per payload and is carried by every token including the
                ones the siblings mint from their older vendored copy of this
                module. Verified LAST, so a replay is only recorded once the
                token has otherwise passed.

        Returns:
            Tuple of (is_valid, payload_dict)
        """
        try:
            # Decode base64
            import base64
            token_json = base64.b64decode(token.encode('utf-8')).decode('utf-8')
            token_data = json.loads(token_json)

            payload = token_data.get("payload", {})
            provided_signature = token_data.get("signature", "")
            key_id = token_data.get("key_id")

            # Recreate signature to verify
            payload_json = json.dumps(payload, sort_keys=True)
            payload_bytes = payload_json.encode('utf-8')

            if not self._signature_matches_any_root(
                provided_signature, payload_bytes, key_id
            ):
                return False, None

            # Check expiration
            current_time = int(time.time())
            expires_at = payload.get("expires_at", 0)

            if current_time > expires_at:
                return False, None  # Token expired

            # Check service name if provided
            if expected_service and payload.get("service") != expected_service:
                return False, None

            # Check client IP if provided
            if expected_client_ip and payload.get("client_ip") != expected_client_ip:
                return False, None

            if single_use:
                identity = payload.get("jti") or provided_signature
                if not self._replay_guard.consume(identity, expires_at):
                    return False, None

            return True, payload

        except Exception:
            return False, None

    def get_token_info(self, token: str) -> Optional[Dict]:
        """
        Get token information without validating signature (for debugging).

        Args:
            token: Base64-encoded token string

        Returns:
            Token payload dict or None if invalid format
        """
        try:
            import base64
            token_json = base64.b64decode(token.encode('utf-8')).decode('utf-8')
            token_data = json.loads(token_json)
            return token_data.get("payload", {})
        except Exception:
            return None


class MCPAuthManager:
    """High-level authentication manager for MCP services."""

    def __init__(self, service_name: str = "pfw-mcp"):
        self.service_name = service_name
        # NOTE: auth_token is lazily initialized — only created when
        # validate_incoming_token or validate_outgoing_token is first called.
        # This avoids failing server startup when INTERNAL_AUTH_SECRET is absent
        # and inter-MCP auth is not needed.
        self._auth_token: Optional[InternalAuthToken] = None

    def _ensure_auth_token(self) -> InternalAuthToken:
        """
        Lazily create InternalAuthToken on first use.

        Returns:
            Initialized InternalAuthToken instance.

        Raises:
            RuntimeError: if INTERNAL_AUTH_SECRET is not set when auth is actually needed.
        """
        if self._auth_token is None:
            self._auth_token = InternalAuthToken()
        return self._auth_token

    def validate_incoming_token(
        self,
        token: str,
        expected_service: Optional[str] = None,
        single_use: bool = False,
    ) -> Tuple[bool, Optional[Dict]]:
        """
        Validate a token from another service.

        Args:
            token: Token to validate.
            expected_service: The service name that should have issued this token.
                              Must match the ``service`` field in the token payload.
                              If omitted, any service name is accepted (legacy compat).
            single_use: Reject a second presentation of the same token inside
                        its TTL. Registration endpoints pass True — one minted
                        token authorizes exactly one registration.

        Returns:
            Tuple of (is_valid, token_payload)
        """
        return self._ensure_auth_token().validate_token(
            token,
            expected_service=expected_service,
            single_use=single_use,
        )


# Lazy getter for the global pfw_auth singleton — avoids import-order crashes
# and prevents fail-fast at module-import time on non-Windows.
_pfw_auth_instance: Optional["MCPAuthManager"] = None


def get_pfw_auth() -> MCPAuthManager:
    """Get the global MCPAuthManager singleton, creating it on first call."""
    global _pfw_auth_instance
    if _pfw_auth_instance is None:
        _pfw_auth_instance = MCPAuthManager("pfw-mcp")
    return _pfw_auth_instance
