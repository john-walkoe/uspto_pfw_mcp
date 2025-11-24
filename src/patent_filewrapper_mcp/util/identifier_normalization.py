"""
Identifier normalization utilities for USPTO Patent File Wrapper MCP

Handles the critical bug where ambiguous identifiers like "11752072" can be
interpreted as either patent numbers or application numbers by the USPTO API.

This module provides smart identifier normalization and resolution to ensure
correct search queries and document retrieval.
"""

import re
import logging
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

from ..models.constants import IdentifierType

logger = logging.getLogger(__name__)


@dataclass
class IdentifierInfo:
    """
    Structured information about a normalized identifier
    """
    original_input: str
    cleaned_value: str
    identifier_type: str  # "application", "patent", "publication", "unknown"
    search_query: str
    app_number_for_docs: Optional[str]
    confidence: str  # "high", "medium", "low"
    notes: str


def normalize_identifier(user_input: str) -> IdentifierInfo:
    """
    Smart identifier normalization for USPTO API

    Critical fix for the bug where "11752072" could be interpreted as:
    - Application number format (post-2001): 16816197
    - Patent number format: 11752072

    When collision exists, USPTO API may return patent number match instead
    of intended application number search.

    Args:
        user_input: Various formats like "11752072", "11/752,072", "7971071",
                   "US 7,971,071", "20080141381", etc.

    Returns:
        IdentifierInfo with normalized search query and metadata
    """
    # Clean input - remove common prefixes, spaces, punctuation
    cleaned = user_input.strip().upper()
    cleaned = re.sub(r'^(US|USPTO)\s*', '', cleaned)  # Remove US prefix

    # Remove patent kind codes (A1, A2, B1, B2, C1, E1, H1, P1, P2, P3, P4, S1, etc.)
    # These appear at the END of patent numbers like "7971071B2"
    # Must remove BEFORE general character removal to avoid keeping the digit
    cleaned = re.sub(r'\s*[A-Z]\d+\s*$', '', cleaned)

    cleaned = re.sub(r'[^\d/,]', '', cleaned)  # Keep only digits, slashes, commas

    # Additional cleaning for patent numbers with formatting
    cleaned = cleaned.replace(',', '')  # Remove commas from patent numbers like "7,971,071"

    # Pattern matching for different identifier types

    # 1. Pre-2001 application format with slash: "11/752,072" or "11/752072"
    if '/' in cleaned:
        # This is definitely an application number
        # Format: XX/XXX,XXX or XX/XXXXXX
        # API wants numbers WITHOUT slashes, so clean them out
        cleaned_no_slash = cleaned.replace("/", "").replace(",", "")
        return IdentifierInfo(
            original_input=user_input,
            cleaned_value=cleaned_no_slash,
            identifier_type="application",
            search_query=f'applicationNumberText:{cleaned_no_slash}',  # NO quotes, NO slashes
            app_number_for_docs=cleaned_no_slash,
            confidence="high",
            notes="Pre-2001 application format with slash - unambiguous (slashes removed for API)"
        )

    # 2. Publication number format: Usually 8-11 digits starting with 2
    elif cleaned.startswith('2') and len(cleaned) in [8, 9, 10, 11]:
        return IdentifierInfo(
            original_input=user_input,
            cleaned_value=cleaned,
            identifier_type="publication",
            search_query=f"publicationNumber:{cleaned}",
            app_number_for_docs=None,  # Will extract from search result
            confidence="high",
            notes="Publication number format detected"
        )

    # 3. Clear patent number: 7 digits or less, typically < 12000000
    elif cleaned.isdigit() and len(cleaned) <= 7:
        return IdentifierInfo(
            original_input=user_input,
            cleaned_value=cleaned,
            identifier_type="patent",
            search_query=f"patentNumber:{cleaned}",
            app_number_for_docs=None,  # Will extract from search result
            confidence="high",
            notes="Patent number format (7 digits or less)"
        )

    # 4. AMBIGUOUS CASE: 8 digits in the danger zone (could be either)
    elif cleaned.isdigit() and len(cleaned) == 8:
        # This is the critical bug case!
        # Numbers like "11752072" could be either:
        # - Application number (series 08-17+: 08000000-17999999+)
        # - Patent number (currently ~11.5M issued max)

        # Heuristic based on USPTO application series:
        # Series 08-11 (pre-2001): 08000000-11999999
        # Series 12+ (2001+): 12000000+
        # Patents: Currently max ~11.5M
        # Numbers >= 08000000 (8M) are likely applications
        if int(cleaned) < 8000000:
            return IdentifierInfo(
                original_input=user_input,
                cleaned_value=cleaned,
                identifier_type="patent",
                search_query=f"applicationMetaData.patentNumber:{cleaned}",
                app_number_for_docs=None,
                confidence="high",
                notes="8-digit number < 8M - likely patent number (max ~11.5M patents issued)"
            )
        else:
            return IdentifierInfo(
                original_input=user_input,
                cleaned_value=cleaned,
                identifier_type="application",
                search_query=f"applicationNumberText:{cleaned}",
                app_number_for_docs=cleaned,
                confidence="high",
                notes="8-digit number >= 8M - likely application number (series 08-17+)"
            )

    # 6. Long numbers: Likely application numbers
    elif cleaned.isdigit() and len(cleaned) > 8:
        return IdentifierInfo(
            original_input=user_input,
            cleaned_value=cleaned,
            identifier_type="application",
            search_query=f"applicationNumberText:{cleaned}",
            app_number_for_docs=cleaned,
            confidence="medium",
            notes="Long number format - likely application number"
        )

    # 7. Fallback: Unknown format
    else:
        return IdentifierInfo(
            original_input=user_input,
            cleaned_value=cleaned,
            identifier_type="unknown",
            search_query=f'"{cleaned}"',  # Generic search
            app_number_for_docs=None,
            confidence="low",
            notes="Unknown format - will try generic search. Consider using /patent_search for better results."
        )


async def resolve_identifier_to_application_number(
    identifier_info: IdentifierInfo,
    search_function
) -> Tuple[Optional[str], str]:
    """
    Resolve any identifier type to an application number for document access

    Args:
        identifier_info: Result from normalize_identifier()
        search_function: The pfw_search_applications_minimal function

    Returns:
        Tuple of (application_number, status_message)
    """
    if identifier_info.identifier_type == IdentifierType.APPLICATION and identifier_info.app_number_for_docs:
        # Already have application number
        return identifier_info.app_number_for_docs, "Direct application number"

    try:
        # Need to search to find application number
        search_result = await search_function(
            query=identifier_info.search_query,
            limit=1
        )

        if not search_result.get('success') or not search_result.get('applications'):
            return None, f"No results found for {identifier_info.original_input}"

        # Extract application number from first result
        app_data = search_result['applications'][0]
        app_number = app_data.get('applicationNumberText')

        if not app_number:
            return None, "Application number not found in search result"

        # Log the resolution for debugging
        logger.info(f"Resolved {identifier_info.original_input} -> {app_number}")

        return app_number, f"Resolved {identifier_info.identifier_type} to application number"

    except Exception as e:
        logger.error(f"Failed to resolve identifier {identifier_info.original_input}: {e}")
        return None, f"Search failed: {str(e)}"


def create_identifier_guidance(identifier_info: IdentifierInfo) -> Dict[str, str]:
    """
    Generate user-friendly guidance about identifier interpretation
    """
    guidance = {
        "interpretation": f"Interpreted as {identifier_info.identifier_type} number",
        "confidence": identifier_info.confidence,
        "notes": identifier_info.notes
    }

    if identifier_info.confidence == "medium":
        guidance["recommendation"] = (
            "If results don't match what you expected, try the /patent_search template "
            "with additional information like inventor name or technology keywords"
        )

    if identifier_info.identifier_type == "unknown":
        guidance["recommendation"] = (
            "Unknown identifier format. Consider using /patent_search template "
            "for fuzzy search with partial information"
        )

    return guidance


# Test cases for validation
TEST_CASES = [
    # Clear cases
    ("7971071", "patent", "high"),
    ("16816197", "application", "high"),  # 8-digit number >= 8M (series 16)
    ("11/752,072", "application", "high"),
    ("20080141381", "publication", "high"),

    # Application number cases (series 08-17+)
    ("11752072", "application", "high"),  # Series 11 application >= 8M
    ("14104993", "application", "high"),  # Series 14 application >= 8M
    ("08123456", "application", "high"),  # Series 08 application >= 8M

    # Patent kind codes (suffixes like B2, A1)
    ("US7971071B2", "patent", "high"),  # Granted patent with B2 suffix
    ("US 7,971,071 B2", "patent", "high"),  # With spaces
    ("7971071A1", "patent", "high"),  # Published application A1 suffix
    ("11752072B1", "application", "high"),  # Application number with suffix (uncommon)

    # Edge cases
    ("US 7,971,071", "patent", "high"),
    ("07999999", "patent", "high"),  # Just below 8M threshold - patent
    ("08000000", "application", "high"),  # At 8M threshold - application
]


def run_identifier_tests() -> bool:
    """
    Run test cases to validate identifier normalization

    Returns:
        True if all tests pass
    """
    all_passed = True

    for test_input, expected_type, expected_confidence in TEST_CASES:
        result = normalize_identifier(test_input)

        if result.identifier_type != expected_type:
            logger.error(f"FAIL: {test_input} -> expected {expected_type}, got {result.identifier_type}")
            all_passed = False
        elif result.confidence != expected_confidence:
            logger.warning(f"CONFIDENCE DIFF: {test_input} -> expected {expected_confidence}, got {result.confidence}")
        else:
            logger.info(f"PASS: {test_input} -> {result.identifier_type} ({result.confidence})")

    return all_passed
