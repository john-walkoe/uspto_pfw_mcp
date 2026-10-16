"""Authentication failures on /mcp, in the security log.

In oauth mode FastMCP's bearer middleware answers a request it
cannot authenticate with 401 and logs nothing the security log sees, so the
per-IP threshold alert in ``util/security_logger.py`` only ever counted the
download proxy. ``AuthFailureLogMiddleware`` wraps the MCP app, watches the
response status, and for every 401 (and 403, insufficient scope) writes one
``auth_failure`` event: the path, the client address resolved the way the
rest of the server resolves it (``util/client_ip.py``), and a reason code.

The reason is read from the presented credential WITHOUT trusting it: the
JWT's payload is base64-decoded only to tell an expired token from one
minted for another audience or issuer. The verifier already refused it;
this only names why for the log. Nothing of the token is ever logged, not
even a prefix or a hash, and the request body is never read.

Reason codes: ``missing_token`` (no Authorization header), ``not_bearer``
(another scheme), ``malformed_token`` (not a JWT, or one that does not
decode), ``expired``, ``wrong_audience``, ``wrong_issuer``,
``bad_signature`` (a well-formed, unexpired JWT for this audience and
issuer that still failed: signature or unknown key),
``invalid_token`` (an opaque bearer that matched nothing, e.g. a wrong
internal bearer), ``insufficient_scope`` (a 403, or a JWT whose ``scope``
claim lacks the required scope).
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: A token longer than this is not decoded at all.
_MAX_TOKEN_CHARS = 16 * 1024


def _b64url_json(segment: str) -> Optional[dict]:
    try:
        raw = base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
        value = json.loads(raw)
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def classify_auth_failure(authorization: Optional[str], status: int, *,
                          audience: Optional[str] = None, issuer: Optional[str] = None,
                          required_scope: Optional[str] = None, now: Optional[float] = None) -> str:
    """The reason code for a refused /mcp request (see the module docstring)."""
    if status == 403:
        return "insufficient_scope"
    scheme, _, token = (authorization or "").strip().partition(" ")
    if not scheme:
        return "missing_token"
    if scheme.lower() != "bearer":
        return "not_bearer"
    token = token.strip()
    if not token:
        return "missing_token"
    parts = token.split(".")
    if len(parts) != 3:
        return "invalid_token"
    header = _b64url_json(parts[0]) if len(token) <= _MAX_TOKEN_CHARS else None
    claims = _b64url_json(parts[1]) if header is not None else None
    if claims is None:
        return "malformed_token"
    return _claims_reason(claims, audience=audience, issuer=issuer, required_scope=required_scope,
                          now=time.time() if now is None else now)


def _claims_reason(claims: dict, *, audience: Optional[str], issuer: Optional[str],
                   required_scope: Optional[str], now: float) -> str:
    """Why a well-formed JWT with these (unverified) claims was refused."""
    exp = claims.get("exp")
    if isinstance(exp, (int, float)) and not isinstance(exp, bool) and exp <= now:
        return "expired"
    aud = claims.get("aud")
    auds = {a.rstrip("/") for a in (aud if isinstance(aud, list) else [aud]) if isinstance(a, str)}
    if audience and audience.rstrip("/") not in auds:
        return "wrong_audience"
    iss = claims.get("iss")
    if issuer and (not isinstance(iss, str) or iss.rstrip("/") != issuer.rstrip("/")):
        return "wrong_issuer"
    scope = claims.get("scope")
    if required_scope and (not isinstance(scope, str) or required_scope not in scope.split()):
        return "insufficient_scope"
    return "bad_signature"


class AuthFailureLogMiddleware:
    """ASGI wrapper for the MCP app: one security-log ``auth_failure`` event
    per 401/403 it returns on a path under ``/mcp``. ``audience``, ``issuer``
    and ``required_scope`` (for a deployment that validates tokens from an
    external issuer: the resource URL, the issuer URL and the user scope)
    sharpen the reason; without them a well-formed unexpired
    JWT reads as ``bad_signature``."""

    def __init__(self, app: Any, *, audience: Optional[str] = None,
                 issuer: Optional[str] = None, required_scope: Optional[str] = None) -> None:
        self.app = app
        self.audience = audience
        self.issuer = issuer
        self.required_scope = required_scope

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        path = scope.get("path", "") if scope.get("type") == "http" else ""
        if not (path == "/mcp" or path.startswith("/mcp/")):
            await self.app(scope, receive, send)
            return
        logged = False

        async def send_wrapper(message: dict) -> None:
            nonlocal logged
            if (not logged and message.get("type") == "http.response.start"
                    and message.get("status") in (401, 403)):
                logged = True
                self._log(scope, int(message["status"]))
            await send(message)

        await self.app(scope, receive, send_wrapper)

    def _log(self, scope: dict, status: int) -> None:
        try:
            from .client_ip import resolve_client_ip_from_scope
            from .security_logger import security_logger

            authorization = None
            for name, value in scope.get("headers") or []:
                if name.lower() == b"authorization":
                    authorization = value.decode("latin-1")
                    break
            reason = classify_auth_failure(authorization, status, audience=self.audience,
                                           issuer=self.issuer, required_scope=self.required_scope)
            security_logger.log_auth_failure(
                endpoint=scope.get("path", ""),
                client_ip=resolve_client_ip_from_scope(scope),
                reason=reason,
            )
        except Exception as exc:  # noqa: BLE001 - logging must never break the response
            logger.warning("auth-failure security logging failed: %s", type(exc).__name__)
