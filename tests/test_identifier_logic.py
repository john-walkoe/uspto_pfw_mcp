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
