"""Dual-IdP OAuth authorization server for the PFW MCP (HTTP mode)."""
from .provider import (
    SCOPE_ADMIN,
    SCOPE_USER,
    PfwAuthProvider,
    build_auth_provider,
)
from .settings import AuthSettings
from .store import McpUserStore

__all__ = [
    "SCOPE_ADMIN",
    "SCOPE_USER",
    "AuthSettings",
    "McpUserStore",
    "PfwAuthProvider",
    "build_auth_provider",
]
