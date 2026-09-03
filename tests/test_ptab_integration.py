#!/usr/bin/env python3
"""
Test PTAB integration workflow for future Open Data Portal integration

This test verifies that the PTAB document store and proxy integration
work correctly when PTAB moves to USPTO Open Data Portal.

Usage:
    python tests/test_ptab_integration.py
"""

import os

# Add src to path for imports

from patent_filewrapper_mcp.proxy.ptab_document_store import PTABDocumentStore  # noqa: E402
from patent_filewrapper_mcp.proxy.models import PTABDocumentRegistration  # noqa: E402


def test_ptab_document_store(tmp_path):
    """Test PTAB document store functionality"""
    print("[TEST] Testing PTAB Document Store...")

    # Create test database
    test_db_path = str(tmp_path / "test_ptab_documents.db")
    if os.path.exists(test_db_path):
        os.remove(test_db_path)

    try:
        store = PTABDocumentStore(db_path=test_db_path)

        # Test data
        # No 'api_key': the store no longer persists the ODP key; the
        # download route resolves the live one from the secure store.
        test_data = {
            'proceeding_number': 'IPR2024-00123',
            'document_identifier': 'TEST_DOC_001',
            'download_url': 'https://api.uspto.gov/ptab/proceedings/IPR2024-00123/documents/TEST_DOC_001',
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

    finally:
        # Cleanup
        if os.path.exists(test_db_path):
            os.remove(test_db_path)


def test_ptab_model_validation():
    """Test PTAB Pydantic model validation"""
    print("[TEST] Testing PTAB Model Validation...")

    # Test 1: Valid data
    print("  ✅ Testing valid data...")
    valid_data = {
        'source': 'ptab',
        'proceeding_number': 'IPR2024-00123',
        'document_identifier': 'TEST_DOC_001',
        'download_url': 'https://api.uspto.gov/ptab/proceedings/IPR2024-00123/documents/TEST_DOC_001',
        'access_token': 'test_access_token_12345',
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

    # Test 5: Invalid URL. Two separate guards, and they fire in order:
    # plain http never reaches the host check, so testing only
    # 'http://example.com' proved the HTTPS rule and left the uspto.gov rule
    # unexercised. This assertion previously named the wrong one, and the
    # swallowing except hid that it never held.
    print("  ❌ Testing invalid download URL...")
    try:
        invalid_data = valid_data.copy()
        invalid_data['download_url'] = 'http://api.uspto.gov/doc.pdf'
        PTABDocumentRegistration(**invalid_data)
        assert False, "Should have rejected a plain-http URL"
    except ValueError as e:
        assert "https" in str(e).lower(), f"Unexpected error message: {e}"

    try:
        invalid_data = valid_data.copy()
        invalid_data['download_url'] = 'https://example.com/doc.pdf'
        PTABDocumentRegistration(**invalid_data)
        assert False, "Should have rejected non-USPTO URL"
    except ValueError as e:
        assert "uspto.gov" in str(e).lower(), f"Unexpected error message: {e}"
        print("    ✅ Invalid download URL rejected")

    print("✅ PTAB Model Validation: ALL TESTS PASSED")



def test_proxy_integration_simulation():
    """
    Simulate PTAB proxy integration workflow

    Note: This doesn't start an actual server, just tests the workflow logic
    """
    print("🧪 Testing PTAB Proxy Integration Simulation...")

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
        'access_token': 'test_access_token_12345',
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
        'access_token': 'test_access_token_12345',
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

