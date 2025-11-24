"""
Test enhanced filename integration for FPD documents
"""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.patent_filewrapper_mcp.proxy.fpd_document_store import FPDDocumentStore
from src.patent_filewrapper_mcp.proxy.models import FPDDocumentRegistration
import tempfile
import json

def test_enhanced_filename_storage():
    """Test that enhanced filenames are stored and retrieved correctly"""

    print("=" * 80)
    print("ENHANCED FILENAME INTEGRATION TEST")
    print("=" * 80)

    # Create temporary database for testing
    with tempfile.NamedTemporaryFile(mode='w', suffix='.db', delete=False) as tmp_file:
        tmp_db_path = tmp_file.name

    try:
        # Initialize store with temp database
        store = FPDDocumentStore(db_path=tmp_db_path)

        print("\n[+] TEST 1: Store document WITH enhanced filename")
        print("-" * 80)

        petition_id = "de4df959-dfe6-5b63-9ff2-d583b7333abd"
        doc_id = "MF47IXVI120X170"
        enhanced_filename = "PET-2025-09-03_APP-18462633_PATENT_PROSECUTION_HIGHWAY_DECISION.pdf"

        success = store.register_document(
            petition_id=petition_id,
            document_identifier=doc_id,
            download_url="https://api.uspto.gov/api/v1/download/applications/18462633/MF47IXVI120X170.pdf",
            api_key="test_key_123",
            application_number="18462633",
            enhanced_filename=enhanced_filename
        )

        if not success:
            print("[FAIL] Failed to register document")
            return False

        # Retrieve and verify
        doc_metadata = store.get_document(petition_id, doc_id)

        if not doc_metadata:
            print("[FAIL] Failed to retrieve document")
            return False

        retrieved_filename = doc_metadata.get('enhanced_filename')

        if retrieved_filename != enhanced_filename:
            print(f"[FAIL] Filename mismatch!")
            print(f"  Expected: {enhanced_filename}")
            print(f"  Got: {retrieved_filename}")
            return False

        print(f"[OK] Enhanced filename stored and retrieved correctly:")
        print(f"     {retrieved_filename}")

        print("\n[+] TEST 2: Store document WITHOUT enhanced filename")
        print("-" * 80)

        petition_id_2 = "550e8400-e29b-41d4-a716-446655440000"
        doc_id_2 = "ABC123DEF"

        success = store.register_document(
            petition_id=petition_id_2,
            document_identifier=doc_id_2,
            download_url="https://api.uspto.gov/api/v1/download/applications/12345678/ABC123DEF.pdf",
            api_key="test_key_456",
            application_number="12345678",
            enhanced_filename=None  # No enhanced filename
        )

        if not success:
            print("[FAIL] Failed to register document without enhanced filename")
            return False

        doc_metadata_2 = store.get_document(petition_id_2, doc_id_2)

        if not doc_metadata_2:
            print("[FAIL] Failed to retrieve document")
            return False

        retrieved_filename_2 = doc_metadata_2.get('enhanced_filename')

        if retrieved_filename_2 is not None:
            print(f"[FAIL] Expected None for enhanced_filename, got: {retrieved_filename_2}")
            return False

        print("[OK] Document without enhanced filename works correctly (None)")

        print("\n[+] TEST 3: Pydantic validation")
        print("-" * 80)

        # Test valid enhanced filename
        try:
            valid_registration = FPDDocumentRegistration(
                source="fpd",
                petition_id="de4df959-dfe6-5b63-9ff2-d583b7333abd",
                document_identifier="TEST123",
                download_url="https://api.uspto.gov/test.pdf",
                api_key="test_key_1234567890",
                application_number="12345678",
                enhanced_filename="PET-2024-05-15_APP-12345678_DECISION.pdf"
            )
            print("[OK] Valid enhanced filename accepted by Pydantic")
        except Exception as e:
            print(f"[FAIL] Valid filename rejected: {e}")
            return False

        # Test invalid enhanced filename (wrong extension)
        try:
            invalid_registration = FPDDocumentRegistration(
                source="fpd",
                petition_id="de4df959-dfe6-5b63-9ff2-d583b7333abd",
                document_identifier="TEST123",
                download_url="https://api.uspto.gov/test.pdf",
                api_key="test_key_1234567890",
                application_number="12345678",
                enhanced_filename="PET-2024-05-15_APP-12345678_DECISION.txt"
            )
            print("[FAIL] Invalid filename (.txt) should have been rejected")
            return False
        except ValueError as e:
            print(f"[OK] Invalid extension (.txt) rejected correctly: {e}")

        # Test invalid enhanced filename (invalid characters)
        try:
            invalid_registration = FPDDocumentRegistration(
                source="fpd",
                petition_id="de4df959-dfe6-5b63-9ff2-d583b7333abd",
                document_identifier="TEST123",
                download_url="https://api.uspto.gov/test.pdf",
                api_key="test_key_1234567890",
                application_number="12345678",
                enhanced_filename="PET-2024-05-15_APP-12345678_DECISION!@#$.pdf"
            )
            print("[FAIL] Invalid characters (!@#$) should have been rejected")
            return False
        except ValueError as e:
            print(f"[OK] Invalid characters rejected correctly")

        # Test None as enhanced filename (should be allowed)
        try:
            none_registration = FPDDocumentRegistration(
                source="fpd",
                petition_id="de4df959-dfe6-5b63-9ff2-d583b7333abd",
                document_identifier="TEST123",
                download_url="https://api.uspto.gov/test.pdf",
                api_key="test_key_1234567890",
                application_number="12345678",
                enhanced_filename=None
            )
            print("[OK] None as enhanced_filename accepted (backward compatibility)")
        except Exception as e:
            print(f"[FAIL] None should be allowed: {e}")
            return False

        print("\n" + "=" * 80)
        print("ALL ENHANCED FILENAME TESTS PASSED!")
        print("=" * 80)

        return True

    finally:
        # Cleanup temp database
        if os.path.exists(tmp_db_path):
            os.remove(tmp_db_path)


if __name__ == "__main__":
    success = test_enhanced_filename_storage()
    sys.exit(0 if success else 1)
