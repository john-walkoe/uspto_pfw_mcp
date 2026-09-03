"""Cross-repo compatibility for S-06 / PT-14: PTAB and FPD's own
`shared/internal_auth.py` copies must keep minting tokens PFW's verifier
accepts, on either side of the fleet-wide rotation rollout (a sibling not yet
rolled to the HKDF-derived scheme signs "legacy" tokens with no key_id; PFW's
verifier has to accept those too — see internal_auth.py's
`_signature_matches_any_root`).

Skips per-sibling when that checkout is not present on this box (fleet
agents may run against a partial checkout).
"""

import importlib
import sys
from pathlib import Path

import pytest

from patent_filewrapper_mcp.shared.internal_auth import InternalAuthToken

_SECRET = "cross-repo-compat-test-secret-value"

# Repo root is this file's grandparent (tests/ -> uspto_pfw_mcp/); the sibling
# MCP repos are expected to be checked out alongside it in the same parent
# directory. When they are not, these checks skip.
_SIBLING_CHECKOUT_ROOT = Path(__file__).resolve().parent.parent.parent

_SIBLINGS = {
    "ptab-mcp": _SIBLING_CHECKOUT_ROOT
    / "uspto_ptab_mcp" / "src" / "ptab_mcp" / "shared" / "internal_auth.py",
    "fpd-mcp": _SIBLING_CHECKOUT_ROOT
    / "uspto_fpd_mcp" / "src" / "fpd_mcp" / "shared" / "internal_auth.py",
}


def _load_sibling_module(service_name: str, path: Path):
    """Import a sibling's shared/internal_auth.py, located by file path, as
    a real package member (not a bare exec) so its own relative imports
    (`from .safe_logger import ...`) resolve."""
    src_dir = str(path.parent.parent.parent)  # .../uspto_x_mcp/src
    package_name = path.parent.parent.name  # ptab_mcp / fpd_mcp
    module_name = f"{package_name}.shared.internal_auth"

    inserted = src_dir not in sys.path
    if inserted:
        sys.path.insert(0, src_dir)
    try:
        sys.modules.pop(module_name, None)
        return importlib.import_module(module_name)
    finally:
        if inserted:
            sys.path.remove(src_dir)


@pytest.mark.parametrize("service_name", sorted(_SIBLINGS))
def test_a_sibling_minted_token_verifies_against_pfw(service_name):
    path = _SIBLINGS[service_name]
    if not path.exists():
        pytest.skip(f"sibling checkout not present: {path}")

    sibling_module = _load_sibling_module(service_name, path)
    sibling_issuer = sibling_module.InternalAuthToken(_SECRET)
    token = sibling_issuer.create_token(
        service_name, metadata={"document_id": "doc-1", "type": "document_access"}
    )

    verifier = InternalAuthToken(_SECRET)
    valid, payload = verifier.validate_token(token, expected_service=service_name)

    assert valid is True
    assert payload["service"] == service_name
