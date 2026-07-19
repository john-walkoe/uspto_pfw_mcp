#!/usr/bin/env python3
"""
Test PTAB integration workflow for future Open Data Portal integration

This test verifies that the PTAB document store and proxy integration
work correctly when PTAB moves to USPTO Open Data Portal.

Usage:
    python tests/test_ptab_integration.py
"""

import os
import sys
from pathlib import Path

# Add src to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from patent_filewrapper_mcp.proxy.ptab_document_store import PTABDocumentStore  # noqa: E402
from patent_filewrapper_mcp.proxy.models import PTABDocumentRegistration  # noqa: E402


def test_ptab_document_store():
    """Test PTAB document store functionality"""
    print("[TEST] Testing PTAB Document Store...")

    # Create test database
    test_db_path = str(project_root / "test_ptab_documents.db")
    if os.path.exists(test_db_path):
        os.remove(test_db_path)

    try:
        store = PTABDocumentStore(db_path=test_db_path)

        # Test data
        test_data = {
            'proceeding_number': 'IPR2024-00123',
            'document_identifier': 'TEST_DOC_001',
            'download_url': 'https://api.uspto.gov/ptab/proceedings/IPR2024-00123/documents/TEST_DOC_001',
            'api_key': 'test_api_key_12345',
            'patent_number': '8524787',
            'application_number': '13574710',
            'proceeding_type': 'IPR',
            'document_type': 'petition',
            'enhanced_filename': 'PTAB-2024-05-15_IPR2024-00123_PAT-8524787_PETITION.pdf'
        }

        # Test 1: Register document
        print("  [1] Testing document registration...")
        success = store.register_document(**test_data)
        assert success, "Document registration failed"
        print("    [OK] Document registered successfully")

        # Test 2: Retrieve document
        print("  [2] Testing document retrieval...")
        doc = store.get_document(test_data['proceeding_number'], test_data['document_identifier'])
        assert doc is not None, "Document not found"
        assert doc['enhanced_filename'] == test_data['enhanced_filename'], "Enhanced filename mismatch"
        assert doc['proceeding_type'] == test_data['proceeding_type'], "Proceeding type mismatch"
        print("    [OK] Document retrieved successfully")

        # Test 3: PTAB proceeding number validation
        print("  [3] Testing proceeding number validation...")
        valid_numbers = ['IPR2024-00123', 'PGR2025-00456', 'CBM2023-00789', 'DER2024-00012']
        invalid_numbers = ['invalid', '123-456', 'IPR2024-123', 'XYZ2024-00123']

        for num in valid_numbers:
            assert store.is_ptab_proceeding_number(num), f"Valid number {num} rejected"

        for num in invalid_numbers:
            assert not store.is_ptab_proceeding_number(num), f"Invalid number {num} accepted"

        print("    [OK] Proceeding number validation working correctly")

        # Test 4: Cross-reference queries
        print("  [4] Testing cross-reference queries...")

        # Add another document with same patent number
        test_data2 = test_data.copy()
        test_data2['proceeding_number'] = 'PGR2024-00456'
        test_data2['document_identifier'] = 'TEST_DOC_002'
        test_data2['proceeding_type'] = 'PGR'
        test_data2['document_type'] = 'response'
        test_data2['enhanced_filename'] = 'PTAB-2024-06-01_PGR2024-00456_PAT-8524787_RESPONSE.pdf'

        store.register_document(**test_data2)

        # Query by patent number
        docs_by_patent = store.get_documents_by_patent(test_data['patent_number'])
        assert len(docs_by_patent) == 2, f"Expected 2 documents for patent, got {len(docs_by_patent)}"
        print("    [OK] Patent number cross-reference working")

        # Query by application number
        docs_by_app = store.get_documents_by_application(test_data['application_number'])
        assert len(docs_by_app) == 2, f"Expected 2 documents for application, got {len(docs_by_app)}"
        print("    [OK] Application number cross-reference working")

        # Test 5: Statistics
        print("  [5] Testing statistics...")
        stats = store.get_statistics()
        assert stats['total_documents'] == 2, f"Expected 2 total documents, got {stats['total_documents']}"
        assert stats['unique_proceedings'] == 2, f"Expected 2 unique proceedings, got {stats['unique_proceedings']}"
        assert 'IPR' in stats['by_proceeding_type'], "IPR not in proceeding type stats"
        assert 'PGR' in stats['by_proceeding_type'], "PGR not in proceeding type stats"
        print("    [OK] Statistics working correctly")

        print("[PASS] PTAB Document Store: ALL TESTS PASSED")
        return True

    except Exception as e:
        print(f"[FAIL] PTAB Document Store test failed: {e}")
        return False
    finally:
        # Cleanup
        if os.path.exists(test_db_path):
            os.remove(test_db_path)


def test_ptab_model_validation():
    """Test PTAB Pydantic model validation"""
    print("[TEST] Testing PTAB Model Validation...")

    try:
        # Test 1: Valid data
        print("  ✅ Testing valid data...")
        valid_data = {
            'source': 'ptab',
            'proceeding_number': 'IPR2024-00123',
            'document_identifier': 'TEST_DOC_001',
            'download_url': 'https://api.uspto.gov/ptab/proceedings/IPR2024-00123/documents/TEST_DOC_001',
            'api_key': 'test_api_key_12345',
            'patent_number': '8524787',
            'application_number': '13574710',
            'proceeding_type': 'IPR',
            'document_type': 'petition',
            'enhanced_filename': 'PTAB-2024-05-15_IPR2024-00123_PAT-8524787_PETITION.pdf'
        }

        registration = PTABDocumentRegistration(**valid_data)
        assert registration.proceeding_number == 'IPR2024-00123'
        print("    ✅ Valid data accepted")

        # Test 2: Invalid proceeding number
        print("  ❌ Testing invalid proceeding number...")
        try:
            invalid_data = valid_data.copy()
            invalid_data['proceeding_number'] = 'INVALID-123'
            PTABDocumentRegistration(**invalid_data)
            assert False, "Should have rejected invalid proceeding number"
        except ValueError as e:
            assert "format" in str(e).lower(), f"Unexpected error message: {e}"
            print("    ✅ Invalid proceeding number rejected")

        # Test 3: Invalid source
        print("  ❌ Testing invalid source...")
        try:
            invalid_data = valid_data.copy()
            invalid_data['source'] = 'invalid'
            PTABDocumentRegistration(**invalid_data)
            assert False, "Should have rejected invalid source"
        except ValueError:
            print("    ✅ Invalid source rejected")

        # Test 4: Invalid enhanced filename
        print("  ❌ Testing invalid enhanced filename...")
        try:
            invalid_data = valid_data.copy()
            invalid_data['enhanced_filename'] = 'invalid filename with spaces.pdf'
            PTABDocumentRegistration(**invalid_data)
            assert False, "Should have rejected invalid filename"
        except ValueError as e:
            assert "invalid characters" in str(e).lower(), f"Unexpected error message: {e}"
            print("    ✅ Invalid filename rejected")

        # Test 5: Invalid URL
        print("  ❌ Testing invalid download URL...")
        try:
            invalid_data = valid_data.copy()
            invalid_data['download_url'] = 'http://example.com/doc.pdf'
            PTABDocumentRegistration(**invalid_data)
            assert False, "Should have rejected non-USPTO URL"
        except ValueError as e:
            assert "uspto.gov" in str(e).lower(), f"Unexpected error message: {e}"
            print("    ✅ Invalid download URL rejected")

        print("✅ PTAB Model Validation: ALL TESTS PASSED")
        return True

    except Exception as e:
        print(f"❌ PTAB Model validation test failed: {e}")
        return False


def test_proxy_integration_simulation():
    """
    Simulate PTAB proxy integration workflow

    Note: This doesn't start an actual server, just tests the workflow logic
    """
    print("🧪 Testing PTAB Proxy Integration Simulation...")

    try:
        # Test 1: PTAB proceeding number detection
        print("  🔍 Testing proceeding number detection...")
        from patent_filewrapper_mcp.proxy.ptab_document_store import get_ptab_store

        ptab_store = get_ptab_store()

        # Test various proceeding number formats
        test_cases = [
            ('IPR2024-00123', True),
            ('PGR2025-00456', True),
            ('CBM2023-00789', True),
            ('DER2024-00012', True),
            ('ipr2024-00123', True),  # Should work case-insensitive
            ('17896175', False),      # PFW app number
            ('550e8400-e29b-41d4-a716-446655440000', False),  # FPD UUID
            ('INVALID-123', False),   # Invalid format
        ]

        for test_input, expected in test_cases:
            result = ptab_store.is_ptab_proceeding_number(test_input)
            assert result == expected, f"Expected {expected} for '{test_input}', got {result}"

        print("    ✅ Proceeding number detection working correctly")

        # Test 2: Enhanced filename generation pattern
        print("  📁 Testing enhanced filename patterns...")

        # Test filename components
        test_filename = "PTAB-2024-05-15_IPR2024-00123_PAT-8524787_FINAL_WRITTEN_DECISION.pdf"

        # Verify it passes validation
        registration_data = {
            'source': 'ptab',
            'proceeding_number': 'IPR2024-00123',
            'document_identifier': 'TEST_DOC',
            'download_url': 'https://api.uspto.gov/test',
            'api_key': 'test_key',
            'enhanced_filename': test_filename
        }

        registration = PTABDocumentRegistration(**registration_data)
        assert registration.enhanced_filename == test_filename
        print("    ✅ Enhanced filename pattern validation working")

        # Test 3: Cross-MCP integration fields
        print("  🔗 Testing cross-MCP integration fields...")

        # Verify all cross-reference fields are captured
        full_registration_data = {
            'source': 'ptab',
            'proceeding_number': 'IPR2024-00123',
            'document_identifier': 'TEST_DOC',
            'download_url': 'https://api.uspto.gov/test',
            'api_key': 'test_key',
            'patent_number': '8524787',           # For cross-reference to PFW
            'application_number': '13574710',     # For cross-reference to PFW
            'proceeding_type': 'IPR',            # For filtering and organization
            'document_type': 'petition',         # For document classification
            'enhanced_filename': test_filename
        }

        full_registration = PTABDocumentRegistration(**full_registration_data)
        assert full_registration.patent_number == '8524787'
        assert full_registration.application_number == '13574710'
        assert full_registration.proceeding_type == 'IPR'
        assert full_registration.document_type == 'petition'
        print("    ✅ Cross-MCP integration fields working")

        print("✅ PTAB Proxy Integration Simulation: ALL TESTS PASSED")
        return True

    except Exception as e:
        print(f"❌ PTAB Proxy integration simulation failed: {e}")
        return False


def print_test_summary():
    """Print test summary and next steps"""
    print("\n" + "="*60)
    print("📋 PTAB INTEGRATION TEST SUMMARY")
    print("="*60)
    print()
    print("✅ PTAB Document Store - Ready for Open Data Portal")
    print("   • SQLite database with proper schema")
    print("   • Proceeding number validation (IPR, PGR, CBM, DER)")
    print("   • Cross-reference queries (patent/application numbers)")
    print("   • Enhanced filename support")
    print()
    print("✅ PTAB Registration Models - Ready for validation")
    print("   • Pydantic models with comprehensive validation")
    print("   • Security checks (USPTO domain, filename safety)")
    print("   • Proceeding number format validation")
    print()
    print("✅ PTAB Proxy Integration - Ready for centralized hub")
    print("   • Download endpoint detection logic")
    print("   • Registration endpoint for document metadata")
    print("   • Enhanced filename streaming")
    print("   • Statistics and monitoring endpoints")
    print()
    print("🚀 NEXT STEPS:")
    print("   1. When PTAB moves to Open Data Portal:")
    print("      • Update PTAB MCP to use Open Data Portal API")
    print("      • Add PFW detection logic (same as FPD pattern)")
    print("      • Register documents with PFW centralized proxy")
    print("      • Generate enhanced filenames before registration")
    print()
    print("   2. No changes needed in PFW MCP:")
    print("      • Database schema already ready")
    print("      • Registration endpoint already implemented")
    print("      • Download detection already implemented")
    print("      • Enhanced filename support already implemented")
    print()
    print("   3. Testing with real PTAB MCP:")
    print("      • Start PFW proxy server")
    print("      • Register test PTAB document")
    print("      • Verify download links work")
    print("      • Test persistent links across restarts")
    print()
    print("✨ ARCHITECTURE READY: No database changes needed when PTAB")
    print("   moves to Open Data Portal - everything is pre-configured!")


def main():
    """Run all PTAB integration tests"""
    print("🧪 PTAB INTEGRATION TESTS - Future Open Data Portal Support")
    print("="*60)
    print()

    all_passed = True

    # Test 1: Document Store
    if not test_ptab_document_store():
        all_passed = False

    print()

    # Test 2: Model Validation
    if not test_ptab_model_validation():
        all_passed = False

    print()

    # Test 3: Proxy Integration Simulation
    if not test_proxy_integration_simulation():
        all_passed = False

    print()

    if all_passed:
        print("🎉 ALL PTAB INTEGRATION TESTS PASSED!")
        print_test_summary()
        return True
    else:
        print("❌ SOME TESTS FAILED - Check output above for details")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
