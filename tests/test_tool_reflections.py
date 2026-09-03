#!/usr/bin/env python3
"""Tool guidance is present for the tools that need it.

This file used to import `get_all_tool_reflections` / `get_tool_reflection`
from `config/tool_reflections.py`. Those functions were DELETED when the
guidance migrated to `PFW_get_guidance()` — the module is now a 22-line
migration notice — and this test kept passing anyway, because the resulting
ImportError landed in a bare `except Exception` that answered `return False`,
which pytest reports as PASS (audit T-4). Retargeted at the live API.
"""

import pytest

from patent_filewrapper_mcp.guidance import get_guidance_sections

#: The four tools the deleted reflections covered. Their guidance lives in the
#: `tools` section now.
_TOOLS_NEEDING_GUIDANCE = [
    "PFW_get_document_content_with_ocr",
    "PFW_get_document_download",
    "PFW_search_applications_balanced",
    "PFW_get_application_documents",
]

_REQUIRED_SECTIONS = ["overview", "tools", "workflows_pfw", "fields", "errors"]


def test_guidance_sections_are_loaded():
    assert get_guidance_sections(), "no guidance sections at all"


@pytest.mark.parametrize("section", _REQUIRED_SECTIONS)
def test_each_section_the_migration_notice_points_at_exists(section):
    """config/tool_reflections.py tells the reader to use these by name; a
    rename there would leave the notice pointing at nothing."""
    sections = get_guidance_sections()
    assert section in sections, f"guidance section {section!r} is missing"
    assert sections[section].strip(), f"guidance section {section!r} is empty"


@pytest.mark.parametrize("tool_name", _TOOLS_NEEDING_GUIDANCE)
def test_each_tool_appears_in_the_tools_guidance(tool_name):
    assert tool_name in get_guidance_sections()["tools"], (
        f"{tool_name} has no entry in the tools guidance section"
    )


def test_the_deprecated_reflections_module_exports_nothing_callable():
    """Pin the deletion so this test cannot silently target a ghost again."""
    from patent_filewrapper_mcp.config import tool_reflections

    assert not hasattr(tool_reflections, "get_all_tool_reflections")
    assert not hasattr(tool_reflections, "get_tool_reflection")
