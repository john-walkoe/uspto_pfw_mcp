#!/usr/bin/env python3
"""Placeholder MISTRAL_API_KEY values must reach the client as "no key".

A user who copy-pastes the documented config should get the "no OCR
configured" guidance, not an authentication failure from Mistral.

Rewritten from a 93-line script whose only failure signal was `return False`,
which pytest reports as PASS (audit T-4). The env save/restore it hand-rolled
in two `finally` blocks is now monkeypatch's job.
"""

import pytest

from patent_filewrapper_mcp.api.enhanced_client import EnhancedPatentClient

_PLACEHOLDERS = [
    ("your_mistral_api_key_here", "exact documentation placeholder"),
    ("your_mistral_api_key_here_OPTIONAL", "documented placeholder with suffix"),
    ("YOUR_MISTRAL_API_KEY_HERE", "uppercase"),
    ("your_key_here", "generic key placeholder"),
    ("your_api_key_here", "generic api key placeholder"),
    ("placeholder", "literal"),
    ("PLACEHOLDER", "uppercase literal"),
    ("optional", "optional keyword"),
    ("OPTIONAL", "uppercase optional"),
    ("change_me", "change me"),
    ("replace_me", "replace me"),
    ("insert_key_here", "insert key here"),
    ("api_key_here", "api key here"),
    ("abc", "suspiciously short"),
    ("123", "numeric short"),
    ("test", "short and a placeholder word"),
    ("", "empty"),
    ("   ", "whitespace only"),
    (None, "unset"),
]

_REAL_KEYS = [
    "sk-1234567890abcdef1234567890abcdef",
    "live_api_key_1234567890",
    "prod-key-abcdef123456",
    "real_mistral_key_with_long_string",
]


def _client_with_mistral_key(monkeypatch, raw_key):
    if raw_key is None:
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    else:
        monkeypatch.setenv("MISTRAL_API_KEY", raw_key)
    monkeypatch.setenv("USPTO_API_KEY", "test_key_for_validation")
    return EnhancedPatentClient()


@pytest.mark.parametrize("raw_key, description", _PLACEHOLDERS)
def test_a_placeholder_never_becomes_the_clients_key(
    monkeypatch, raw_key, description
):
    client = _client_with_mistral_key(monkeypatch, raw_key)
    assert client.mistral_api_key is None, (
        f"{description}: {raw_key!r} survived onto the client, so the paid OCR "
        f"tier would be attempted with a placeholder as the credential"
    )


@pytest.mark.parametrize("raw_key", _REAL_KEYS)
def test_a_real_looking_key_reaches_the_client(monkeypatch, raw_key):
    client = _client_with_mistral_key(monkeypatch, raw_key)
    assert client.mistral_api_key == raw_key, (
        "a usable key was discarded, which disables OCR silently"
    )


def test_a_key_containing_mistral_api_key_is_rejected(monkeypatch):
    """`mistral_api_key` is itself a placeholder pattern: someone pasting the
    VARIABLE NAME instead of its value. It was in OCRService's list and not in
    the client's, so this only became true when the two merged (audit D-2)."""
    client = _client_with_mistral_key(monkeypatch, "mistral_api_key_abc123def456")
    assert client.mistral_api_key is None
