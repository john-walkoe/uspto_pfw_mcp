"""Registration gate for pfw_manage_users (audit H1).

The tool must be absent from the registered tool set unless
PFW_ENABLE_USER_MANAGEMENT=true (default off — stdio never needs it and
non-OAuth HTTP would expose it behind only the shared INTERNAL_AUTH_SECRET).

Registration happens at import time, so each state runs in a subprocess.
"""

import os
import subprocess
import sys

_PROBE = (
    "from patent_filewrapper_mcp.main import mcp\n"
    "from fastmcp.tools.base import Tool\n"
    "names = [c.name for c in mcp.local_provider._components.values()"
    " if isinstance(c, Tool)]\n"
    "print('PRESENT' if 'pfw_manage_users' in names else 'ABSENT')\n"
)


def _probe(extra_env: dict) -> str:
    env = {**os.environ, **extra_env}
    env.pop("PFW_ENABLE_USER_MANAGEMENT", None)
    env.update(extra_env)
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True, text=True, env=env, timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return result.stdout.strip().splitlines()[-1]


def test_manage_users_absent_by_default():
    assert _probe({}) == "ABSENT"


def test_manage_users_registered_when_enabled():
    assert _probe({"PFW_ENABLE_USER_MANAGEMENT": "true"}) == "PRESENT"
