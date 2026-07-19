"""
Test FPD integration with PFW centralized proxy

Tests document registration and download functionality for FPD petition documents.
"""

import os
import sys
import asyncio
import httpx
import json
from pathlib import Path

# Add src to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from patent_filewrapper_mcp.proxy.fpd_document_store import FPDDocumentStore  # noqa: E402

import pytest


def _proxy_reachable(port: int = 8080) -> bool:
    """True when a proxy is listening locally — proxy-dependent tests
    auto-skip instead of failing when it isn't (audit F45)."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0




def test_fpd_document_store():
    """Test FPD document store basic functionality"""
    print("\n" + "="*80)
    print("TEST 1: FPD Document Store Basic Functionality")
    print("="*80)

    # Create test database
    test_db_path = str(project_root / "test_fpd_documents.db")
    if os.path.exists(test_db_path):
        os.remove(test_db_path)

    try:
        store = FPDDocumentStore(db_path=test_db_path)

        # Test UUID detection
        test_uuid = "550e8400-e29b-41d4-a716-446655440000"
        test_app_number = "17896175"

        print("\n[+] Testing UUID detection:")
        print(f"  - Is '{test_uuid}' a UUID? {store.is_fpd_petition_id(test_uuid)}")
        print(f"  - Is '{test_app_number}' a UUID? {store.is_fpd_petition_id(test_app_number)}")

        assert store.is_fpd_petition_id(test_uuid) is True
        assert store.is_fpd_petition_id(test_app_number) is False
        print("  [OK] UUID detection working correctly")

        # Test document registration
        print("\n[+] Testing document registration:")
        success = store.register_document(
            petition_id=test_uuid,
            document_identifier="TEST_DOC_123",
            download_url="https://api.uspto.gov/api/v1/download/test.pdf",
            api_key="test_api_key",
            application_number="12345678"
        )

        assert success is True
        print("  [OK] Document registered successfully")

        # Test document retrieval
        print("\n[+] Testing document retrieval:")
        doc = store.get_document(test_uuid, "TEST_DOC_123")

        assert doc is not None
        assert doc['petition_id'] == test_uuid.lower()  # Should be normalized to lowercase
        assert doc['document_identifier'] == "TEST_DOC_123"
        assert doc['download_url'] == "https://api.uspto.gov/api/v1/download/test.pdf"
        assert doc['api_key'] == "test_api_key"
        assert doc['application_number'] == "12345678"
        print("  [OK] Document retrieved successfully")
        print(f"     Petition ID: {doc['petition_id']}")
        print(f"     Doc ID: {doc['document_identifier']}")
        print(f"     App Number: {doc['application_number']}")
        print(f"     Registered: {doc['registered_at']}")

        # Test statistics
        print("\n[+] Testing statistics:")
        stats = store.get_statistics()

        assert stats['total_documents'] == 1
        assert stats['unique_petitions'] == 1
        assert stats['with_application_numbers'] == 1
        print("  [OK] Statistics retrieved successfully")
        print(f"     Total documents: {stats['total_documents']}")
        print(f"     Unique petitions: {stats['unique_petitions']}")
        print(f"     With app numbers: {stats['with_application_numbers']}")

        print("\n[PASS] TEST 1 PASSED - FPD Document Store working correctly")

    finally:
        # Cleanup
        if os.path.exists(test_db_path):
            os.remove(test_db_path)


async def test_registration_endpoint():
    """Test the POST /register-fpd-document endpoint"""
    print("\n" + "="*80)
    print("TEST 2: FPD Document Registration Endpoint")
    print("="*80)
    print("\nNOTE: This test requires the PFW proxy server to be running on port 8080")
    print("      Start server with: uv run patent-filewrapper-mcp")
    print("      or skip with SKIP_PROXY_TESTS=1")

    if os.getenv("SKIP_PROXY_TESTS") or not _proxy_reachable():
        pytest.skip("proxy not running on 8080 (auto-skip — audit F45)")

    try:
        # Registration payload matching the CURRENT API: access_token (HMAC
        # inter-service token), not the legacy api_key field. This token is
        # bogus, so the endpoint must reject it — the assertion below checks
        # that auth is enforced, not that registration succeeds.
        registration_payload = {
            "source": "fpd",
            "petition_id": "550e8400-e29b-41d4-a716-446655440000",
            "document_identifier": "TEST_DOC_456",
            "download_url": "https://api.uspto.gov/api/v1/download/applications/12345678/documents/test.pdf",
            "access_token": "bogus-token-0123456789",
            "application_number": "12345678"
        }

        print("\n[+] Sending registration request to proxy server...")
        print("   URL: http://localhost:8080/register-fpd-document")
        print(f"   Payload: {json.dumps(registration_payload, indent=2)}")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://localhost:8080/register-fpd-document",
                json=registration_payload,
                timeout=10.0
            )

            print("\n[+] Response received:")
            print(f"   Status Code: {response.status_code}")
            print(f"   Response: {json.dumps(response.json(), indent=2)}")

            # A bogus access_token must be rejected (401/403), proving the
            # endpoint is reachable AND the inter-service auth gate works.
            assert response.status_code in (401, 403), (
                f"expected auth rejection for bogus token, got {response.status_code}"
            )
            print("\n[PASS] TEST 2 PASSED - Registration endpoint enforces access-token auth")
            return None

    except httpx.ConnectError:
        print("\n[WARN] WARNING: Could not connect to proxy server on port 8080")
        print("   To test this functionality, start the server with:")
        print("   uv run patent-filewrapper-mcp")
        print("\n[SKIP] TEST 2 SKIPPED - Server not running")
        return None
    except Exception as e:
        print(f"\n[FAIL] TEST 2 FAILED: {e}")
        raise


async def test_fpd_stats_endpoint():
    """Test the GET /fpd-stats endpoint"""
    print("\n" + "="*80)
    print("TEST 3: FPD Statistics Endpoint")
    print("="*80)

    if os.getenv("SKIP_PROXY_TESTS") or not _proxy_reachable():
        pytest.skip("proxy not running on 8080 (auto-skip — audit F45)")

    try:
        print("\n[+] Requesting FPD statistics from proxy server...")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                "http://localhost:8080/fpd-stats",
                timeout=10.0
            )

            print("\n[+] Response received:")
            print(f"   Status Code: {response.status_code}")
            print(f"   Statistics: {json.dumps(response.json(), indent=2)}")

            assert response.status_code == 200
            stats = response.json()

            # Check that we have the expected fields
            assert 'total_documents' in stats
            assert 'unique_petitions' in stats
            assert 'with_application_numbers' in stats
            assert 'database_path' in stats

            print("\n[PASS] TEST 3 PASSED - Statistics endpoint working correctly")

    except httpx.ConnectError:
        print("\n[SKIP] TEST 3 SKIPPED - Server not running")
    except Exception as e:
        print(f"\n[FAIL] TEST 3 FAILED: {e}")
        raise


async def test_validation():
    """Test request validation for registration endpoint"""
    print("\n" + "="*80)
    print("TEST 4: Request Validation")
    print("="*80)

    if os.getenv("SKIP_PROXY_TESTS") or not _proxy_reachable():
        pytest.skip("proxy not running on 8080 (auto-skip — audit F45)")

    try:
        # Test invalid UUID format
        print("\n[+] Testing invalid UUID format...")
        invalid_payload = {
            "source": "fpd",
            "petition_id": "not-a-valid-uuid",  # Invalid UUID
            "document_identifier": "TEST_DOC",
            "download_url": "https://api.uspto.gov/test.pdf",
            "access_token": "bogus-token-0123456789"
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://localhost:8080/register-fpd-document",
                json=invalid_payload,
                timeout=10.0
            )

            print(f"   Status Code: {response.status_code}")
            assert response.status_code == 422  # Validation error
            print("   [OK] Invalid UUID rejected correctly")

        # Test invalid download URL
        print("\n[+] Testing invalid download URL...")
        invalid_payload = {
            "source": "fpd",
            "petition_id": "550e8400-e29b-41d4-a716-446655440000",
            "document_identifier": "TEST_DOC",
            "download_url": "http://malicious-site.com/test.pdf",  # Non-HTTPS
            "access_token": "bogus-token-0123456789"
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://localhost:8080/register-fpd-document",
                json=invalid_payload,
                timeout=10.0
            )

            print(f"   Status Code: {response.status_code}")
            assert response.status_code == 422  # Validation error
            print("   [OK] Invalid URL rejected correctly")

        print("\n[PASS] TEST 4 PASSED - Validation working correctly")

    except httpx.ConnectError:
        print("\n[SKIP] TEST 4 SKIPPED - Server not running")
    except Exception as e:
        print(f"\n[FAIL] TEST 4 FAILED: {e}")
        raise


async def main():
    """Run all tests"""
    print("\n" + "="*80)
    print("FPD INTEGRATION TEST SUITE")
    print("="*80)

    # Test 1: Basic store functionality (always runs)
    test_fpd_document_store()

    # Tests 2-4: Require running server (can be skipped)
    await test_registration_endpoint()
    await test_fpd_stats_endpoint()
    await test_validation()

    print("\n" + "="*80)
    print("ALL TESTS COMPLETED")
    print("="*80)
    print("\nTo test with running server:")
    print("  1. Terminal 1: uv run patent-filewrapper-mcp")
    print("  2. Terminal 2: uv run python tests/test_fpd_integration.py")
    print("\nTo skip server tests:")
    print("  SKIP_PROXY_TESTS=1 uv run python tests/test_fpd_integration.py")
    print()


if __name__ == "__main__":
    asyncio.run(main())
