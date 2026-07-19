"""
Internal Authentication System for MCP Inter-Service Communication

Provides secure token-based authentication between MCPs instead of passing raw API keys.
"""

import hashlib
import hmac
import json
import os
import time
from typing import Dict, Optional, Tuple


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
                           INTERNAL_AUTH_SECRET env var.

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

        self.shared_secret = shared_secret.encode('utf-8')
        self.default_ttl_minutes = 5  # 5 minute token lifetime

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
            "client_ip": client_ip,
            "issued_at": current_time,
            "expires_at": expires_at,
            "metadata": metadata or {}
        }

        # Serialize payload
        payload_json = json.dumps(payload, sort_keys=True)
        payload_bytes = payload_json.encode('utf-8')

        # Create HMAC signature
        signature = hmac.new(
            self.shared_secret,
            payload_bytes,
            hashlib.sha256
        ).hexdigest()

        # Combine payload and signature
        token_data = {
            "payload": payload,
            "signature": signature
        }

        # Encode as base64 for transmission
        token_json = json.dumps(token_data)
        import base64
        return base64.b64encode(token_json.encode('utf-8')).decode('utf-8')

    def validate_token(self, token: str, expected_service: Optional[str] = None,
                      expected_client_ip: Optional[str] = None) -> Tuple[bool, Optional[Dict]]:
        """
        Validate token and return payload if valid.

        Args:
            token: Base64-encoded token string
            expected_service: Expected service name (optional)
            expected_client_ip: Expected client IP (optional)

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

            # Recreate signature to verify
            payload_json = json.dumps(payload, sort_keys=True)
            payload_bytes = payload_json.encode('utf-8')

            expected_signature = hmac.new(
                self.shared_secret,
                payload_bytes,
                hashlib.sha256
            ).hexdigest()

            # Constant-time comparison
            if not hmac.compare_digest(provided_signature, expected_signature):
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
    ) -> Tuple[bool, Optional[Dict]]:
        """
        Validate a token from another service.

        Args:
            token: Token to validate.
            expected_service: The service name that should have issued this token.
                              Must match the ``service`` field in the token payload.
                              If omitted, any service name is accepted (legacy compat).

        Returns:
            Tuple of (is_valid, token_payload)
        """
        return self._ensure_auth_token().validate_token(
            token,
            expected_service=expected_service,
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
