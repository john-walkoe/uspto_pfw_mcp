"""Vendored-module drift guard.

Each module below is hand-copied (not a package dependency) into every USPTO
MCP repo that needs it — no shared import path exists because there is no
shared package on PyPI, and the two-way `git subtree`/symlink alternatives
were rejected earlier for the same reason a straight file copy was chosen in
the first place (repo-specific constants stay OUT of the vendored file,
everything else is byte-identical). That means nothing enforces the copies
staying in sync except a human remembering to re-vendor, so this test pins
the md5 of this repo's copy of each module: if it drifts (an edit landed
here directly instead of at the canonical copy, or a re-vendor was missed)
CI goes red instead of the repos silently diverging.

This is exactly the guard that would have caught the `shared/response_bounds.py`
drift: PFW's copy pinned the pre-2026-08-30 `_window.unit` "page"/"char"
contract while PTAB moved on (`unit` always "char", the snapping fact moved
to a new `edges` key) and nothing noticed for four weeks and a full review
round — PFW's tests and guidance text (guidance.py, README.md, CLAUDE.md)
still asserted the old contract until this fix.

Canonical copies (edit at the canonical repo, then re-vendor byte-for-byte):
  - shared/response_bounds.py: **uspto_ptab_mcp is canonical.** Re-vendored
    FROM PTAB into this repo 2026-09-28 (md5 below); do not hand-edit this
    copy again — edit PTAB's and re-vendor.
  - shared/uspto_shared_rate_limiter.py, shared/uspto_hosts.py: the copy
    uspto_pfw_mcp / uspto_ptab_mcp / uspto_fpd_mcp already share
    byte-identical (uspto_enriched_citation_mcp's rate limiter is a DIVERGED
    copy missing the 30 s wait cap and must be re-vendored to match this
    one, not the reverse).

PFW does NOT vendor `shared/citations.py` or `shared/dpapi_crypto.py` (PTAB
and FPD share those with each other; PFW has its own `util/citation_links.py`
for citation links and a different at-rest-key architecture,
`shared/fernet_key_store.py` + `shared/internal_auth.py`), so they are not
pinned here.

Re-vendoring rule: `cp` the file across verbatim, then re-run this test (and
the sibling repo's own copy of it) to confirm the md5 landed.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

_SHARED_DIR = Path(__file__).resolve().parents[1] / "src" / "patent_filewrapper_mcp" / "shared"

# filename -> expected md5 hex digest of this repo's vendored copy.
_EXPECTED_MD5 = {
    "response_bounds.py": "ef54141d6eedba49ee801a15a5452679",
    "uspto_shared_rate_limiter.py": "a381d6cd21d2a6b4590fe2a54daf432b",  # 2026-10-13, PTAB ODP wave (slot-first, FIFO, cooldown)
    "uspto_hosts.py": "fd2e4902fdc1e9972b26e078dd9cf5bc",
}


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("filename, expected", sorted(_EXPECTED_MD5.items()))
def test_vendored_module_matches_recorded_md5(filename: str, expected: str) -> None:
    path = _SHARED_DIR / filename
    assert path.is_file(), f"vendored module missing: {path}"
    actual = _md5(path)
    assert actual == expected, (
        f"{filename} has drifted from its recorded md5 ({expected} -> "
        f"{actual}). If this edit was intentional, re-vendor it to every "
        "sharer named in this file's module docstring and update the "
        "constant here AND in each sibling repo's copy of this test."
    )
