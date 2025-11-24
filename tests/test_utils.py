"""
Test utilities for USPTO Patent File Wrapper MCP tests.

Provides standardized test configuration and API key management.
"""
import os


def setup_test_api_key():
    """
    Set up test API key from environment or use fallback.

    Uses TEST_USPTO_API_KEY if available, otherwise falls back to a test value.
    This prevents hardcoded test keys in individual test files.
    """
    test_key = os.getenv("TEST_USPTO_API_KEY", "test_fallback_api_key_20chars")
    os.environ["USPTO_API_KEY"] = test_key
    return test_key


def setup_test_mistral_key():
    """
    Set up test Mistral API key from environment or use fallback.

    Uses TEST_MISTRAL_API_KEY if available, otherwise falls back to a test value.
    """
    test_key = os.getenv("TEST_MISTRAL_API_KEY", "test_fallback_mistral_key")
    os.environ["MISTRAL_API_KEY"] = test_key
    return test_key


def get_test_api_key():
    """Get test API key without setting environment variable."""
    return os.getenv("TEST_USPTO_API_KEY", "test_fallback_api_key_20chars")
