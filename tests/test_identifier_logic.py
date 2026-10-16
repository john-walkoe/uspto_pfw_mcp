"""Pytest coverage for the 'critical bug' identifier logic (audit F42).

Both modules carried in-module TEST_CASES lists that were never executed by
pytest — the data already existed, only the runner was missing.
"""

import pytest

from patent_filewrapper_mcp.util.identifier_normalization import (
    TEST_CASES as NORMALIZE_CASES,
    normalize_identifier,
)
from patent_filewrapper_mcp.util.input_processing import (
    TEST_CASES as PROCESS_CASES,
    process_identifier_inputs,
)


@pytest.mark.parametrize(
    "test_input,expected_type,expected_confidence",
    NORMALIZE_CASES,
    ids=[c[0] for c in NORMALIZE_CASES],
)
def test_normalize_identifier(test_input, expected_type, expected_confidence):
    result = normalize_identifier(test_input)
    assert result.identifier_type == expected_type, (
        f"{test_input!r}: expected {expected_type}, got {result.identifier_type}"
    )
    # Confidence drift is a warning in the legacy runner — keep it an
    # assertion here so silent reclassification gets caught
    assert result.confidence == expected_confidence, (
        f"{test_input!r}: expected confidence {expected_confidence}, got {result.confidence}"
    )


@pytest.mark.parametrize(
    "case",
    PROCESS_CASES,
    ids=[str(c["inputs"]) for c in PROCESS_CASES],
)
def test_process_identifier_inputs(case):
    result = process_identifier_inputs(**case["inputs"])
    assert result.identifier_type == case["expected_type"]
    assert result.search_strategy == case["expected_strategy"]


def test_process_identifier_inputs_rejects_empty():
    with pytest.raises(ValueError):
        process_identifier_inputs("", "", "")


def test_eight_digit_serial_only_series_is_an_application_not_a_publication():
    """2026-09-19: D618,677's serial 29328018 was typed as a publication number
    (8 digits starting with 2), looked up on earliestPublicationNumber, and
    reported unresolved without the application lane being tried."""
    from patent_filewrapper_mcp.util.identifier_normalization import normalize_identifier

    info = normalize_identifier("29328018")
    assert info.identifier_type == "application"
    assert info.app_number_for_docs == "29328018"
    assert "29/328,018" in info.notes
    # reexamination control numbers ride the same rule
    assert normalize_identifier("90016071").identifier_type == "application"
    # an 8-digit number starting with 2 outside those series is ambiguous, never a publication
    assert normalize_identifier("20080141").identifier_type == "ambiguous"
    # the real publication shape is untouched
    assert normalize_identifier("20080141381").identifier_type == "publication"
    assert normalize_identifier("US 2024/0000001 A1").identifier_type == "publication"


@pytest.mark.parametrize(
    "typed,expected",
    [
        ("D618677", "D618677"),
        ("d618677", "D618677"),
        ("D618,677", "D618677"),
        ("US D618677 S1", "D618677"),
        ("USD618677S1", "D618677"),
        ("D0618677", "D618677"),
        ("RE48123", "RE48123"),
        ("RE48,123 E1", "RE48123"),
        ("PP12345 P2", "PP12345"),
        ("H1234", "H1234"),
    ],
)
def test_series_prefixed_patent_number_keeps_its_prefix(typed, expected):
    # The kind-code strip used to delete all of "D618677" (a letter followed by
    # digits to the end of the string), and "D618,677" lost its D and became
    # utility patent 618,677 of 1899. USPTO indexes these numbers WITH the prefix.
    info = normalize_identifier(typed)
    assert info.cleaned_value == expected
    assert info.identifier_type == "patent"
    assert info.confidence == "high"


@pytest.mark.parametrize("typed", ["7971071B2", "US 7,971,071 B2", "11752072", "29/328,018"])
def test_unprefixed_identifiers_are_untouched_by_the_prefix_rule(typed):
    assert normalize_identifier(typed).cleaned_value.isdigit()
