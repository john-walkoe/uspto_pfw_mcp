"""Registration gate for the MCP prompt templates.

The prompts must be absent from the registered prompt set unless
PFW_ENABLE_PROMPTS=true (default off — prompts are opt-in server-side).
Mirrors tests/test_user_management_gate.py.

Registration happens at import time, so each state runs in a subprocess.
"""

import os
import subprocess
import sys

_PROBE = (
    "from patent_filewrapper_mcp.main import mcp\n"
    # fastmcp.prompts.prompt was a v3 sys.modules alias for .base, removed in
    # FastMCP 4. The package re-export resolves on both.
    "from fastmcp.prompts import Prompt\n"
    "names = [c.name for c in mcp.local_provider._components.values()"
    " if isinstance(c, Prompt)]\n"
    "print('PRESENT' if names else 'ABSENT')\n"
)


def _probe(extra_env: dict) -> str:
    env = {**os.environ, **extra_env}
    env.pop("PFW_ENABLE_PROMPTS", None)
    env.update(extra_env)
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True, text=True, env=env, timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return result.stdout.strip().splitlines()[-1]


def test_prompts_absent_by_default():
    assert _probe({}) == "ABSENT"


def test_prompts_registered_when_enabled():
    assert _probe({"PFW_ENABLE_PROMPTS": "true"}) == "PRESENT"
