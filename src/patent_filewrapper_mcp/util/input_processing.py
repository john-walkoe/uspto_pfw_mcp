"""
Enhanced input processing utilities for USPTO Patent File Wrapper MCP

Provides flexible, user-friendly input handling for prompt templates based on
Claude Desktop testing feedback. Supports multiple identifier formats with
smart validation and processing.
"""

import re
import logging
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass

from ..models.constants import TechnologyKeyword

logger = logging.getLogger(__name__)


@dataclass
class ProcessedInput:
    """
    Result of processing user inputs through the enhanced parameter system
    """
    identifier_type: str  # "patent", "application", "title_keywords"
    resolved_identifier: str  # The identifier to use for search
    search_strategy: str  # "direct_lookup", "fuzzy_search"
    search_query: str  # The actual query to execute
    confidence: str  # "high", "medium", "low"
    user_guidance: str  # Message to show user about what was processed
    fallback_needed: bool = False  # Whether fuzzy search fallback is needed


def validate_inputs(
    patent_number: str = "",
    application_number: str = "",
    title_keywords: str = ""
) -> bool:
    """
    Validate that at least one identifier field is provided.

    Args:
        patent_number: US patent number (optional)
        application_number: Application number (optional)
        title_keywords: Keywords from patent title (optional)

    Returns:
        True if validation passes

    Raises:
        ValueError: If no identifier provided with helpful guidance
    """
    # Clean inputs to check for actual content
    clean_patent = patent_number.strip() if patent_number else ""
    clean_app = application_number.strip() if application_number else ""
    clean_keywords = title_keywords.strip() if title_keywords else ""

    if not clean_patent and not clean_app and not clean_keywords:
        raise ValueError(
            "Please provide at least one identifier:\n"
            "• Patent Number (e.g., '7971071' or '7,971,071')\n"
            "• Application Number (e.g., '11752072' or '11/752,072')\n"
            "• Title Keywords (e.g., 'digital rights management')\n\n"
            "Example usage:\n"
            "- Patent lookup: patent_number='7971071'\n"
            "- App lookup: application_number='11/752,072'\n"
            "- Fuzzy search: title_keywords='wireless charging device'"
        )

    return True


def clean_patent_number(patent_number: str) -> str:
    """
    Clean patent number input by removing formatting characters.

    Args:
        patent_number: Raw patent number input

    Returns:
        Cleaned patent number (digits only)

    Examples:
        "7,971,071" → "7971071"
        "US 7971071" → "7971071"
        "7-971-071" → "7971071"
    """
    if not patent_number:
        return ""

    # Remove common prefixes and formatting
    cleaned = patent_number.strip().upper()
    cleaned = re.sub(r'^(US|USPTO)\s*', '', cleaned)  # Remove US prefix
    cleaned = re.sub(r'[^\d]', '', cleaned)  # Keep only digits

    return cleaned


def clean_application_number(application_number: str) -> Tuple[str, str]:
    """
    Clean application number and return both formatted and raw versions.

    Args:
        application_number: Raw application number input

    Returns:
        Tuple of (formatted_for_search, raw_for_docs)

    Examples:
        "11/752,072" → ("11/752,072", "11752072")
        "11752072" → ("11752072", "11752072")
        "11-752-072" → ("11/752/072", "11752072")
    """
    if not application_number:
        return "", ""

    cleaned = application_number.strip().replace(" ", "")

    # If it contains slash, preserve the format for search
    if "/" in cleaned:
        # Remove extra commas but preserve slash structure
        formatted = cleaned.replace(",", "")
        raw = re.sub(r'[^\d]', '', cleaned)  # Digits only for docs
        return formatted, raw

    # If it's all digits, check if it should have slash format
    digits_only = re.sub(r'[^\d]', '', cleaned)
    if len(digits_only) == 8 and int(digits_only) < 15000000:
        # Likely a pre-2001 application number, try to format it
        # Format as XX/XXX,XXX if 8 digits and < 15M
        if len(digits_only) >= 5:
            formatted_slash = f"{digits_only[:2]}/{digits_only[2:]}"
            return formatted_slash, digits_only

    # Return as-is for modern application numbers
    return digits_only, digits_only


def clean_title_keywords(title_keywords: str) -> str:
    """
    Clean and validate title keywords for fuzzy search.

    Args:
        title_keywords: Raw title keywords input

    Returns:
        Cleaned keywords string

    Raises:
        ValueError: If keywords are too short or too long
    """
    if not title_keywords:
        return ""

    cleaned = title_keywords.strip()

    # Basic validation
    if len(cleaned) < 3:
        raise ValueError(
            "Title keywords must be at least 3 characters long.\n"
            "Examples: 'wireless', 'digital rights', 'charging device'"
        )

    if len(cleaned) > 200:
        raise ValueError(
            "Title keywords must be 200 characters or less to prevent massive searches.\n"
            "Try using more specific keywords."
        )

    return cleaned


def process_identifier_inputs(
    patent_number: str = "",
    application_number: str = "",
    title_keywords: str = ""
) -> ProcessedInput:
    """
    Process multiple identifier inputs and create smart search strategy.

    Priority order:
    1. Patent number (most specific, direct lookup)
    2. Application number (direct lookup)
    3. Title keywords (fuzzy search via patent_search)

    Args:
        patent_number: US patent number (optional)
        application_number: Application number (optional)
        title_keywords: Keywords from patent title (optional)

    Returns:
        ProcessedInput with search strategy and guidance

    Raises:
        ValueError: If validation fails
    """
    # First validate that at least one field is provided
    validate_inputs(patent_number, application_number, title_keywords)

    # Priority 1: Patent Number (highest priority)
    if patent_number and patent_number.strip():
        clean_patent = clean_patent_number(patent_number)

        if not clean_patent:
            raise ValueError(
                f"Invalid patent number format: '{patent_number}'\n"
                "Examples: '7971071', '7,971,071', 'US 7971071'"
            )

        return ProcessedInput(
            identifier_type="patent",
            resolved_identifier=clean_patent,
            search_strategy="direct_lookup",
            search_query=f"patentNumber:{clean_patent}",
            confidence="high",
            user_guidance=f"Using patent number {clean_patent} for direct lookup"
        )

    # Priority 2: Application Number
    elif application_number and application_number.strip():
        formatted_app, raw_app = clean_application_number(application_number)

        if not raw_app:
            raise ValueError(
                f"Invalid application number format: '{application_number}'\n"
                "Examples: '11752072', '11/752,072', '16816197'"
            )

        # Use the existing identifier normalization for the search query
        from .identifier_normalization import normalize_identifier
        identifier_info = normalize_identifier(formatted_app)

        return ProcessedInput(
            identifier_type="application",
            resolved_identifier=raw_app,
            search_strategy="direct_lookup",
            search_query=identifier_info.search_query,
            confidence=identifier_info.confidence,
            user_guidance=f"Using application number {formatted_app} for direct lookup ({identifier_info.confidence} confidence)"
        )

    # Priority 3: Title Keywords (fuzzy search)
    elif title_keywords and title_keywords.strip():
        clean_keywords = clean_title_keywords(title_keywords)

        return ProcessedInput(
            identifier_type="title_keywords",
            resolved_identifier=clean_keywords,
            search_strategy="fuzzy_search",
            search_query=clean_keywords,  # Will be processed by patent_search
            confidence="medium",
            user_guidance=f"Using title keywords '{clean_keywords}' for fuzzy search",
            fallback_needed=True
        )

    else:
        # This should never happen due to validate_inputs, but just in case
        raise ValueError("No valid identifier provided")


def create_fuzzy_search_strategy(title_keywords: str) -> Dict[str, Any]:
    """
    Create a structured strategy for fuzzy search based on title keywords.

    Args:
        title_keywords: Cleaned title keywords

    Returns:
        Dictionary with search strategy parameters
    """
    keywords = title_keywords.lower().strip()

    # Extract potential search patterns
    search_strategy = {
        "primary_keywords": keywords,
        "search_type": "title_based",
        "suggested_limit": 20,  # Start with reasonable limit
        "search_params": {
            "query": keywords,
            "fields": "minimal",  # Use minimal fields for discovery
            "limit": 20
        }
    }

    # Add specific strategies based on keyword patterns
    if any(word in keywords for word in ["system", "method", "device", "apparatus"]):
        search_strategy["search_type"] = "technical_invention"
        search_strategy["suggested_limit"] = 30

    if any(word in keywords for word in [TechnologyKeyword.WIRELESS, TechnologyKeyword.DIGITAL,
                                          TechnologyKeyword.ELECTRONIC, TechnologyKeyword.COMPUTER]):
        search_strategy["search_type"] = "technology_focused"
        search_strategy["suggested_limit"] = 25

    return search_strategy


def format_input_guidance(processed_input: ProcessedInput) -> str:
    """
    Generate user-friendly guidance about how the input was processed.

    Args:
        processed_input: Result from process_identifier_inputs

    Returns:
        Formatted guidance string for user
    """
    base_message = f"✅ {processed_input.user_guidance}"

    if processed_input.search_strategy == "direct_lookup":
        if processed_input.identifier_type == "patent":
            base_message += "\n📋 Will retrieve complete patent information and resolve to application number for document access."
        else:
            base_message += "\n📋 Will retrieve application information and proceed with document package."

    elif processed_input.search_strategy == "fuzzy_search":
        base_message += (
            "\n🔍 Will search for patents matching your keywords and present options for selection.\n"
            "💡 Tip: If results aren't quite right, you can refine the search or provide a patent/application number."
        )

    if processed_input.confidence == "medium":
        base_message += "\n⚠️ Medium confidence - if results don't match expectations, try using patent_search with additional details."

    return base_message


# Test cases for the enhanced input processing
TEST_CASES = [
    # Patent number variations
    {
        "inputs": {"patent_number": "7971071"},
        "expected_type": "patent",
        "expected_strategy": "direct_lookup"
    },
    {
        "inputs": {"patent_number": "7,971,071"},
        "expected_type": "patent",
        "expected_strategy": "direct_lookup"
    },
    {
        "inputs": {"patent_number": "US 7971071"},
        "expected_type": "patent",
        "expected_strategy": "direct_lookup"
    },

    # Application number variations
    {
        "inputs": {"application_number": "11752072"},
        "expected_type": "application",
        "expected_strategy": "direct_lookup"
    },
    {
        "inputs": {"application_number": "11/752,072"},
        "expected_type": "application",
        "expected_strategy": "direct_lookup"
    },
    {
        "inputs": {"application_number": "16816197"},
        "expected_type": "application",
        "expected_strategy": "direct_lookup"
    },

    # Title keywords
    {
        "inputs": {"title_keywords": "digital rights management"},
        "expected_type": "title_keywords",
        "expected_strategy": "fuzzy_search"
    },
    {
        "inputs": {"title_keywords": "wireless charging device"},
        "expected_type": "title_keywords",
        "expected_strategy": "fuzzy_search"
    },

    # Priority testing (should use patent number)
    {
        "inputs": {
            "patent_number": "7971071",
            "application_number": "11752072",
            "title_keywords": "digital rights"
        },
        "expected_type": "patent",
        "expected_strategy": "direct_lookup"
    },

    # Priority testing (should use app number when patent empty)
    {
        "inputs": {
            "patent_number": "",
            "application_number": "11752072",
            "title_keywords": "digital rights"
        },
        "expected_type": "application",
        "expected_strategy": "direct_lookup"
    }
]


def run_input_processing_tests() -> bool:
    """
    Run test cases to validate the enhanced input processing.

    Returns:
        True if all tests pass
    """
    all_passed = True

    for i, test_case in enumerate(TEST_CASES):
        try:
            result = process_identifier_inputs(**test_case["inputs"])

            if result.identifier_type != test_case["expected_type"]:
                logger.error(f"Test {i+1} FAIL: Expected type {test_case['expected_type']}, got {result.identifier_type}")
                all_passed = False
            elif result.search_strategy != test_case["expected_strategy"]:
                logger.error(f"Test {i+1} FAIL: Expected strategy {test_case['expected_strategy']}, got {result.search_strategy}")
                all_passed = False
            else:
                logger.info(f"Test {i+1} PASS: {test_case['inputs']} -> {result.identifier_type} ({result.search_strategy})")

        except Exception as e:
            logger.error(f"Test {i+1} ERROR: {e}")
            all_passed = False

    # Test validation errors
    try:
        process_identifier_inputs("", "", "")
        logger.error("Validation test FAIL: Should have raised ValueError for empty inputs")
        all_passed = False
    except ValueError:
        logger.info("Validation test PASS: Correctly rejected empty inputs")

    return all_passed
