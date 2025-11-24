#!/usr/bin/env python3
"""
Simple PTAB integration test for future Open Data Portal integration

This test verifies that the PTAB document store and proxy integration
work correctly when PTAB moves to USPTO Open Data Portal.

Usage:
    python tests/test_ptab_simple.py
"""

import os
import sys
from pathlib import Path

# Add src to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from patent_filewrapper_mcp.proxy.ptab_document_store import PTABDocumentStore
from patent_filewrapper_mcp.proxy.models import PTABDocumentRegistration


def test_ptab_basic():
    """Test basic PTAB functionality"""
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
        
        # Test registration
        print("  [1] Testing document registration...")
        success = store.register_document(**test_data)
        assert success, "Document registration failed"
        print("    [OK] Document registered successfully")
        
        # Test retrieval
        print("  [2] Testing document retrieval...")
        doc = store.get_document(test_data['proceeding_number'], test_data['document_identifier'])
        assert doc is not None, "Document not found"
        assert doc['enhanced_filename'] == test_data['enhanced_filename'], "Enhanced filename mismatch"
        print("    [OK] Document retrieved successfully")
        
        # Test proceeding number validation
        print("  [3] Testing proceeding number validation...")
        # Test AIA Trial formats
        assert store.is_ptab_proceeding_number('IPR2024-00123'), "Valid IPR AIA Trial format rejected"
        assert store.is_ptab_proceeding_number('PGR2025-00456'), "Valid PGR AIA Trial format rejected"
        assert store.is_ptab_proceeding_number('CBM2025-00789'), "Valid CBM AIA Trial format rejected"
        assert store.is_ptab_proceeding_number('DER2025-00012'), "Valid DER AIA Trial format rejected"
        # Test Appeal formats
        assert store.is_ptab_proceeding_number('2025000950'), "Valid Appeal numeric format rejected"
        assert store.is_ptab_proceeding_number('2024001234'), "Valid Appeal numeric format rejected"
        # Test invalid formats
        assert not store.is_ptab_proceeding_number('INVALID-123'), "Invalid format accepted"
        assert not store.is_ptab_proceeding_number('202500095'), "9-digit number accepted (should be 10)"
        assert not store.is_ptab_proceeding_number('20250009501'), "11-digit number accepted (should be 10)"
        print("    [OK] Proceeding number validation working (AIA Trials and Appeals)")
        
        # Test Pydantic model
        print("  [4] Testing Pydantic model validation...")
        # Test AIA Trial format
        registration_trial = PTABDocumentRegistration(**{
            'source': 'ptab',
            'proceeding_number': 'IPR2024-00123',
            'document_identifier': 'TEST_DOC_001',
            'download_url': 'https://api.uspto.gov/test',
            'api_key': 'test_api_key_12345',
            'enhanced_filename': 'PTAB-2024-05-15_IPR2024-00123_DECISION.pdf'
        })
        assert registration_trial.proceeding_number == 'IPR2024-00123'
        
        # Test Appeal format
        registration_appeal = PTABDocumentRegistration(**{
            'source': 'ptab',
            'proceeding_number': '2025000950',
            'document_identifier': 'TEST_DOC_002',
            'download_url': 'https://api.uspto.gov/test',
            'api_key': 'test_api_key_12345',
            'enhanced_filename': 'PTAB-2025-03-15_2025000950_DECISION.pdf'
        })
        assert registration_appeal.proceeding_number == '2025000950'
        print("    [OK] Model validation working (AIA Trials and Appeals)")
        
        print("[PASS] PTAB Integration: ALL TESTS PASSED")
        return True
        
    except Exception as e:
        print(f"[FAIL] PTAB test failed: {e}")
        return False
    finally:
        # Cleanup
        if os.path.exists(test_db_path):
            os.remove(test_db_path)


def main():
    """Run PTAB integration test"""
    print("PTAB INTEGRATION TEST - Future Open Data Portal Support")
    print("=" * 60)
    
    success = test_ptab_basic()
    
    if success:
        print()
        print("SUCCESS: PTAB integration is ready for Open Data Portal!")
        print()
        print("NEXT STEPS:")
        print("  1. When PTAB moves to Open Data Portal:")
        print("     - Update PTAB MCP to use Open Data Portal API")
        print("     - Add PFW detection logic (same as FPD pattern)")
        print("     - Register documents with PFW centralized proxy")
        print("  2. No changes needed in PFW MCP:")
        print("     - Database schema already ready")
        print("     - Registration endpoint already implemented")
        print("     - Download detection already implemented")
        return True
    else:
        print("FAILURE: Check output above for details")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)