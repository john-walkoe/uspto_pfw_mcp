"""One doc-code parser, shared by the MCP resource and the HTTP endpoint.

There were two copies (audit D-1) and they had drifted in four ways, two of
them defects on the MCP-resource side: no markdown `|` escape and no FPD
bucket. Both copies also rebuilt their buckets outside the encoding-retry loop
while appending inside it, so a mid-file decode failure emitted duplicate rows.
"""

import inspect

import pytest

from patent_filewrapper_mcp.reference.doc_codes import (
    _clean,
    _parse_rows,
    build_doc_code_table,
    parse_doc_code_csv,
    render_doc_code_markdown,
)

_HEADER = ["CATEGORY", "DESCRIPTION", "BUSINESS PROCESS", "DOC CODE"]


def _rows(*data):
    return iter([_HEADER, *data])


class TestBucketing:
    def test_fpd_codes_get_their_own_bucket(self):
        """Missing on the MCP-resource path, so FPD codes were silently filed
        under 'Common Prosecution Document Codes'."""
        buckets = _parse_rows(
            _rows(["FPD Petitions", "Petition decision", "Petitions", "PET.DEC"])
        )
        assert [e["code"] for e in buckets["fpd"]] == ["PET.DEC"]
        assert buckets["prosecution"] == []

    def test_the_long_form_fpd_category_also_matches(self):
        buckets = _parse_rows(
            _rows(["Final Petition Decision", "A decision", "Petitions", "PDEC"])
        )
        assert [e["code"] for e in buckets["fpd"]] == ["PDEC"]

    def test_ptab_and_prosecution_still_split(self):
        buckets = _parse_rows(
            _rows(
                ["PTAB Trials", "Appeal brief", "Appeals", "AP.B"],
                ["Prosecution", "Claims", "Filing", "CLM"],
            )
        )
        assert [e["code"] for e in buckets["ptab"]] == ["AP.B"]
        assert [e["code"] for e in buckets["prosecution"]] == ["CLM"]

    def test_the_header_row_and_short_rows_are_skipped(self):
        buckets = _parse_rows(_rows(["Prosecution", "x", "y", "DOC CODE"], ["a", "b"]))
        assert buckets == {"prosecution": [], "ptab": [], "fpd": []}


class TestCellCleaning:
    def test_a_pipe_is_escaped_for_the_markdown_table(self):
        """The defect: an unescaped `|` in a USPTO description breaks the row
        it sits in, and the MCP resource had no escape at all."""
        assert _clean("Petition A | Petition B", 120) == "Petition A \\| Petition B"

    def test_a_pipe_in_a_parsed_row_reaches_the_table_escaped(self):
        buckets = _parse_rows(
            _rows(["Prosecution", "Amendment | Response", "Filing", "AMD"])
        )
        table = render_doc_code_markdown(buckets)
        row = next(line for line in table.splitlines() if "`AMD`" in line)
        assert row.count("|") == 4 + 1, (
            f"an unescaped pipe split the row into extra cells: {row!r}"
        )
        assert "\\|" in row

    def test_newlines_are_flattened(self):
        # \r and \n each become a space, so CRLF yields two. Behavior
        # preserved verbatim from both original copies.
        assert _clean("line one\nline two", 120) == "line one line two"
        assert _clean("line one\r\nline two", 120) == "line one  line two"

    def test_non_ascii_is_replaced(self):
        assert _clean("café", 120) == "caf?"

    def test_truncation_uses_the_proxy_cap_not_the_resource_cap(self):
        """120/100, the proxy's values; the resource used 100/80."""
        assert len(_clean("x" * 500, 120)) == 120
        assert _clean("x" * 500, 120).endswith("...")


class TestPartialParse:
    def test_a_failure_mid_parse_yields_no_rows_at_all(self):
        """Both old copies initialized the buckets OUTSIDE the encoding loop
        and appended inside it, so a decode failure partway through left
        partial rows behind and the next encoding duplicated them."""

        def exploding_reader():
            yield _HEADER
            yield ["Prosecution", "First", "Filing", "AAA"]
            raise UnicodeDecodeError("utf-8", b"", 0, 1, "boom")

        with pytest.raises(UnicodeDecodeError):
            _parse_rows(exploding_reader())

    def test_buckets_are_local_to_the_call(self):
        source = inspect.getsource(_parse_rows)
        assert "buckets: Dict[str, List[dict]] = {" in source, (
            "the buckets must be constructed inside _parse_rows, not shared"
        )


class TestAgreement:
    def test_both_endpoints_render_from_one_function(self):
        """Source-level, in the spirit of test_identifier_resolution_order.py:
        neither call site may grow its own parser again."""
        from patent_filewrapper_mcp import main
        from patent_filewrapper_mcp.proxy.routes import reference

        for module, func_name in (
            (main, "read_doc_codes"),
            (reference, "get_doc_codes"),
        ):
            source = inspect.getsource(getattr(module, func_name))
            assert "build_doc_code_table" in source, (
                f"{func_name} does not use the shared doc-code builder"
            )
            assert "csv.reader" not in source, (
                f"{func_name} has grown its own CSV parser again"
            )

    def test_the_real_csv_renders(self):
        table = build_doc_code_table()
        assert table.startswith("# USPTO Document Code Decoder Table")
        assert "## Common Prosecution Document Codes" in table

    def test_a_missing_csv_raises_rather_than_returning_a_partial_table(self):
        with pytest.raises(ValueError):
            parse_doc_code_csv("/nonexistent/Document_Descriptions_List.csv")
