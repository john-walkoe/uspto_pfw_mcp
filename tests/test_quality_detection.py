#!/usr/bin/env python3
"""The free-vs-paid extraction gate.

`is_good_extraction` decides whether a document escalates from the free pypdf
tier to the metered Mistral OCR tier, so a wrong answer here costs money.

Two defects made this file worthless before (audit T-4, readability R-5): it
carried its OWN copy of `is_good_extraction` rather than importing the real
one, so the production function was never executed; and it reported by
`return passed == total`, which pytest reads as PASS either way.
"""

import pytest

from patent_filewrapper_mcp.api.enhanced_client import (
    EnhancedPatentClient,
    extraction_reject_reason,
)

_GOOD = [
    "This is a patent application for a secure hardware adjunct that provides "
    "authentication services and cryptographic operations",
    "The invention relates to secure cryptographic methods using 256-bit "
    "encryption algorithms for hardware security modules",
    "A method for implementing secure boot processes in embedded systems "
    "comprising authentication of firmware images",
]

_BAD = [
    ("empty", "", "too_short"),
    ("short", "ABC", "too_short"),
    ("whitespace only", "   \n\t  ", "too_short"),
    ("CJK garbage", "㿁㿂㿃㿄㿅㿆㿇㿈㿉"
                    "㿊㿋㿌㿍㿎㿏㿐㿑㿒"
                    "㿓㿔㿕㿖㿗㿘㿙㿚㿛"
                    "㿜㿝㿞㿟", "too_short"),
    ("symbol noise", "###$$$%%%^^^&&&***((()))!!!", "too_short"),
    ("one-letter words", "a b c d e f g h i j k l m n o p q r", "too_short"),
    ("no spaces", "averylongwordwithoutspacesormeaning" * 5, "too_few_words"),
]


@pytest.mark.parametrize("text", _GOOD)
def test_usable_extractions_do_not_escalate_to_the_paid_tier(text):
    assert extraction_reject_reason(text) is None
    assert EnhancedPatentClient.is_good_extraction(None, text) is True


@pytest.mark.parametrize("label, text, expected_check", _BAD)
def test_unusable_extractions_are_rejected(label, text, expected_check):
    reason = extraction_reject_reason(text)
    assert reason is not None, f"{label!r} was accepted as a usable extraction"
    assert reason.startswith(expected_check), (
        f"{label!r} was rejected by {reason!r}, expected {expected_check!r}"
    )
    assert EnhancedPatentClient.is_good_extraction(None, text) is False


def test_is_good_extraction_agrees_with_the_reason_helper():
    """The public name must stay a thin wrapper; the tier code calls both."""
    for text in _GOOD + [t for _, t, _ in _BAD]:
        assert EnhancedPatentClient.is_good_extraction(None, text) is (
            extraction_reject_reason(text) is None
        )


def test_the_alpha_ratio_check_is_reachable():
    """Enough words of enough length, but mostly digits: the only input shape
    that reaches the fourth check."""
    text = " ".join(["1234567890"] * 12)
    assert extraction_reject_reason(text).startswith("alpha_ratio")
