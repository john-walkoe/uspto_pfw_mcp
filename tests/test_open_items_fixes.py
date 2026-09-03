"""Tests for the 2026-08-30 open-items fixes.

Every case here pins a defect the 2026-08-29/30 skill-test sweep found, with
the live-probed values that proved it. Hermetic: no network, no FastMCP server,
no USPTO key beyond a placeholder.

Live values used as fixtures (probed 2026-08-30 against api.uspto.gov):
  * US 9,135,462 / app 13975827 — 529 <patcit> + 111 <nplcit> under
    <us-references-cited>/<us-citation>; independent claims 1, 13, 19;
    provisional parent 61/694,492 filed 2012-08-29 vs effectiveFilingDate
    2013-08-26
  * US 7,971,071 / app 11752072 — 91 <patcit> under <references-cited>/<citation>
  * "12539322" — patent 12,539,322 is application 17996652 (Nestle), while
    application 12/539,322 is an unrelated Canon image sensor
"""

import pytest
import yaml

from patent_filewrapper_mcp.api.enhanced_client import (
    PTGRXML_FIRST_SERVED_GRANT_YEAR,
    PTGRXML_NOT_SERVED_MESSAGE,
)
from patent_filewrapper_mcp.api.helpers import (
    annotate_earliest_priority,
    compute_earliest_priority,
)
from patent_filewrapper_mcp.api.xml_parsing import (
    CITATIONS_PARSE_FAILED,
    CITATIONS_PARSED,
    CITATIONS_UNAVAILABLE,
    derive_claim_type,
    parse_xml_for_llm,
)
from patent_filewrapper_mcp.models.constants import IdentifierType
from patent_filewrapper_mcp.util.identifier_normalization import normalize_identifier
from patent_filewrapper_mcp.util.identifier_resolution import (
    resolve_application_number,
    resolve_identifier_lanes,
)


class _CaptureMCP:
    """Collects the functions each tools module registers."""

    def __init__(self):
        self.tools = {}

    def tool(self, *args, **kwargs):
        if args and callable(args[0]):
            fn = args[0]
            self.tools[kwargs.get("name") or fn.__name__] = fn
            return fn

        def decorator(fn):
            self.tools[kwargs.get("name") or fn.__name__] = fn
            return fn

        return decorator


class _LaneClient:
    """Stands in for EnhancedPatentClient's identifier-lane lookup."""

    def __init__(self, hits=None):
        #: {query: hit dict}. A query absent from the map is a lane MISS.
        self.hits = hits or {}
        self.queries = []

    async def lookup_identifier_lane(self, query):
        self.queries.append(query)
        return self.hits.get(query)


# ---------------------------------------------------------------------------
# #9 — an 8-digit identifier is both a patent number and an application serial
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", ["12539322", "11752072", "16816197", "08000000", "07999999"])
def test_eight_digit_identifiers_are_ambiguous(value):
    """The old rule typed anything >= 8,000,000 as an application serial, so a
    2024-or-later patent number was silently answered with a stranger's file."""
    info = normalize_identifier(value)
    assert info.identifier_type == IdentifierType.AMBIGUOUS
    assert info.confidence == "medium"
    # The patent lane is tried FIRST, the application lane is the fallback.
    assert info.search_query == f"applicationMetaData.patentNumber:{value}"
    assert info.alternate_search_query == f"applicationNumberText:{value}"


def test_seven_digit_identifier_is_still_an_unambiguous_patent_number():
    info = normalize_identifier("7971071")
    assert info.identifier_type == IdentifierType.PATENT
    assert info.confidence == "high"
    assert info.alternate_search_query is None


@pytest.mark.asyncio
async def test_ambiguous_identifier_resolves_through_the_patent_lane_first():
    client = _LaneClient({
        "applicationMetaData.patentNumber:12539322": {
            "applicationNumberText": "17996652",
            "applicationMetaData": {"patentNumber": "12539322"},
        }
    })

    resolved = await resolve_identifier_lanes(client, "12539322")

    assert resolved.resolved_as == "patent"
    assert resolved.application_number == "17996652"
    assert resolved.ambiguous is True
    assert client.queries[0] == "applicationMetaData.patentNumber:12539322"
    fields = resolved.response_fields()
    assert fields["identifier_resolved_as"] == "patent"
    assert "applicationMetaData.patentNumber:12539322" in fields["identifier_lanes_tried"][0]


@pytest.mark.asyncio
async def test_ambiguous_identifier_falls_back_to_the_application_lane():
    client = _LaneClient()  # patent lane misses

    resolved = await resolve_application_number(client, "15992176")

    assert resolved.resolved_as == "application"
    assert resolved.application_number == "15992176"
    # Both lanes are reported even though only one was queried.
    assert len(resolved.lanes_tried) == 2
    assert "applicationNumberText:15992176" in resolved.lanes_tried[1]


@pytest.mark.asyncio
async def test_content_type_patent_forces_the_patent_lane():
    client = _LaneClient({
        "applicationMetaData.patentNumber:12539322": {
            "applicationNumberText": "17996652",
            "applicationMetaData": {"patentNumber": "12539322"},
        }
    })
    resolved = await resolve_identifier_lanes(client, "12539322", content_type="patent")
    assert resolved.resolved_as == "patent"
    assert client.queries == ["applicationMetaData.patentNumber:12539322"]


@pytest.mark.asyncio
async def test_content_type_application_forces_the_application_lane():
    client = _LaneClient()
    resolved = await resolve_identifier_lanes(client, "12539322", content_type="application")
    assert resolved.resolved_as == "application"
    assert resolved.application_number == "12539322"
    assert client.queries == []  # no lookup needed, the caller settled it


@pytest.mark.asyncio
async def test_verified_application_lane_reports_unresolved_when_both_miss():
    client = _LaneClient()
    resolved = await resolve_identifier_lanes(
        client, "99999999", verify_application_lane=True
    )
    assert resolved.resolved_as == "unresolved"
    assert resolved.application_number is None
    assert len(resolved.lanes_tried) == 2


# --- the tools report the lane ---------------------------------------------

class _DocsClient(_LaneClient):
    async def get_documents(self, app_number, **kwargs):
        return {
            "application_number": app_number,
            "count": 1,
            "documentBag": [{"documentCode": "CTNF", "documentIdentifier": "X"}],
            "summary": {},
        }


@pytest.fixture
def document_tools(monkeypatch):
    monkeypatch.setenv("USPTO_API_KEY", "test-uspto-key-0123456789")
    from patent_filewrapper_mcp.tools import document_tools as mod

    fake = _CaptureMCP()
    mod.register(fake)
    return fake.tools, mod


@pytest.mark.asyncio
async def test_documents_tool_reports_the_resolved_lane(document_tools, monkeypatch):
    tools, mod = document_tools
    client = _DocsClient({
        "applicationMetaData.patentNumber:12539322": {
            "applicationNumberText": "17996652",
            "applicationMetaData": {"patentNumber": "12539322"},
        }
    })
    monkeypatch.setattr(mod, "_client", lambda: client)

    result = await tools["PFW_get_application_documents"]("12539322")

    assert result["identifier_resolved_as"] == "patent"
    assert result["identifier_input"] == "12539322"
    assert result["application_number"] == "17996652"


@pytest.mark.asyncio
async def test_documents_tool_reports_an_unresolved_identifier(document_tools, monkeypatch):
    tools, mod = document_tools

    class _NeverHits(_DocsClient):
        pass

    # A 7-digit value reads as a patent number; when no patent carries it the
    # tool must say so rather than querying a random application.
    monkeypatch.setattr(mod, "_client", lambda: _NeverHits())
    result = await tools["PFW_get_application_documents"]("1234567")
    assert result.get("success") is False
    assert result["identifier_resolved_as"] == "unresolved"


# ---------------------------------------------------------------------------
# #1 — citations: both element spellings, and a status next to every zero
# ---------------------------------------------------------------------------

_OLD_SCHEMA_XML = """<us-patent-grant>
  <references-cited>
    <citation><patcit><document-id><doc-number>7000001</doc-number></document-id></patcit></citation>
    <citation><patcit><document-id><doc-number>7000002</doc-number></document-id></patcit></citation>
    <citation><nplcit><othercit>Some paper</othercit></nplcit></citation>
  </references-cited>
</us-patent-grant>"""

_NEW_SCHEMA_XML = """<us-patent-grant>
  <us-references-cited>
    <us-citation><patcit><document-id><doc-number>9000001</doc-number></document-id></patcit></us-citation>
    <us-citation><patcit><document-id><doc-number>9000002</doc-number></document-id></patcit></us-citation>
    <us-citation><patcit><document-id><doc-number>9000003</doc-number></document-id></patcit></us-citation>
    <us-citation><nplcit><othercit>Some paper</othercit></nplcit></us-citation>
  </us-references-cited>
</us-patent-grant>"""

_NO_REFERENCES_XML = "<us-patent-application><abstract>x</abstract></us-patent-application>"

_EMPTY_CONTAINER_XML = """<us-patent-grant>
  <us-references-cited></us-references-cited>
</us-patent-grant>"""


def test_old_schema_citations_still_parse():
    out = parse_xml_for_llm(_OLD_SCHEMA_XML, ["citations"])
    assert out["citations_total"] == 2
    assert out["npl_citations_total"] == 1
    assert out["citations_status"] == CITATIONS_PARSED
    assert out["citations_container"] == "references-cited"


def test_new_schema_citations_are_no_longer_reported_as_zero():
    """<us-citation> under <us-references-cited> is what every grant issued from
    roughly 2013 uses; the extractor only looked for <citation>, so US 9,135,462
    (529 citations) came back citations_total: 0 with success: true."""
    out = parse_xml_for_llm(_NEW_SCHEMA_XML, ["citations"])
    assert out["citations_total"] == 3
    assert out["citations_status"] == CITATIONS_PARSED
    assert out["citations_container"] == "us-references-cited"


def test_absent_references_block_is_unavailable_not_a_silent_zero():
    out = parse_xml_for_llm(_NO_REFERENCES_XML, ["citations"])
    assert out["citations_total"] == 0
    assert out["citations_status"] == CITATIONS_UNAVAILABLE
    assert out["citations_container"] is None
    assert "absence of data" in out["citations_note"]


def test_present_but_unparseable_references_block_is_a_parse_failure():
    out = parse_xml_for_llm(_EMPTY_CONTAINER_XML, ["citations"])
    assert out["citations_total"] == 0
    assert out["citations_status"] == CITATIONS_PARSE_FAILED
    assert "PARSE FAILURE" in out["citations_note"]


# ---------------------------------------------------------------------------
# #2 — claim type derived from the claim text, not a keyword guess
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("1. A first device, comprising: at least one display", "independent"),
    ("2. The first device of claim 1, wherein the instructions", "dependent"),
    ("16. The method of claim 14, comprising: using the MCD", "dependent"),
    ("17. A computer memory that is not a transitory signal and that comprises "
     "instructions", "independent"),
    ("19. A non-transitory computer readable storage medium having instructions "
     "stored thereon", "independent"),
    ("3. The method according to claim 1, further comprising", "dependent"),
    ("4. The apparatus as claimed in claim 2, wherein", "dependent"),
    ("5. The method as recited in claim 1", "dependent"),
    ("6. The system of any one of claims 1 to 4", "dependent"),
])
def test_claim_type_is_derived_from_the_claim_text(text, expected):
    assert derive_claim_type(text) == expected


def test_a_claim_ref_link_makes_a_claim_dependent():
    assert derive_claim_type("A method of doing things, comprising:", has_claim_ref=True) == "dependent"


_CLAIMS_XML = """<us-patent-grant><claims>
  <claim num="00001"><claim-text>1. A method, comprising: doing a thing wherein: it works</claim-text></claim>
  <claim num="00002"><claim-text>2. The method of <claim-ref idref="CLM-00001">claim 1</claim-ref>,
      wherein the thing is blue</claim-text></claim>
  <claim num="00003"><claim-text>3. A non-transitory computer readable storage medium having
      instructions stored thereon</claim-text></claim>
</claims></us-patent-grant>"""


def test_claims_expose_both_reported_and_derived_types():
    out = parse_xml_for_llm(_CLAIMS_XML, ["claims"])
    claims = {c["number"]: c for c in out["claims"]}

    # Claim 3 is independent but has neither "comprising:" nor "wherein:", so the
    # old keyword guess called it dependent. The derived value is authoritative.
    assert claims["00003"]["type_reported"] == "dependent"
    assert claims["00003"]["type_derived"] == "independent"
    assert claims["00003"]["type"] == claims["00003"]["type_derived"]

    # Claim 2 refers to claim 1 both in text and by <claim-ref>.
    assert claims["00002"]["type_derived"] == "dependent"
    assert claims["00002"]["depends_on"] == ["CLM-00001"]

    assert out["claims_independent_count"] == 2
    assert "type_derived" in out["claims_type_note"]


# ---------------------------------------------------------------------------
# #4 — AIA status in the balanced field sets
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def field_configs():
    with open("field_configs.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)["predefined_sets"]


@pytest.mark.parametrize("set_name", ["applications_balanced", "inventor_balanced"])
def test_balanced_sets_request_the_aia_indicator(field_configs, set_name):
    assert "applicationMetaData.firstInventorToFileIndicator" in field_configs[set_name]["fields"]


@pytest.mark.parametrize("set_name", ["applications_balanced", "inventor_balanced"])
def test_balanced_sets_request_the_parent_filing_dates(field_configs, set_name):
    """Without these the earliest-priority computation has nothing to minimise
    over but the application's own filing date."""
    fields = field_configs[set_name]["fields"]
    assert "parentContinuityBag.parentApplicationFilingDate" in fields
    assert "parentContinuityBag.claimParentageTypeCode" in fields


def test_the_continuity_bag_namesake_warning_is_documented():
    with open("field_configs.yaml", encoding="utf-8") as fh:
        text = fh.read()
    assert "NAMESAKE WARNING" in text
    assert "childContinuityBag[]" in text


# ---------------------------------------------------------------------------
# #13 — earliest priority date, not effectiveFilingDate
# ---------------------------------------------------------------------------

def test_a_provisional_parent_beats_the_applications_own_filing_date():
    """The live case: app 13975827 reports effectiveFilingDate 2013-08-26 while
    its provisional 61/694,492 was filed 2012-08-29."""
    result = compute_earliest_priority(
        own_filing_date="2013-08-26",
        own_application_number="13975827",
        parent_entries=[{
            "application_number": "61694492",
            "filing_date": "2012-08-29",
            "relation_type": "PRO",
        }],
    )
    assert result["earliest_priority_date"] == "2012-08-29"
    assert "provisional parent) 61694492" in result["priority_basis"]
    assert "effectiveFilingDate" in result["priority_note"]


def test_a_foreign_priority_claim_can_win():
    result = compute_earliest_priority(
        own_filing_date="2019-05-06",
        own_application_number="16999999",
        parent_entries=[],
        foreign_priority=[{
            "country": "JP", "application_number": "2018-118000",
            "filing_date": "2018-06-22",
        }],
    )
    assert result["earliest_priority_date"] == "2018-06-22"
    assert result["priority_basis"].startswith("foreignPriorityBag (JP)")


def test_no_dates_at_all_is_reported_rather_than_guessed():
    result = compute_earliest_priority()
    assert result["earliest_priority_date"] is None
    assert "no filing or priority date" in result["priority_basis"]


def test_datetime_stamps_are_normalized_to_a_date():
    result = compute_earliest_priority(own_filing_date="2013-08-26T00:00:00")
    assert result["earliest_priority_date"] == "2013-08-26"


def test_search_hits_are_annotated_in_place():
    applications = [
        {
            "applicationNumberText": "13975827",
            "applicationMetaData": {"filingDate": "2013-08-26"},
            "parentContinuityBag": [{
                "parentApplicationNumberText": "61694492",
                "parentApplicationFilingDate": "2012-08-29",
                "claimParentageTypeCode": "PRO",
            }],
        },
        {"applicationNumberText": "00000000"},  # nothing to compute from
    ]
    annotated = annotate_earliest_priority(applications)
    assert annotated == 1
    assert applications[0]["earliest_priority_date"] == "2012-08-29"
    assert "earliest_priority_date" not in applications[1]


# ---------------------------------------------------------------------------
# #7 — the document-code decoder, reconciled across three files
# ---------------------------------------------------------------------------

def test_n417_is_an_efs_receipt_not_an_applicant_response():
    from patent_filewrapper_mcp.guidance import _get_document_codes_section

    text = _get_document_codes_section()
    assert "Electronic Filing System Acknowledgment Receipt" in text
    assert "N417** - Applicant's Response/Amendment" not in text


def test_ctav_is_decoded():
    from patent_filewrapper_mcp.guidance import _get_document_codes_section

    assert "CTAV** - Advisory Action (PTOL-303)" in _get_document_codes_section()


def test_srfw_is_search_information_and_ctrs_is_the_restriction_requirement():
    from patent_filewrapper_mcp.guidance import _get_document_codes_section

    text = _get_document_codes_section()
    assert "CTRS** - Requirement for Restriction/Election" in text
    assert "SRFW** - Search information including classification" in text
    # The old table called SRFW the restriction/election requirement.
    assert "SRFW** - Restriction/Election Requirement" not in text


def test_the_decoder_says_it_is_not_proof_a_code_does_not_exist():
    from patent_filewrapper_mcp.guidance import _get_document_codes_section

    assert "Absence from this table proves nothing" in _get_document_codes_section()


def test_the_three_code_tables_agree():
    from patent_filewrapper_mcp.guidance import _get_document_codes_section
    from patent_filewrapper_mcp.util.package_manager import PackageManager

    decoder = _get_document_codes_section()
    categorized = set(
        PackageManager.CRITICAL_DOCS
        + PackageManager.IMPORTANT_DOCS
        + PackageManager.STANDARD_DOCS
    )
    for code in categorized:
        assert f"**{code}**" in decoder, f"{code} is categorized but not decoded"

    with open("src/patent_filewrapper_mcp/ui/views.py", encoding="utf-8") as fh:
        views = fh.read()
    icons = views.split("const DOC_ICONS = {", 1)[1].split("};", 1)[0]
    for code in ("CTAV", "CTRS", "SRFW"):
        assert f"{code}:" in icons, f"{code} has no downloads-view icon"
        assert f"**{code}**" in decoder


# ---------------------------------------------------------------------------
# #8 — action_type validated against the served set
# ---------------------------------------------------------------------------

def test_served_action_types_are_accepted():
    from patent_filewrapper_mcp.tools.oa_tools import OA_TEXT_ACTION_TYPES, validate_action_type

    for code in OA_TEXT_ACTION_TYPES:
        normalized, error = validate_action_type(code.lower())
        assert error is None
        assert normalized == code


def test_ctav_is_in_the_served_set():
    """CTAV was reported as unsupported; the dataset carries 47,327 CTAV records
    (probed 2026-08-30), so the empty result was per-application, not per-code."""
    from patent_filewrapper_mcp.tools.oa_tools import OA_TEXT_ACTION_TYPES

    assert "CTAV" in OA_TEXT_ACTION_TYPES


def test_an_unserved_action_type_is_rejected_with_the_served_set():
    from patent_filewrapper_mcp.tools.oa_tools import validate_action_type

    _, error = validate_action_type("N417")
    assert error is not None
    assert error.get("success") is False
    assert "CTNF" in error["action_types_served"]
    assert "CTAV" in error["action_types_served"]
    assert "probe-verified" in error["action_types_provenance"].lower()


@pytest.fixture
def oa_tools(monkeypatch):
    monkeypatch.setenv("USPTO_API_KEY", "test-uspto-key-0123456789")
    from patent_filewrapper_mcp.tools import oa_tools as mod

    fake = _CaptureMCP()
    mod.register(fake)
    return fake.tools, mod


class _FakeOATextClient:
    def __init__(self, docs):
        self._docs = docs
        self.calls = []

    async def search(self, criteria, start=0, rows=10):
        self.calls.append(criteria)
        return {"response": {"docs": self._docs, "numFound": len(self._docs)}}

    def extract_body_text(self, doc):
        return doc.get("bodyText", "")

    def extract_section_text(self, doc, section):
        return ""


@pytest.mark.asyncio
async def test_oa_text_rejects_an_unserved_action_type_before_any_call(oa_tools, monkeypatch):
    tools, mod = oa_tools
    client = _FakeOATextClient([])
    monkeypatch.setattr(mod, "_get_oa_text_client", lambda: client)

    result = await tools["PFW_get_oa_text"]("15992176", action_type="ZZZZ")

    assert result.get("success") is False
    assert "action_types_served" in result
    assert client.calls == []  # nothing reached USPTO


# ---------------------------------------------------------------------------
# #5 — the document-bag census next to the OA text result
# ---------------------------------------------------------------------------

class _CensusClient(_LaneClient):
    def __init__(self, codes, hits=None):
        super().__init__(hits)
        self._codes = codes

    async def get_documents(self, app_number, **kwargs):
        return {
            "application_number": app_number,
            "documentBag": [{"documentCode": c} for c in self._codes],
        }


@pytest.mark.asyncio
async def test_oa_text_returns_the_document_bag_census(oa_tools, monkeypatch):
    """A CTRS in the file wrapper that the OA text dataset does not serve used
    to read exactly like an application that never had one."""
    tools, mod = oa_tools
    monkeypatch.setattr(mod, "_get_oa_text_client", lambda: _FakeOATextClient([]))
    monkeypatch.setattr(
        mod, "_client", lambda: _CensusClient(["CTNF", "CTNF", "CTRS", "REM"])
    )

    result = await tools["PFW_get_oa_text"]("15992176")

    assert result["num_found"] == 0
    assert result["documents_by_code"] == {"CTNF": 2, "CTRS": 1, "REM": 1}
    assert "COVERAGE GAP" in result["documents_by_code_note"]
    assert "CTRS" in result["documents_by_code_note"]
    assert "CTNF" in result["action_types_served"]


@pytest.mark.asyncio
async def test_the_census_failing_does_not_fail_the_office_action_read(oa_tools, monkeypatch):
    tools, mod = oa_tools

    class _Broken(_LaneClient):
        async def get_documents(self, app_number, **kwargs):
            raise RuntimeError("documentBag unavailable")

    monkeypatch.setattr(mod, "_get_oa_text_client", lambda: _FakeOATextClient([]))
    monkeypatch.setattr(mod, "_client", lambda: _Broken())

    result = await tools["PFW_get_oa_text"]("15992176")

    assert result["success"] is True
    assert result["documents_by_code"] is None
    assert "unavailable" in result["documents_by_code_note"]


# ---------------------------------------------------------------------------
# #6 — a pre-2005 grant is a coverage boundary, not "may not be granted"
# ---------------------------------------------------------------------------

def test_missing_grant_xml_names_the_grant_year_boundary():
    assert PTGRXML_FIRST_SERVED_GRANT_YEAR == 2005
    assert "not served for this grant" in PTGRXML_NOT_SERVED_MESSAGE
    assert "2005" in PTGRXML_NOT_SERVED_MESSAGE
    assert "may not be granted" not in PTGRXML_NOT_SERVED_MESSAGE


def test_extract_xml_url_uses_the_coverage_message(monkeypatch):
    monkeypatch.setenv("USPTO_API_KEY", "test-uspto-key-0123456789")
    from patent_filewrapper_mcp.api.enhanced_client import EnhancedPatentClient

    client = EnhancedPatentClient()
    # Shape of the 2004-grant associated-documents response probed 2026-08-30:
    # a wrapper entry with no grantDocumentMetaData at all.
    assoc = {"documents": [{"applicationNumberText": "10881461"}], "ptgrXmlAvailable": False}
    with pytest.raises(ValueError) as exc:
        client.extract_xml_url(assoc, "PTGRXML")
    assert "not served for this grant" in str(exc.value)


# ---------------------------------------------------------------------------
# #11 — page ranges for text an extraction cap never reached
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_page_from_must_be_one_based(document_tools):
    tools, _ = document_tools
    result = await tools["PFW_get_document_content_with_ocr"]("17896175", "ABC", page_from=0)
    assert result.get("success") is False
    assert "1-based" in result["message"]


@pytest.mark.asyncio
async def test_page_to_must_not_precede_page_from(document_tools):
    tools, _ = document_tools
    result = await tools["PFW_get_document_content_with_ocr"](
        "17896175", "ABC", page_from=10, page_to=3
    )
    assert result.get("success") is False


@pytest.mark.asyncio
async def test_the_page_window_reaches_the_extraction_layer(document_tools, monkeypatch):
    tools, mod = document_tools
    seen = {}

    class _Recorder:
        async def extract_document_content_hybrid(
            self, app_number, document_identifier, auto_optimize, progress_cb=None,
            page_from=1, page_to=None,
        ):
            seen["page_from"] = page_from
            seen["page_to"] = page_to
            return {
                "success": True,
                "application_number": app_number,
                "document_identifier": document_identifier,
                "extracted_content": "text",
                "extraction_method": "Mistral OCR (direct)",
            }

    monkeypatch.setattr(mod, "_client", lambda: _Recorder())
    await tools["PFW_get_document_content_with_ocr"](
        "17896175", "ABC", page_from=51, page_to=104
    )
    assert seen == {"page_from": 51, "page_to": 104}


def test_slicing_a_pdf_to_a_page_window():
    pytest.importorskip("pypdf")
    import io

    import pypdf

    from patent_filewrapper_mcp.api.enhanced_client import slice_pdf_pages

    writer = pypdf.PdfWriter()
    for _ in range(10):
        writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    pdf = buffer.getvalue()

    sliced, first, last, total = slice_pdf_pages(pdf, 5, 8)
    assert (first, last, total) == (5, 8, 10)
    assert len(pypdf.PdfReader(io.BytesIO(sliced)).pages) == 4

    # A window covering the whole document is a no-op, byte-identical.
    same, first, last, total = slice_pdf_pages(pdf, 1, 10)
    assert same is pdf and first is None and last is None and total == 10

    # page_to past the end clamps; page_from past the end is an error.
    _, first, last, _ = slice_pdf_pages(pdf, 9, 99)
    assert (first, last) == (9, 10)
    with pytest.raises(ValueError):
        slice_pdf_pages(pdf, 11, None)


# ---------------------------------------------------------------------------
# #3, #10, #12 — documented limitations
# ---------------------------------------------------------------------------

def test_examiner_data_is_documented_as_never_populated():
    from patent_filewrapper_mcp.guidance import _get_fields_section

    text = _get_fields_section()
    assert "`examinerData`" in text
    assert "examinerNameText" in text


def test_assignment_bag_emptiness_is_documented():
    from patent_filewrapper_mcp.guidance import _get_fields_section

    text = _get_fields_section()
    assert "empty assignmentBag is not evidence of no" in text
    assert "3.73(c)" in text


def test_docx_variants_omitting_form_pages_is_documented():
    from patent_filewrapper_mcp.guidance import _get_documents_section

    text = _get_documents_section()
    assert "PTOL-471G" in text
    assert "extraction_method" in text


def test_effective_filing_date_is_documented_in_the_field_docs():
    from patent_filewrapper_mcp.guidance import _get_fields_section

    text = _get_fields_section()
    assert "effectiveFilingDate is NOT the priority date" in text
    assert "earliest_priority_date" in text


@pytest.mark.asyncio
async def test_pre2005_grant_coverage_message_survives_the_sanitizing_catch_all(monkeypatch):
    """Freddie eval tr-cov-43: after 0d81c91 sanitized the XML catch-all, the
    authored PTGRXML coverage message came back as a generic 500. Authored
    messages must reach the caller verbatim, as a 404 (agents retry 500s)."""
    monkeypatch.setenv("USPTO_API_KEY", "test-uspto-key-0123456789")
    from patent_filewrapper_mcp.api import enhanced_client as ec
    from patent_filewrapper_mcp.util import identifier_resolution as ir

    class _Resolved:
        application_number = "10881461"
        resolved_as = "patent"
        note = ""

        def response_fields(self):
            return {"identifier_resolved_as": "patent"}

    async def _fake_resolve(*args, **kwargs):
        return _Resolved()

    monkeypatch.setattr(ir, "resolve_identifier_lanes", _fake_resolve)
    client = ec.EnhancedPatentClient()

    async def _assoc(app_number):
        # 2004 grant: wrapper entry with no grantDocumentMetaData at all.
        return {"success": True, "associated_documents": [{"applicationNumberText": app_number}]}

    monkeypatch.setattr(client, "get_associated_documents", _assoc)

    result = await client.get_patent_or_application_xml("6794052", "patent")

    assert result.get("success") is False
    assert result["status_code"] == 404
    assert "2005" in result["message"]
    assert "coverage boundary" in result["message"] or "not served for this grant" in result["message"]
    assert result["error_type"] == "xml_not_available"
    assert result["identifier_resolved_as"] == "patent"
