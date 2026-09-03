#!/usr/bin/env python3
"""PTAB document store basics: registration round-trip, proceeding-number
recognition, and the registration model.

The assertions here are not new — but they used to sit inside a
`try/except Exception: return False` that swallowed every one of them, and
pytest reports `return False` as PASS (audit T-4). Removing the wrapper is the
entire fix; the expectations are unchanged.
"""

import pytest

from patent_filewrapper_mcp.proxy.models import PTABDocumentRegistration
from patent_filewrapper_mcp.proxy.ptab_document_store import PTABDocumentStore

_ENHANCED = "PTAB-2024-05-15_IPR2024-00123_PAT-8524787_PETITION.pdf"

# No 'api_key': the store no longer persists the ODP key; the download route
# resolves the live one from the secure store.
_DOC = {
    "proceeding_number": "IPR2024-00123",
    "document_identifier": "TEST_DOC_001",
    "download_url": (
        "https://api.uspto.gov/ptab/proceedings/IPR2024-00123/documents/TEST_DOC_001"
    ),
    "patent_number": "8524787",
    "application_number": "13574710",
    "proceeding_type": "IPR",
    "document_type": "petition",
    "enhanced_filename": _ENHANCED,
}


@pytest.fixture
def store(tmp_path):
    return PTABDocumentStore(db_path=str(tmp_path / "ptab_documents.db"))


def test_a_registered_document_round_trips(store):
    assert store.register_document(**_DOC) is True

    doc = store.get_document(_DOC["proceeding_number"], _DOC["document_identifier"])
    assert doc is not None, "get_document returned nothing"
    assert doc["enhanced_filename"] == _ENHANCED


@pytest.mark.parametrize(
    "number",
    [
        "IPR2024-00123",
        "PGR2025-00456",
        "CBM2025-00789",
        "DER2025-00012",
        "2025000950",  # Appeal
        "2024001234",  # Appeal
    ],
)
def test_valid_proceeding_numbers_are_recognized(store, number):
    assert store.is_ptab_proceeding_number(number)


@pytest.mark.parametrize(
    "number, why",
    [
        ("INVALID-123", "not a PTAB shape"),
        ("202500095", "9 digits, appeals are 10"),
        ("20250009501", "11 digits, appeals are 10"),
    ],
)
def test_invalid_proceeding_numbers_are_rejected(store, number, why):
    assert not store.is_ptab_proceeding_number(number), why


@pytest.mark.parametrize(
    "proceeding_number, doc_id, filename",
    [
        (
            "IPR2024-00123",
            "TEST_DOC_001",
            "PTAB-2024-05-15_IPR2024-00123_DECISION.pdf",
        ),
        (
            "2025000950",
            "TEST_DOC_002",
            "PTAB-2025-03-15_2025000950_DECISION.pdf",
        ),
    ],
)
def test_the_registration_model_accepts_both_proceeding_shapes(
    proceeding_number, doc_id, filename
):
    registration = PTABDocumentRegistration(
        source="ptab",
        proceeding_number=proceeding_number,
        document_identifier=doc_id,
        download_url="https://api.uspto.gov/test",
        access_token="test_token_12345",
        enhanced_filename=filename,
    )
    assert registration.proceeding_number == proceeding_number
