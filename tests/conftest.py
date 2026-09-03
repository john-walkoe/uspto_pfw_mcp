"""Pytest configuration for PFW MCP test suite."""

import os

import pytest

# Set BEFORE any test module is imported. pytest imports conftest.py ahead of
# collection, and `client_registry` builds a client at import time, so this has
# to be in place by then rather than in a fixture.
#
# This used to live at tests/test_download.py:12 and tests/test_fields_fix.py:22
# as an un-torn-down module-level mutation. Collection is alphabetical, so
# those files happened to import before test_injection_scan.py and leaked the
# variable into the process: the suite was green by collection order alone.
# Alone, test_injection_scan.py failed 3 tests; behind it, test_bounds_bug_fixes.py
# failed 6 more, because client_registry caches its init failure. `setdefault`
# so a real key in the environment still wins (audit T-3).
os.environ.setdefault("USPTO_API_KEY", "test_key_for_testing")

from patent_filewrapper_mcp.shared_secure_storage import UnifiedSecureStorage  # noqa: E402

#: Several of the oldest test files call the real USPTO ODP API. They used to
#: report success with `return True` / failure with `return False`, which
#: pytest reads as PASS either way, so they were green with no key at all.
#: Converting them to real assertions (audit T-4) means they need a real key.
#:
#: Gated on an EXPLICIT opt-in, not merely on a real key being present. The
#: presence of a key is not consent: the sibling FPD and PTAB repos each had
#: an import-time `load_dotenv()` that walked up to a shared parent directory's
#: .env and injected a live USPTO_API_KEY, and under a presence-based gate that
#: would silently switch the whole suite onto the live API - and, on the
#: extraction paths, onto a third-party OCR service. PFW has no load_dotenv
#: today (verified), and this gate means acquiring one later still cannot
#: reach either by itself.
#: Same shape as the repo's existing PFW_RUN_KEY_TESTS convention.
requires_live_uspto = pytest.mark.skipif(
    not os.environ.get("PFW_RUN_LIVE_TESTS")
    or os.environ.get("USPTO_API_KEY", "test_key_for_testing") == "test_key_for_testing",
    reason=(
        "Live USPTO API test. Set PFW_RUN_LIVE_TESTS=1 with a real "
        "USPTO_API_KEY to run these deliberately."
    ),
)


@pytest.fixture
def storage():
    """Provide a UnifiedSecureStorage instance for tests."""
    return UnifiedSecureStorage()


@pytest.fixture(autouse=True)
def _uspto_api_key(monkeypatch):
    """Guarantee a syntactically valid dummy USPTO key for every test.

    monkeypatch restores the prior value, so a test that deliberately unsets
    or changes the key cannot leak that into the next one — which is the class
    of bug this fixture exists to end.
    """
    monkeypatch.setenv(
        "USPTO_API_KEY", os.environ.get("USPTO_API_KEY", "test_key_for_testing")
    )
    yield


@pytest.fixture(autouse=True)
def _reset_client_registry():
    """Drop cached clients and the cached init failure between tests.

    `get_api_client()` caches its first failure for the life of the process,
    so one test running without a key disabled the client for every later
    test in the same process even after the key came back.
    """
    from patent_filewrapper_mcp import client_registry

    client_registry.reset_api_client()
    yield
    client_registry.reset_api_client()
