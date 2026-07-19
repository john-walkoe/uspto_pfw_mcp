"""Test proxy token stability — verifies the production bug fix for token regeneration."""
import pytest
from patent_filewrapper_mcp.proxy.server import _get_proxy_token, _safe_filename


class TestProxyToken:
    def test_proxy_token_is_stable(self):
        """Token must be stable across calls — same value, not regenerated."""
        t1 = _get_proxy_token()
        t2 = _get_proxy_token()
        assert t1 == t2, f"Token changed between calls: '{t1}' vs '{t2}'"

    def test_proxy_token_sufficient_entropy(self):
        """token_urlsafe(32) yields 43 URL-safe chars. Reject anything shorter."""
        token = _get_proxy_token()
        assert len(token) >= 32, (
            f"Token too short ({len(token)} chars). "
            "Expected ≥32 from token_urlsafe(32)."
        )

    def test_proxy_token_is_urlsafe(self):
        """Token must be URL-safe base64 with no problematic chars."""
        token = _get_proxy_token()
        # URL-safe base64: no +, /, or = padding
        assert "+" not in token
        assert "/" not in token
        # Should decode cleanly
        import base64
        try:
            decoded = base64.urlsafe_b64decode(token + "==")
            assert len(decoded) >= 32
        except Exception:
            pytest.fail(f"Token '{token}' does not look like URL-safe base64")

    def test_main_uses_get_proxy_token_not_direct_generation(self):
        """Verify main.py imports and uses _get_proxy_token, not secrets.token_urlsafe directly.

        Production bug: if main.py generates a fresh token via secrets.token_urlsafe()
        separately from _get_proxy_token(), the proxy and MCP are out of sync and all
        /api/register-download calls return 401.
        """
        import inspect

        # Read main.py source
        from patent_filewrapper_mcp.tools import document_tools as main
        source = inspect.getsource(main)

        # Check _register_download_via_proxy function
        for name, obj in inspect.getmembers(main):
            if name == "_register_download_via_proxy":
                src = inspect.getsource(obj)
                # Must NOT call secrets.token_urlsafe directly
                assert "secrets.token_urlsafe" not in src, (
                    "FAIL: _register_download_via_proxy calls secrets.token_urlsafe() "
                    "directly — should use _get_proxy_token() instead. "
                    "This causes proxy token mismatch (production bug)."
                )
                # Must call _get_proxy_token
                assert "_get_proxy_token" in src, (
                    "FAIL: _register_download_via_proxy does not call _get_proxy_token(). "
                    "It must use the shared token getter."
                )
                return

        pytest.fail("_register_download_via_proxy not found in tools/document_tools.py")


class TestSafeFilename:
    """Sanity tests for filename sanitization (used by proxy routes)."""

    def test_dot_preserved_drwpdf(self):
        """DRW.pdf must not become DRW_pdf.pdf — this was the production bug."""
        result = _safe_filename("DRW.pdf")
        assert result == "DRW.pdf", f"Expected 'DRW.pdf', got '{result}'"

    def test_pdf_extension_intact(self):
        """Critical invariant: if input ends with .pdf (any case), result ends with .pdf."""
        for name in ["DRW.pdf", "DRW.PDF", "Document.Name.PDF"]:
            result = _safe_filename(name)
            assert result.lower().endswith(".pdf"), f"Input '{name}' -> '{result}'"

    def test_no_double_underscore(self):
        """Must not produce _pdf.pdf — the double-extension regression."""
        result = _safe_filename("DRW.pdf")
        assert not result.endswith("_pdf.pdf"), f"Double-extension regression: {result}"

    def test_path_traversal_blocked(self):
        """Path separators must be stripped."""
        result = _safe_filename("../../../etc/passwd")
        assert "/" not in result

    def test_empty_string_returns_safe_fallback(self):
        """Empty string must not crash."""
        result = _safe_filename("")
        assert result == "document.pdf"
