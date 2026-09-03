"""
Identifier normalization utilities for USPTO Patent File Wrapper MCP

Handles the critical bug where ambiguous identifiers like "11752072" can be
interpreted as either patent numbers or application numbers by the USPTO API.

This module provides smart identifier normalization and resolution to ensure
correct search queries and document retrieval.
"""

import re
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

from ..models.constants import IdentifierType
from ..shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)


@dataclass
class IdentifierInfo:
    """
    Structured information about a normalized identifier
    """
    original_input: str
    cleaned_value: str
    identifier_type: str  # "application", "patent", "publication", "ambiguous", "unknown"
    search_query: str
    app_number_for_docs: Optional[str]
    confidence: str  # "high", "medium", "low"
    notes: str
    #: For an AMBIGUOUS 8-digit number: the second lane to try if the first
    #: (search_query) returns nothing. None for every unambiguous type.
    alternate_search_query: Optional[str] = None
    alternate_identifier_type: Optional[str] = None


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

    # 4. AMBIGUOUS CASE: 8 digits is BOTH a valid patent number and a valid
    #    application serial, at every value. No arithmetic threshold separates
    #    them, so none is applied.
    elif cleaned.isdigit() and len(cleaned) == 8:
        # The old rule typed any 8-digit number >= 8,000,000 as an application
        # serial. Patent numbers passed 12,000,000 in 2024, so every recent
        # grant was silently routed to `applicationNumberText:<n>` and came
        # back as an unrelated application (live-verified 2026-08-30:
        # "12539322" as a patent number is application 17996652, Nestle; as an
        # application serial it is 12/539,322, a Canon image sensor). Both
        # lanes are real, so the API decides, not a heuristic — see
        # util/identifier_resolution.resolve_identifier_lanes.
        return IdentifierInfo(
            original_input=user_input,
            cleaned_value=cleaned,
            identifier_type=IdentifierType.AMBIGUOUS,
            # Patent lane FIRST: an 8-digit value typed by a user is far more
            # often a patent number, and the application lane is the fallback.
            search_query=f"applicationMetaData.patentNumber:{cleaned}",
            app_number_for_docs=None,
            confidence="medium",
            notes=(
                "8-digit identifier is both a valid patent number and a valid "
                "application serial. Resolved against the API: "
                f"applicationMetaData.patentNumber:{cleaned} first, then "
                f"applicationNumberText:{cleaned}. Pass content_type='patent' or "
                "content_type='application' to force one lane."
            ),
            alternate_search_query=f"applicationNumberText:{cleaned}",
            alternate_identifier_type=IdentifierType.APPLICATION,
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
        search_function: The PFW_search_applications_minimal function

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
    ("11/752,072", "application", "high"),
    ("20080141381", "publication", "high"),

    # 8-digit bare numbers are AMBIGUOUS by construction (2026-08-30): each of
    # these is simultaneously a valid patent number and a valid application
    # serial, and only the API can say which one the caller meant.
    ("16816197", "ambiguous", "medium"),
    ("11752072", "ambiguous", "medium"),
    ("14104993", "ambiguous", "medium"),
    ("08123456", "ambiguous", "medium"),
    ("12539322", "ambiguous", "medium"),  # the reported miss: patent 12,539,322
    ("07999999", "ambiguous", "medium"),  # the old <8M patent branch
    ("08000000", "ambiguous", "medium"),  # the old >=8M application branch

    # Patent kind codes (suffixes like B2, A1)
    ("US7971071B2", "patent", "high"),  # Granted patent with B2 suffix
    ("US 7,971,071 B2", "patent", "high"),  # With spaces
    ("7971071A1", "patent", "high"),  # Published application A1 suffix
    ("11752072B1", "ambiguous", "medium"),  # 8 digits after the kind code

    # Edge cases
    ("US 7,971,071", "patent", "high"),
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
