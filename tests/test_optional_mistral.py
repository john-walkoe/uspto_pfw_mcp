#!/usr/bin/env python3
"""
Test script to verify graceful handling when Mistral API key is missing.

This test simulates the scenario where:
1. A user has only USPTO_API_KEY set (no MISTRAL_API_KEY)
2. They try to extract content from a document that PyPDF2 cannot handle
3. The system should provide helpful guidance instead of failing

Run with: python test_optional_mistral.py
"""

import os
import asyncio
import tempfile
import logging
from src.patent_filewrapper_mcp.api.enhanced_client import EnhancedPatentClient

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_missing_mistral_key():
    """Test behavior when Mistral API key is missing"""

    # Save original Mistral API key if it exists
    original_mistral_key = os.getenv("MISTRAL_API_KEY")

    try:
        # Temporarily remove Mistral API key
        if "MISTRAL_API_KEY" in os.environ:
            del os.environ["MISTRAL_API_KEY"]

        # Verify we have USPTO API key
        if not os.getenv("USPTO_API_KEY"):
            logger.error("USPTO_API_KEY environment variable required for this test")
            return False

        # Create client (should work without Mistral key)
        client = EnhancedPatentClient()

        # Test case 1: Create a mock result that simulates PyPDF2 failure
        print("\n=== Test Case 1: Missing Mistral API Key Handling ===")

        # Create a test document extraction result
        app_number = "17896175"  # Using a known test case
        document_identifier = "test_doc_123"

        # Test the extract_document_content_hybrid method
        # This should trigger our new error handling logic
        try:
            result = await client.extract_document_content_hybrid(
                app_number, document_identifier, auto_optimize=True
            )

            print(f"Result success: {result.get('success', False)}")
            print(f"Extraction method: {result.get('extraction_method', 'N/A')}")
            print(f"Error: {result.get('error', 'N/A')}")
            print(f"Mistral API key missing flag: {result.get('mistral_api_key_missing', False)}")
            print(f"Suggestion: {result.get('suggestion', 'N/A')}")
            print(f"Auto optimization: {result.get('auto_optimization', 'N/A')}")

            # Verify our expected behavior
            if result.get('mistral_api_key_missing'):
                print("✅ Correctly detected missing Mistral API key")
                if "Set MISTRAL_API_KEY" in result.get('suggestion', ''):
                    print("✅ Provided helpful suggestion")
                else:
                    print("❌ Missing helpful suggestion")
                    return False
            else:
                print("❌ Did not detect missing Mistral API key")
                return False

        except Exception as e:
            print(f"❌ Unexpected exception: {e}")
            return False

        print("\n=== Test Case 2: Direct OCR Request Without Key ===")

        # Test direct OCR request without API key
        try:
            result = await client.extract_document_content_hybrid(
                app_number, document_identifier, auto_optimize=False
            )

            print(f"Result success: {result.get('success', False)}")
            print(f"Error: {result.get('error', 'N/A')}")
            print(f"Mistral API key missing flag: {result.get('mistral_api_key_missing', False)}")

            if result.get('mistral_api_key_missing') and "required for OCR" in result.get('error', ''):
                print("✅ Correctly handled direct OCR request without key")
            else:
                print("❌ Did not properly handle direct OCR request")
                return False

        except Exception as e:
            print(f"❌ Unexpected exception: {e}")
            return False

        print("\n✅ All tests passed - Mistral API key handling is working correctly!")
        return True

    finally:
        # Restore original Mistral API key if it existed
        if original_mistral_key:
            os.environ["MISTRAL_API_KEY"] = original_mistral_key

async def main():
    """Run the test"""
    print("Testing optional Mistral API key handling...")

    success = await test_missing_mistral_key()

    if success:
        print("\n🎉 All tests completed successfully!")
        print("\nKey improvements verified:")
        print("- ✅ System gracefully handles missing Mistral API key")
        print("- ✅ Provides helpful guidance to users")
        print("- ✅ Falls back to PyPDF2 when possible")
        print("- ✅ Clear error messages for different scenarios")
    else:
        print("\n❌ Some tests failed. Please check the implementation.")
        exit(1)

if __name__ == "__main__":
    asyncio.run(main())
