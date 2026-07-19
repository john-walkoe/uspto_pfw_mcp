"""Test _safe_filename — the production bug fix for dot-stripping."""
from patent_filewrapper_mcp.proxy.server import _safe_filename


class TestSafeFilename:
    def test_dot_preserved_drwpdf(self):
        """DRW.pdf must not become DRW_pdf.pdf — this was the production bug."""
        result = _safe_filename("DRW.pdf")
        assert result == "DRW.pdf", f"Expected 'DRW.pdf', got '{result}'"

    def test_spaces_preserved(self):
        """Spaces in filenames are OK — spaces pass through."""
        result = _safe_filename("document name.pdf")
        assert ".pdf" in result.lower()
        assert result.lower().endswith(".pdf")

    def test_path_traversal_blocked(self):
        """Path separators must be stripped — no ../../../etc/passwd."""
        result = _safe_filename("../../../etc/passwd")
        assert "/" not in result
        assert "\\" not in result

    def test_null_byte_replaced(self):
        """Control character \\x00 must be replaced."""
        result = _safe_filename("doc\x00name.pdf")
        assert "\x00" not in result
        assert ".pdf" in result.lower()

    def test_empty_string_returns_safe_value(self):
        """Empty string must not crash — returns safe fallback."""
        result = _safe_filename("")
        assert result != ""
        assert "\x00" not in result

    def test_none_returns_safe_value(self):
        """None must not crash — returns safe fallback."""
        result = _safe_filename(None)
        assert result is not None
        assert result != ""

    def test_special_chars_replaced(self):
        """Chars like : * ? \" < > | must be replaced."""
        result = _safe_filename('file:name*.pdf')
        assert ":" not in result
        assert "*" not in result
        assert ".pdf" in result.lower()

    def test_pdf_extension_intact(self):
        """Critical invariant: if input ends with .pdf (case-insensitive), result ends with .pdf."""
        for name in ["DRW.pdf", "doc.pdf", "file.pdf", "Document.Name.PDF"]:
            result = _safe_filename(name)
            assert result.lower().endswith(".pdf"), f"Input '{name}' -> '{result}' does not end with .pdf"

    def test_no_double_underscore(self):
        """Must not produce _pdf.pdf — the double-extension regression."""
        result = _safe_filename("DRW.pdf")
        assert not result.endswith("_pdf.pdf"), f"Double-extension regression: {result}"

    def test_extension_case_preserved(self):
        """Case of extension is preserved — .PDF stays .PDF, .pdf stays .pdf."""
        assert _safe_filename("DOC.PDF") == "DOC.PDF"
        assert _safe_filename("doc.pdf") == "doc.pdf"
