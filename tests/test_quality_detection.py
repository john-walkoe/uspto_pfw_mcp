#!/usr/bin/env python3
"""Test quality detection logic without requiring API keys"""

import sys
from pathlib import Path

# Add the src directory to the path
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

def is_good_extraction(text: str) -> bool:
    """
    Determine if PyPDF2 extraction is usable.
    
    Criteria for "good" extraction:
    - Not empty or whitespace-only
    - Contains reasonable amount of text (>50 chars)
    - Contains readable words (not just symbols/garbage)
    - Has reasonable word-to-character ratio
    """
    
    if not text or len(text.strip()) < 50:
        return False
    
    # Check for reasonable word content
    words = text.split()
    if len(words) < 10:  # Very short extractions are probably garbage
        return False
    
    # Check character-to-word ratio (catch symbol/garbage extractions)
    avg_word_length = len(text) / len(words)
    if avg_word_length > 20:  # Probably garbage characters
        return False
    
    # Check for English-like content (basic heuristic)
    alpha_chars = sum(1 for c in text if c.isalpha())
    alpha_ratio = alpha_chars / len(text)
    if alpha_ratio < 0.6:  # Less than 60% alphabetic = probably scanned/garbage
        return False
    
    return True

def test_quality_detection():
    """Test the quality detection logic"""
    print("Testing Quality Detection Logic")
    print("=" * 40)
    
    test_cases = [
        ("Good patent text", "This is a patent application for a secure hardware adjunct that provides authentication services and cryptographic operations", True),
        ("Empty text", "", False),
        ("Short text", "ABC", False),
        ("Whitespace only", "   \n\t  ", False),
        ("Garbage symbols", "㟁㟂㟃㟄㟅㟆㟇㟈㟉㟊㟋㟌㟍㟎㟏㟐㟑㟒㟓㟔㟕㟖㟗㟘㟙㟚㟛㟜㟝㟞㟟", False),
        ("Symbol noise", "###$$$%%%^^^&&&***((()))!!!", False),
        ("Mixed good text", "The invention relates to secure cryptographic methods using 256-bit encryption algorithms for hardware security modules", True),
        ("Technical patent", "A method for implementing secure boot processes in embedded systems comprising authentication of firmware images", True),
        ("Too short words", "a b c d e f g h i j k l m n o p q r", False),  # Many short words
        ("Long nonsense", "averylongwordwithoutspacesormeaning" * 5, False),  # Bad word ratio
    ]
    
    passed = 0
    total = len(test_cases)
    
    for name, text, expected in test_cases:
        result = is_good_extraction(text)
        status = "PASS" if result == expected else "FAIL"
        print(f"{status}: {name} -> {result} (expected {expected})")
        if result == expected:
            passed += 1
    
    print(f"\nResults: {passed}/{total} tests passed")
    return passed == total

if __name__ == "__main__":
    success = test_quality_detection()
    if success:
        print("\nAll quality detection tests passed!")
    else:
        print("\nSome quality detection tests failed!")
        sys.exit(1)