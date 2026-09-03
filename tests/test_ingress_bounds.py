"""Bounds on what the server will accept and buffer: request bodies, Lucene
date parameters, archive members, and documents held for extraction
(audits M-5, M-8, M-18, M-19, L-19).
"""

import inspect
import io
import zipfile

import pytest

from patent_filewrapper_mcp import server_bootstrap
from patent_filewrapper_mcp.api import free_text_variants as fv
from patent_filewrapper_mcp.models.search_params import (
    ParameterValidationError,
    SearchParameters,
)
from patent_filewrapper_mcp.tools.search_tools import _build_query_from_params


class TestRequestSizeCapOnTheMcpTransport:
    """The cap was mounted on the proxy app only. POST /mcp is the primary
    tool ingress and, in OAuth mode, the body is read before the bearer check
    runs, so it was unbounded PRE-AUTH (audit M-5)."""

    def test_both_auth_branches_wrap_the_mcp_app(self):
        source = inspect.getsource(server_bootstrap.main)
        assert source.count("RequestSizeLimitMiddleware(") == 2, (
            "the size cap must wrap the MCP app in the oauth AND the "
            "non-oauth branch"
        )

    def test_the_cap_is_outermost(self):
        """Outermost so an oversized body is refused before anything reads it."""
        source = inspect.getsource(server_bootstrap.main)
        for line in source.splitlines():
            if "app = " in line and "RequestSizeLimitMiddleware" in line:
                break
        else:
            pytest.fail("the size cap is not the outermost wrapper")

    def test_the_middleware_counts_streamed_bytes(self):
        """A chunked body carries no Content-Length; the cap must survive that."""
        from patent_filewrapper_mcp.proxy.server import RequestSizeLimitMiddleware

        source = inspect.getsource(RequestSizeLimitMiddleware)
        assert "content-length" in source.lower()
        assert "more_body" in source or "body" in source


class TestLuceneDateValidation:
    """The four date parameters are interpolated into range clauses unescaped.
    The comment said that was safe because they are "in known format" —
    nothing checked (audit M-8)."""

    _INJECTION = "2020-01-01] OR applicationMetaData.patentNumber:[* TO *"

    @pytest.mark.parametrize(
        "field",
        [
            "filing_date_start",
            "filing_date_end",
            "grant_date_start",
            "grant_date_end",
        ],
    )
    def test_an_injection_payload_is_rejected_by_the_query_builder(self, field):
        with pytest.raises(ParameterValidationError):
            _build_query_from_params(**{field: self._INJECTION})

    @pytest.mark.parametrize(
        "field",
        [
            "filing_date_start",
            "filing_date_end",
            "grant_date_start",
            "grant_date_end",
        ],
    )
    def test_an_injection_payload_is_rejected_by_the_parameter_object(self, field):
        with pytest.raises(ParameterValidationError):
            SearchParameters(query="foo", **{field: self._INJECTION})

    @pytest.mark.parametrize(
        "value",
        ["2020-1-1", "20200101", "2020/01/01", "yesterday", "*", "2020-01-01 "],
    )
    def test_non_iso_shapes_are_rejected(self, value):
        with pytest.raises(ParameterValidationError):
            _build_query_from_params(filing_date_start=value)

    def test_the_error_names_the_offending_field(self):
        with pytest.raises(ParameterValidationError) as exc:
            _build_query_from_params(grant_date_end="nope")
        assert "grant_date_end" in str(exc.value)

    def test_valid_dates_still_build_a_range_clause(self):
        query = _build_query_from_params(
            filing_date_start="2020-01-01", filing_date_end="2021-12-31"
        )
        assert "applicationMetaData.filingDate:[2020-01-01 TO 2021-12-31]" in query

    def test_an_open_ended_range_still_works(self):
        query = _build_query_from_params(grant_date_start="2020-01-01")
        assert "applicationMetaData.grantDate:[2020-01-01 TO *]" in query

    def test_omitting_the_dates_entirely_is_fine(self):
        assert _build_query_from_params(art_unit="2142")


def _zip_of(members):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buffer.getvalue()


class TestArchiveBounds:
    def test_a_docx_part_over_the_member_cap_is_refused(self, monkeypatch):
        """The three docx zf.read() calls had no cap at all (audit M-18)."""
        monkeypatch.setattr(fv, "_MAX_MEMBER_BYTES", 1024)
        data = _zip_of({"word/document.xml": b"<x>" + b"A" * 5000 + b"</x>"})

        with pytest.raises(fv.VariantEmptyError):
            fv.extract_docx(data, "16816197")

    def test_a_normal_docx_part_still_reads(self):
        text = (
            '<?xml version="1.0"?><w:document '
            'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>A patent claim</w:t></w:r></w:p></w:body>"
            "</w:document>"
        ).encode()
        result = fv.extract_docx(_zip_of({"word/document.xml": text}), "16816197")
        assert "A patent claim" in result["text"]

    def test_the_aggregate_byte_budget_stops_the_walk(self, monkeypatch):
        """Per-member alone is not a bound: many small members add up
        (audit L-19)."""
        monkeypatch.setattr(fv, "_MAX_ARCHIVE_BYTES", 1000)
        data = _zip_of({f"m{i}.xml": b"B" * 400 for i in range(20)})

        members = fv._archive_members(data)

        assert 0 < len(members) < 20
        assert sum(len(raw) for _, raw in members) <= 1000 + 400

    def test_the_member_count_budget_stops_the_walk(self, monkeypatch):
        monkeypatch.setattr(fv, "_MAX_ARCHIVE_MEMBERS", 5)
        data = _zip_of({f"m{i}.xml": b"C" for i in range(50)})

        assert len(fv._archive_members(data)) == 5

    def test_a_small_archive_is_returned_whole(self):
        data = _zip_of({"a.xml": b"<a/>", "b.xml": b"<b/>"})
        assert {name for name, _ in fv._archive_members(data)} == {"a.xml", "b.xml"}

    def test_a_member_that_decompresses_past_its_declared_size_is_dropped(
        self, monkeypatch
    ):
        """The cap used to be applied to the DECLARED size only."""
        monkeypatch.setattr(fv, "_MAX_MEMBER_BYTES", 100)
        data = _zip_of({"bomb.xml": b"D" * 10_000})
        assert fv._archive_members(data) == []


class TestExtractionDocumentCeiling:
    """`response.content` buffers the whole PDF, slice_pdf_pages holds a
    second copy and a multipart OCR body a third, and nothing checked
    Content-Length (audits M-19, resilience F-9)."""

    class _Response:
        def __init__(self, length):
            self.headers = {"content-length": str(length)}

    def test_an_oversized_document_is_refused_with_actionable_advice(self):
        from patent_filewrapper_mcp.api.enhanced_client import EnhancedPatentClient
        from patent_filewrapper_mcp.exceptions import ValidationError

        with pytest.raises(ValidationError) as exc:
            EnhancedPatentClient._check_download_size(self._Response(500_000_000))
        assert "page_from" in str(exc.value), (
            "the refusal must tell the caller how to get the content anyway"
        )

    def test_a_normal_document_passes(self):
        from patent_filewrapper_mcp.api.enhanced_client import EnhancedPatentClient

        EnhancedPatentClient._check_download_size(self._Response(5_000_000))

    def test_a_missing_or_unparseable_content_length_does_not_block(self):
        from patent_filewrapper_mcp.api.enhanced_client import EnhancedPatentClient

        class _NoLength:
            headers = {}

        class _Junk:
            headers = {"content-length": "not-a-number"}

        EnhancedPatentClient._check_download_size(_NoLength())
        EnhancedPatentClient._check_download_size(_Junk())

    def test_the_ceiling_is_env_tunable(self, monkeypatch):
        from patent_filewrapper_mcp.api.enhanced_client import max_document_bytes

        monkeypatch.setenv("PFW_MAX_DOCUMENT_BYTES", "12345")
        assert max_document_bytes() == 12345

    def test_an_invalid_env_value_falls_back_to_the_default(self, monkeypatch):
        from patent_filewrapper_mcp.api.enhanced_client import max_document_bytes

        monkeypatch.setenv("PFW_MAX_DOCUMENT_BYTES", "banana")
        assert max_document_bytes() == 100_000_000

    @pytest.mark.parametrize(
        "method", ["_download_pdf_for_extraction", "_fetch_variant_bytes"]
    )
    def test_both_buffering_call_sites_check_the_size(self, method):
        from patent_filewrapper_mcp.api.enhanced_client import EnhancedPatentClient

        source = inspect.getsource(getattr(EnhancedPatentClient, method))
        assert "_check_download_size" in source
