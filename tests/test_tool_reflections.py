#!/usr/bin/env python3
"""Simple test for tool reflections system"""

import sys
from pathlib import Path

# Add the src directory to the path
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

def test_tool_reflections():
    """Test the tool reflections system"""
    print("Testing Tool Reflections System")
    print("=" * 40)

    try:
        from patent_filewrapper_mcp.config.tool_reflections import (
            get_all_tool_reflections,
            get_tool_reflection
        )

        # Test 1: Check that reflections are loaded
        all_reflections = get_all_tool_reflections()
        print(f"Loaded {len(all_reflections)} tool reflections")

        # Test 2: Check specific tools exist
        tools_to_check = [
            "pfw_get_document_content",
            "pfw_get_document_download",
            "pfw_search_applications_balanced",
            "pfw_get_application_documents"
        ]

        for tool_name in tools_to_check:
            reflection = get_tool_reflection(tool_name)
            if reflection:
                print(f"PASS: {tool_name} reflection found")
            else:
                print(f"FAIL: {tool_name} reflection missing")
                return False

        # Test 3: Check Session 5 content
        content_tool = get_tool_reflection("pfw_get_document_content")
        if content_tool and 'session_5_enhancement' in content_tool:
            print("PASS: Session 5 enhancement documented")
        else:
            print("FAIL: Session 5 enhancement missing")
            return False

        # Test 4: Check download tool UX guidance
        download_tool = get_tool_reflection("pfw_get_document_download")
        if download_tool and 'critical_ux_requirement' in download_tool:
            print("PASS: Download tool UX requirements found")
        else:
            print("FAIL: Download tool UX requirements missing")
            return False

        print("\nAll tool reflection tests passed!")
        return True

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_tool_reflections()
    if not success:
        sys.exit(1)
