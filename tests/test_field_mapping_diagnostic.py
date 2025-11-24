#!/usr/bin/env python3
"""
Diagnostic test for field mapping to understand current behavior
"""
import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from patent_filewrapper_mcp.api.helpers import map_query_field_names
from patent_filewrapper_mcp.api.field_constants import USPTOFields

print("=" * 80)
print("FIELD MAPPING DIAGNOSTIC TEST")
print("=" * 80)
print()

# Test queries that should work
test_queries = [
    ("applicationNumberText:11752072", "Application number (top-level field)"),
    ("patentNumber:7971071", "Patent number (needs prefix)"),
    ("applicationMetaData.patentNumber:7971071", "Patent number (already prefixed)"),
    ("examinerNameText:SMITH", "Examiner name (needs prefix)"),
    ("inventionTitle:\"machine learning\"", "Title with quotes (needs prefix)"),
    ("patentNumber:7971071 AND examinerNameText:SMITH", "Complex query"),
]

print("Testing query field name mapping:")
print("-" * 80)
for query, description in test_queries:
    mapped = map_query_field_names(query)
    print(f"\n{description}:")
    print(f"  Input:  {query}")
    print(f"  Output: {mapped}")
    print(f"  Changed: {'Yes' if query != mapped else 'No'}")

print("\n" + "=" * 80)
print("FIELD CONSTANTS CHECK")
print("=" * 80)
print()
print(f"APPLICATION_NUMBER_TEXT = {USPTOFields.APPLICATION_NUMBER_TEXT}")
print(f"PATENT_NUMBER = {USPTOFields.PATENT_NUMBER}")
print(f"EXAMINER_NAME_TEXT = {USPTOFields.EXAMINER_NAME_TEXT}")
print(f"INVENTION_TITLE = {USPTOFields.INVENTION_TITLE}")

print("\n" + "=" * 80)
print("EXPECTED BEHAVIOR")
print("=" * 80)
print()
print("✓ applicationNumberText should NOT get prefix (top-level field)")
print("✓ patentNumber should become applicationMetaData.patentNumber")
print("✓ examinerNameText should become applicationMetaData.examinerNameText")
print("✓ Already-prefixed fields should pass through unchanged")
print()
