#!/usr/bin/env python3
"""The Mistral API key validator, which decides whether the paid OCR tier is
even reachable.

The previous version of this file asserted nothing and exercised no repo code
at all: it re-implemented `os.getenv` checks inline, printed SUCCESS, and
grepped README.md (audit T-4). It is now pointed at the real validator, which
as of audit D-2 is the single owner of the placeholder list that used to exist
in two divergent copies.
"""

import pytest

from patent_filewrapper_mcp.services.ocr_service import (
    _PLACEHOLDER_PATTERNS,
    validate_mistral_api_key,
)

_REAL_LOOKING_KEY = "sk-abcdefghijklmnopqrstuvwxyz012345"


class TestMissingKey:
    @pytest.mark.parametrize("raw", [None, "", "   "])
    def test_an_absent_key_is_none(self, raw):
        assert validate_mistral_api_key(raw) is None

    def test_a_key_shorter_than_ten_chars_is_treated_as_missing(self):
        assert validate_mistral_api_key("abc123") is None


class TestPlaceholders:
    @pytest.mark.parametrize("pattern", _PLACEHOLDER_PATTERNS)
    def test_every_declared_placeholder_pattern_is_actually_rejected(self, pattern):
        """A pattern in the list that does not reject is dead configuration."""
        assert validate_mistral_api_key(f"{pattern}_padding_to_length") is None

    @pytest.mark.parametrize(
        "pattern",
        # One from each of the two lists that had drifted apart, so a
        # regression that reinstates either copy fails here.
        ["change_me", "replace_me", "temp_key", "test_key", "example_key"],
    )
    def test_patterns_from_both_former_copies_are_caught(self, pattern):
        assert validate_mistral_api_key(f"{pattern}_padding_to_length") is None

    def test_matching_is_case_insensitive(self):
        assert validate_mistral_api_key("YOUR_KEY_HERE_PADDING") is None

    def test_extra_patterns_can_be_added_by_env(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_PLACEHOLDER_PATTERNS", "corporate_dummy")
        assert validate_mistral_api_key("corporate_dummy_value_here") is None


class TestRealKey:
    def test_a_plausible_key_survives(self):
        assert validate_mistral_api_key(_REAL_LOOKING_KEY) == _REAL_LOOKING_KEY

    def test_surrounding_whitespace_is_stripped(self):
        assert (
            validate_mistral_api_key(f"  {_REAL_LOOKING_KEY}  ") == _REAL_LOOKING_KEY
        )


def test_the_client_and_the_service_share_one_validator():
    """Both call sites must resolve to the same function; two lists that must
    be maintained in lockstep already were not (audit D-2)."""
    from patent_filewrapper_mcp.services.ocr_service import OCRService

    for candidate in ("change_me_padding", "temp_key_padding", _REAL_LOOKING_KEY):
        assert OCRService._validate_mistral_api_key(
            None, candidate
        ) == validate_mistral_api_key(candidate)
