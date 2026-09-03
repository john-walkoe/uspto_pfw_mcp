"""Registration checks for the family and term-adjustment tools.

Registration happens at import time and pulls in the whole server module, so
it runs in a subprocess — same pattern as tests/test_prompts_gate.py.

Guards three things a refactor can silently break: the tools reach tools/list
under their exact public names, PFW_get_family carries its MCP App resource
URI, and the family app resource is actually registered (a tool pointing at an
unregistered ui:// URI renders nothing).
"""

import os
import subprocess
import sys

_PROBE = (
    "from patent_filewrapper_mcp.main import mcp\n"
    # fastmcp.tools.tool was a v3 sys.modules alias for .base, removed in
    # FastMCP 4. The package re-export resolves on both.
    "from fastmcp.tools import Tool\n"
    "comps = list(mcp.local_provider._components.values())\n"
    "tools = {c.name: c for c in comps if isinstance(c, Tool)}\n"
    "print('TOOLS:' + ','.join(sorted(tools)))\n"
    "def ui_uri(name):\n"
    "    meta = getattr(tools.get(name), 'meta', None) or {}\n"
    "    return (meta.get('ui') or {}).get('resourceUri', '')\n"
    "print('FAMILY_URI:' + ui_uri('PFW_get_family'))\n"
    "print('TERM_URI:' + ui_uri('PFW_get_term_adjustment'))\n"
    "print('RESOURCES:' + ','.join(sorted(str(getattr(c, 'uri', '')) for c in comps)))\n"
)


def _probe() -> dict:
    env = {**os.environ}
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True, text=True, env=env, timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    out = {}
    for line in result.stdout.strip().splitlines():
        if ":" in line and line.split(":", 1)[0].isupper():
            key, value = line.split(":", 1)
            out[key] = value
    return out


def test_family_and_term_tools_are_registered():
    probe = _probe()
    names = probe["TOOLS"].split(",")

    assert "PFW_get_family" in names
    assert "PFW_get_term_adjustment" in names
    # The pre-existing roster must survive the addition.
    for existing in (
        "PFW_search_applications_minimal",
        "PFW_get_application_documents",
        "PFW_get_guidance",
        "PFW_get_oa_text",
    ):
        assert existing in names


def test_family_tool_declares_its_app_resource_uri():
    probe = _probe()

    assert probe["FAMILY_URI"] == "ui://pfw/family-view.html"
    # The view resource must exist, or the tool points at nothing.
    assert "ui://pfw/family-view.html" in probe["RESOURCES"]
    # PFW_get_term_adjustment deliberately has no MCP App view.
    assert probe["TERM_URI"] == ""


def test_family_guidance_section_is_served():
    from patent_filewrapper_mcp.guidance import get_guidance_sections

    sections = get_guidance_sections()
    assert "family" in sections

    family = sections["family"]
    assert "PFW_get_family" in family
    assert "PFW_get_term_adjustment" in family
    # The two claims the section exists to carry.
    assert "not missing data" in family
    assert "No expiration date is computed" in family

    assert "All 16 PFW MCP Tools" in sections["tools"]
    # Search-scope honesty lives in the fields section.
    assert "bibliographic" in sections["fields"]
    assert "cpcClassificationBag" in sections["fields"]
