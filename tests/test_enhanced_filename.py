"""Enhanced filenames survive the FPD document store round-trip, and the
pydantic model rejects the filenames that would poison Content-Disposition.

Rewritten from a 163-line console script with 11 `return False` exits and zero
assertions: if FPDDocumentStore stopped storing enhanced filenames entirely,
the old version printed [FAIL] and reported PASS (audit T-4). The `from src.`
imports it used created a SECOND module object with its own module-level
singletons, so monkeypatching the real package did nothing here (audit T-5).
"""

import pytest

from patent_filewrapper_mcp.proxy.fpd_document_store import FPDDocumentStore
from patent_filewrapper_mcp.proxy.models import FPDDocumentRegistration

_PETITION_ID = "de4df959-dfe6-5b63-9ff2-d583b7333abd"
_ENHANCED = "PET-2025-09-03_APP-18462633_PATENT_PROSECUTION_HIGHWAY_DECISION.pdf"


@pytest.fixture
def store(tmp_path):
    return FPDDocumentStore(db_path=str(tmp_path / "fpd_documents.db"))


def _register(store, petition_id, doc_id, enhanced_filename):
    return store.register_document(
        petition_id=petition_id,
        document_identifier=doc_id,
        download_url=(
            f"https://api.uspto.gov/api/v1/download/applications/"
            f"18462633/{doc_id}.pdf"
        ),
        application_number="18462633",
        enhanced_filename=enhanced_filename,
    )


class TestRoundTrip:
    def test_an_enhanced_filename_survives_the_round_trip(self, store):
        assert _register(store, _PETITION_ID, "MF47IXVI120X170", _ENHANCED) is True

        doc = store.get_document(_PETITION_ID, "MF47IXVI120X170")
        assert doc, "get_document returned nothing for a just-registered document"
        assert doc.get("enhanced_filename") == _ENHANCED

    def test_a_document_with_no_enhanced_filename_stores_none(self, store):
        petition_id = "550e8400-e29b-41d4-a716-446655440000"
        assert _register(store, petition_id, "ABC123DEF", None) is True

        doc = store.get_document(petition_id, "ABC123DEF")
        assert doc, "get_document returned nothing"
        assert doc.get("enhanced_filename") is None


def _registration(**overrides):
    payload = {
        "source": "fpd",
        "petition_id": _PETITION_ID,
        "document_identifier": "TEST123",
        "download_url": "https://api.uspto.gov/test.pdf",
        # The model's field is access_token. The old version of this file
        # passed `api_key=`, so EVERY construction here raised a missing-field
        # ValidationError — and because ValidationError is a ValueError, the
        # two "invalid filename is rejected" branches passed for the wrong
        # reason while the two "valid filename is accepted" branches took the
        # `return False` exit that pytest reads as PASS.
        "access_token": "test_token_1234567890",
        "application_number": "12345678",
        "enhanced_filename": "PET-2024-05-15_APP-12345678_DECISION.pdf",
    }
    payload.update(overrides)
    return FPDDocumentRegistration(**payload)


class TestFilenameValidation:
    def test_a_well_formed_pdf_filename_is_accepted(self):
        assert (
            _registration().enhanced_filename
            == "PET-2024-05-15_APP-12345678_DECISION.pdf"
        )

    def test_none_is_accepted_for_backward_compatibility(self):
        assert _registration(enhanced_filename=None).enhanced_filename is None

    @pytest.mark.parametrize(
        "filename, why",
        [
            ("PET-2024-05-15_APP-12345678_DECISION.txt", "non-pdf extension"),
            ("PET-2024-05-15_APP-12345678_DECISION!@#$.pdf", "invalid characters"),
        ],
    )
    def test_a_bad_filename_is_rejected(self, filename, why):
        with pytest.raises(ValueError):
            _registration(enhanced_filename=filename)
