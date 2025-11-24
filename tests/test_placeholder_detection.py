#!/usr/bin/env python3
"""
Test script to verify placeholder API key detection works correctly.

This test ensures that common placeholder patterns are detected and treated
as missing API keys, preventing authentication errors.
"""

import os
import sys
import tempfile

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from patent_filewrapper_mcp.api.enhanced_client import EnhancedPatentClient

def test_placeholder_detection():
    """Test that placeholder API keys are correctly detected and treated as missing"""

    print("Testing placeholder API key detection...")

    # Test cases: [input_key, should_be_treated_as_missing, description]
    test_cases = [
        # Placeholder patterns that should be detected
        ("your_mistral_api_key_here", True, "Exact documentation placeholder"),
        ("your_mistral_api_key_here_OPTIONAL", True, "Documentation placeholder with OPTIONAL suffix"),
        ("YOUR_MISTRAL_API_KEY_HERE", True, "Uppercase placeholder"),
        ("your_key_here", True, "Generic key placeholder"),
        ("your_api_key_here", True, "Generic API key placeholder"),
        ("placeholder", True, "Simple placeholder"),
        ("PLACEHOLDER", True, "Uppercase placeholder"),
        ("optional", True, "Optional keyword"),
        ("OPTIONAL", True, "Uppercase optional"),
        ("change_me", True, "Change me placeholder"),
        ("replace_me", True, "Replace me placeholder"),
        ("insert_key_here", True, "Insert key placeholder"),
        ("api_key_here", True, "API key here placeholder"),

        # Short keys that should be detected as suspicious
        ("abc", True, "Suspiciously short key"),
        ("123", True, "Numeric short key"),
        ("test", True, "Test placeholder"),
        ("", True, "Empty string"),
        ("   ", True, "Whitespace only"),

        # Valid keys that should NOT be detected as placeholders
        ("sk-1234567890abcdef1234567890abcdef", False, "Valid-looking API key"),
        ("mistral_api_key_abc123def456", False, "Valid key with mistral prefix"),
        ("live_api_key_1234567890", False, "Valid live API key"),
        ("prod-key-abcdef123456", False, "Production key"),
        ("real_mistral_key_with_long_string", False, "Real key with descriptive name"),
        (None, True, "None value"),
    ]

    print(f"\nRunning {len(test_cases)} test cases...\n")

    all_passed = True

    for i, (input_key, should_be_missing, description) in enumerate(test_cases, 1):
        # Save original env vars
        original_mistral_key = os.getenv("MISTRAL_API_KEY")
        original_uspto_key = os.getenv("USPTO_API_KEY")

        try:
            # Set required USPTO key for client creation
            os.environ["USPTO_API_KEY"] = "test_key_for_validation"

            # Set the test Mistral key
            if input_key is None:
                if "MISTRAL_API_KEY" in os.environ:
                    del os.environ["MISTRAL_API_KEY"]
            else:
                os.environ["MISTRAL_API_KEY"] = input_key

            # Create client (this will trigger validation)
            client = EnhancedPatentClient()

            # Check if the key was properly validated
            is_treated_as_missing = (client.mistral_api_key is None)

            # Verify result
            if is_treated_as_missing == should_be_missing:
                status = "PASS"
            else:
                status = "FAIL"
                all_passed = False

            print(f"{i:2d}. {status} - {description}")
            print(f"    Input: {repr(input_key)}")
            print(f"    Expected missing: {should_be_missing}, Got missing: {is_treated_as_missing}")

            if not is_treated_as_missing == should_be_missing:
                print(f"    Client key: {repr(client.mistral_api_key)}")

            print()

        finally:
            # Restore original env vars
            if original_mistral_key is not None:
                os.environ["MISTRAL_API_KEY"] = original_mistral_key
            elif "MISTRAL_API_KEY" in os.environ:
                del os.environ["MISTRAL_API_KEY"]

            if original_uspto_key is not None:
                os.environ["USPTO_API_KEY"] = original_uspto_key
            elif "USPTO_API_KEY" in os.environ:
                del os.environ["USPTO_API_KEY"]

    return all_passed

def test_error_handling_with_placeholders():
    """Test that placeholder detection works in the full error handling flow"""

    print("Testing error handling with placeholder keys...")

    # Save original env vars
    original_mistral = os.getenv("MISTRAL_API_KEY")
    original_uspto = os.getenv("USPTO_API_KEY")

    try:
        # Set placeholder keys
        os.environ["MISTRAL_API_KEY"] = "your_mistral_api_key_here_OPTIONAL"
        os.environ["USPTO_API_KEY"] = "test_key_for_validation"  # We need this for client creation

        # Create client
        client = EnhancedPatentClient()

        # Verify the placeholder was detected and removed
        if client.mistral_api_key is None:
            print("PASS - Placeholder key correctly treated as missing")
            print("    This means users who copy-paste config will get helpful error messages")
            print("    instead of authentication failures from Mistral API")
            return True
        else:
            print("FAIL - Placeholder key was not detected")
            print(f"    Client still has key: {repr(client.mistral_api_key)}")
            return False

    finally:
        # Restore original env vars
        if original_mistral is not None:
            os.environ["MISTRAL_API_KEY"] = original_mistral
        elif "MISTRAL_API_KEY" in os.environ:
            del os.environ["MISTRAL_API_KEY"]

        if original_uspto is not None:
            os.environ["USPTO_API_KEY"] = original_uspto
        elif "USPTO_API_KEY" in os.environ:
            del os.environ["USPTO_API_KEY"]

def main():
    """Run all placeholder detection tests"""

    print("=" * 60)
    print("PLACEHOLDER API KEY DETECTION TEST SUITE")
    print("=" * 60)

    # Test 1: Basic placeholder detection
    test1_passed = test_placeholder_detection()

    print("\n" + "=" * 60)

    # Test 2: Integration with error handling
    test2_passed = test_error_handling_with_placeholders()

    print("\n" + "=" * 60)

    if test1_passed and test2_passed:
        print("ALL TESTS PASSED!")
        print("\nBenefits implemented:")
        print("- Users can copy-paste config without changing placeholder text")
        print("- System provides helpful guidance instead of API authentication errors")
        print("- Common placeholder patterns are automatically detected")
        print("- Very short suspicious keys are flagged")
        return True
    else:
        print("SOME TESTS FAILED")
        print("Please check the implementation.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
