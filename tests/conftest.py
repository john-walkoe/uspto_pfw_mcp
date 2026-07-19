"""Pytest configuration for PFW MCP test suite."""

import pytest

from patent_filewrapper_mcp.shared_secure_storage import UnifiedSecureStorage


@pytest.fixture
def storage():
    """Provide a UnifiedSecureStorage instance for tests."""
    return UnifiedSecureStorage()
