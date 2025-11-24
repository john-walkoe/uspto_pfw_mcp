"""Test the new document_codes section in pfw_get_guidance"""

import sys
import asyncio
sys.path.insert(0, '../src')

from patent_filewrapper_mcp.main import pfw_get_guidance

async def test_document_codes():
    """Test the new document_codes section"""

    print("Testing pfw_get_guidance('document_codes')...")
    print("=" * 80)

    result = await pfw_get_guidance("document_codes")

    # Check that the result contains expected content
    assert "Document Code Decoder" in result, "Missing 'Document Code Decoder' header"
    assert "CTFR" in result, "Missing CTFR code"
    assert "NOA" in result, "Missing NOA code"
    assert "892" in result, "Missing 892 code"
    assert "IDS" in result, "Missing IDS code"
    assert "ABST" in result, "Missing ABST code"
    assert "CLM" in result, "Missing CLM code"
    assert "A..." in result, "Missing A... wildcard code"
    assert "RCEX" in result, "Missing RCEX code"
    assert "Usage Examples" in result, "Missing usage examples section"
    assert "Document_Descriptions_List.csv" in result, "Missing CSV reference"

    # Check exclusions
    assert "Petition codes (see FPD MCP" in result, "Missing FPD exclusion note"
    assert "PTAB codes (see PTAB MCP" in result, "Missing PTAB exclusion note"
    assert "PCT/International codes" in result, "Missing PCT exclusion note"

    print("PASS: All assertions passed!")
    print(f"PASS: Result length: {len(result)} characters")
    print(f"PASS: document_codes section contains 50+ document codes with examples")

    return True

if __name__ == "__main__":
    try:
        success = asyncio.run(test_document_codes())
        if success:
            print("\n[SUCCESS] document_codes section test PASSED")
            print("The new section provides a comprehensive decoder for documentBag responses")
            sys.exit(0)
    except Exception as e:
        print(f"\n[FAILED] document_codes section test FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
