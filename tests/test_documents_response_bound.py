"""Tests for the PFW_get_application_documents response-size backstop
(tools/document_tools.py `_bound_documents_response`).

claude.ai replaces an oversized tool result with a client-side truncation
error the server never sees, so the guard has to fire BEFORE the response
leaves: slim the downloadOptionBag entries, truncate the bag only if that is
not enough, and teach the caller how to narrow. Under the threshold it must
be a no-op — the same object back, byte-identical.

As of 2026-08-21 the truncation stage and the whole marker contract are
DELEGATED to shared/response_bounds.py; the PDF-option pre-slim stays local
(keeping "the PDF one" is a filter, not a projection, so it cannot be a shared
keep_fields spec). The legacy documents_returned / documents_total /
documents_note keys are preserved as ALIASES of the canonical `_bounds`
sub-keys, which is what the alias tests below pin.
"""

import json

from patent_filewrapper_mcp.shared.response_bounds import BOUNDS_KEY
from patent_filewrapper_mcp.tools.document_tools import (
    _DOCUMENTS_MIN_DOCS,
    _DOCUMENTS_SOFT_CHAR_LIMIT,
    _bound_documents_response,
)

_FAT_URL = "https://api.uspto.gov/api/v1/download/applications/14171705/" + "x" * 120


def _doc(index: int) -> dict:
    """One documentBag entry with the real 3-option download bag (PDF plus the
    MS_WORD/XML variants that dominate the payload)."""
    return {
        "documentIdentifier": f"DOC{index:05d}",
        "documentCode": "CTNF",
        "documentCodeDescriptionText": "Non-Final Rejection",
        "officialDate": "2024-01-15T00:00:00.000Z",
        "directionCategory": "OUTGOING",
        "downloadOptionBag": [
            {"mimeTypeIdentifier": "PDF", "downloadUrl": f"{_FAT_URL}/{index}.pdf",
             "pageTotalQuantity": 12},
            {"mimeTypeIdentifier": "MS_WORD", "downloadUrl": f"{_FAT_URL}/{index}.docx",
             "pageTotalQuantity": 12},
            {"mimeTypeIdentifier": "XML", "downloadUrl": f"{_FAT_URL}/{index}.xml",
             "pageTotalQuantity": 12},
        ],
    }


def _response(doc_count: int) -> dict:
    return {
        "success": True,
        "application_number": "14171705",
        "count": doc_count,
        "documentBag": [_doc(i) for i in range(doc_count)],
        "summary": {
            "total_documents": doc_count,
            "document_types": {"CTNF": doc_count},
            "key_documents": [],
            "filtering": {"filters_applied": ["limit=200"],
                          "original_document_count": doc_count,
                          "filtered_document_count": doc_count},
        },
        "guidance": {"workflow": ["unchanged"]},
    }


def _size(payload: dict) -> int:
    return len(json.dumps(payload, default=str))


def test_small_response_untouched():
    result = _response(5)
    before = json.dumps(result, default=str)

    bounded = _bound_documents_response(result)

    assert bounded is result
    assert json.dumps(bounded, default=str) == before
    assert "documents_note" not in bounded
    # All three MIME options survive when the guard does not fire.
    assert len(bounded["documentBag"][0]["downloadOptionBag"]) == 3


def test_oversized_response_slimmed_to_pdf_option():
    result = _response(60)
    assert _size(result) > _DOCUMENTS_SOFT_CHAR_LIMIT
    source_docs = list(result["documentBag"])

    bounded = _bound_documents_response(result)

    # Copy-on-slim: the client's own (possibly cached) entries are untouched.
    assert len(source_docs[0]["downloadOptionBag"]) == 3

    assert _size(bounded) <= _DOCUMENTS_SOFT_CHAR_LIMIT
    # Slimming alone was enough — every document survives.
    assert len(bounded["documentBag"]) == 60
    # CONTRACT CHANGE (2026-08-21): the aliases are mirrored whenever the guard
    # fires, so documents_returned/documents_total are now always present and
    # equal here rather than absent. The "nothing was dropped" signal moved to
    # `_bounds.stages`, which reports slimming without truncation.
    assert bounded[BOUNDS_KEY]["stages"] == ["slimmed"]
    assert bounded[BOUNDS_KEY]["slimmed_fields"] == ["downloadOptionBag"]
    assert bounded["documents_returned"] == bounded["documents_total"] == 60
    options = bounded["documentBag"][0]["downloadOptionBag"]
    assert options == [{"downloadUrl": f"{_FAT_URL}/0.pdf", "pageTotalQuantity": 12}]
    # Identifiers (the only thing downloads need) and the guidance blocks stay.
    assert bounded["documentBag"][0]["documentIdentifier"] == "DOC00000"
    assert bounded["summary"]["filtering"]["original_document_count"] == 60
    assert bounded["guidance"] == {"workflow": ["unchanged"]}
    note = bounded["documents_note"]
    assert "document_code" in note and "direction_category" in note
    assert "document_identifier" in note


def test_still_oversized_response_truncated_with_counts():
    result = _response(400)

    bounded = _bound_documents_response(result)

    assert _size(bounded) <= _DOCUMENTS_SOFT_CHAR_LIMIT
    kept = len(bounded["documentBag"])
    assert _DOCUMENTS_MIN_DOCS <= kept < 400
    assert bounded["documents_returned"] == kept
    assert bounded["documents_total"] == 400
    # CONTRACT CHANGE (2026-08-21): the counts used to be interpolated into
    # documents_note ("the first N of M"). They now live in the marker (and its
    # aliases), so the note stays a stable, cacheable recovery instruction.
    assert bounded[BOUNDS_KEY]["items_returned"] == kept
    assert bounded[BOUNDS_KEY]["items_total"] == 400
    assert "truncated" in bounded[BOUNDS_KEY]["stages"]
    assert bounded["documents_note"] == bounded[BOUNDS_KEY]["note"]


def test_empty_bag_is_a_no_op():
    result = {"success": True, "documentBag": [], "blob": "y" * 40_000}

    bounded = _bound_documents_response(result)

    assert bounded is result
    assert "documents_note" not in bounded


# ---------------------------------------------------------------------------
# Delegation to the shared guard
# ---------------------------------------------------------------------------

def test_marker_uses_the_shared_vocabulary_verbatim():
    """The marker must be the shared `_bounds` block, not a PFW dialect — the
    three USPTO MCPs are contractually identical here."""
    bounded = _bound_documents_response(_response(400))

    assert set(bounded[BOUNDS_KEY]) == {
        "applied",
        "reason",
        "size_chars",
        "size_limit",
        "stages",
        "slimmed_fields",
        "items_returned",
        "items_total",
        "note",
    }
    assert bounded[BOUNDS_KEY]["applied"] is True
    assert bounded[BOUNDS_KEY]["reason"] == "size"
    assert bounded[BOUNDS_KEY]["size_limit"] == _DOCUMENTS_SOFT_CHAR_LIMIT
    assert bounded[BOUNDS_KEY]["size_chars"] == _size(bounded)


def test_aliases_mirror_the_canonical_keys_exactly():
    bounded = _bound_documents_response(_response(400))
    marker = bounded[BOUNDS_KEY]

    assert bounded["documents_returned"] == marker["items_returned"]
    assert bounded["documents_total"] == marker["items_total"]
    assert bounded["documents_note"] == marker["note"]


def test_preslim_only_still_gets_a_marker():
    """When the PDF pre-slim alone brings the payload under budget the shared
    guard is a no-op — but the payload DID change, so it is still marked. An
    unmarked change is exactly what this guard exists to eliminate."""
    bounded = _bound_documents_response(_response(60))

    assert bounded[BOUNDS_KEY]["stages"] == ["slimmed"]
    assert bounded[BOUNDS_KEY]["items_returned"] == 60
    assert "documents_note" in bounded


def test_budget_follows_the_env_var(monkeypatch):
    """The soft ceiling is now USPTO_MAX_RESPONSE_CHARS, shared with FPD/PTAB.

    The payload is not asserted to land under the raw number: the shared guard
    reserves headroom for the marker and the min_items floor deliberately wins
    over the budget (shrinking past it would leave the caller nothing useful).
    What must hold is that the CONFIGURED budget is the one being enforced and
    that it actually bit.
    """
    before = _size(_response(60))
    monkeypatch.setenv("USPTO_MAX_RESPONSE_CHARS", "8000")

    bounded = _bound_documents_response(_response(60))

    assert bounded[BOUNDS_KEY]["size_limit"] == 8000
    assert "truncated" in bounded[BOUNDS_KEY]["stages"]
    assert bounded[BOUNDS_KEY]["items_returned"] < 60
    assert _size(bounded) < before // 4


def test_disabled_guard_leaves_the_payload_alone(monkeypatch):
    """USPTO_RESPONSE_BOUNDS_ENABLED=0 turns the shared stage off; the local
    PDF pre-slim still runs, so the marker is still attached and honest."""
    monkeypatch.setenv("USPTO_RESPONSE_BOUNDS_ENABLED", "0")

    bounded = _bound_documents_response(_response(400))

    assert len(bounded["documentBag"]) == 400  # nothing dropped
    assert bounded[BOUNDS_KEY]["stages"] == ["slimmed"]
