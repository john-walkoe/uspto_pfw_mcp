"""Every document code is reachable, not just the first sixty.

The `uspto://pfw/doc-codes` resource rendered 60 of 367 prosecution rows sorted
by code, so it ran 136A..COVID-19 and stopped, and the only way forward it
named was a link to uspto.gov. A reader holding CTAV, PETDEC, REM, N417 or WFEE
got nothing (walkthrough follow-up, 2026-09-05).

Two distinct gaps, and only one is truncation:

  * REM and WFEE ARE in the CSV, past row 60. Paging reaches them.
  * CTAV, PETDEC and N417 are NOT in the CSV at any offset, and neither are
    CTNF, CTFR or NOA. It is the EFS-Web list of what an APPLICANT may file,
    so no outgoing examiner code is in it at all.

So the lookup reads the curated decoder as well as the CSV. That curated table
is SCRAPED from `guidance.py::_get_document_codes_section` rather than copied,
which makes this file the alarm on its bullet format: if an edit there changes
the shape, the five codes below stop resolving and this fails.
"""

import pytest

from patent_filewrapper_mcp.reference import doc_codes

#: The five the walkthrough could not decode. Non-negotiable.
WALKTHROUGH_CODES = ["CTAV", "PETDEC", "REM", "N417", "WFEE"]

#: In the curated table only. Absent from the CSV by construction.
EXAMINER_ONLY_CODES = ["CTNF", "CTFR", "NOA", "CTAV", "PETDEC", "N417", "892"]


@pytest.fixture(scope="module")
def buckets():
    return doc_codes.parse_doc_code_csv(doc_codes.find_doc_code_csv())


@pytest.fixture(scope="module")
def curated():
    return doc_codes.parse_curated_codes()


# ===========================================================================
# The five
# ===========================================================================

@pytest.mark.parametrize("code", WALKTHROUGH_CODES)
def test_the_walkthrough_codes_decode(code):
    matches = doc_codes.lookup_doc_codes(code)
    assert len(matches) == 1, f"{code} should resolve to exactly one code"
    assert matches[0]["code"].upper() == code
    assert matches[0]["description"].strip()


def test_the_five_decode_to_what_they_actually_are():
    """Pinned by meaning, not just by presence: the whole point of OPEN_ITEMS
    #7 was that three of these once carried WRONG glosses."""
    def decode(code):
        return doc_codes.lookup_doc_codes(code)[0]["description"].lower()

    assert "advisory action" in decode("CTAV")
    assert "petition decision" in decode("PETDEC")
    assert "remarks" in decode("REM")
    # N417 is the EFS receipt, NOT an applicant response.
    assert "acknowledgment receipt" in decode("N417")
    assert "response" not in decode("N417").split(".")[0]
    # WFEE is a worksheet, NOT the issue fee payment.
    assert "worksheet" in decode("WFEE")


@pytest.mark.parametrize("code", EXAMINER_ONLY_CODES)
def test_examiner_codes_resolve_although_the_csv_lacks_them(code, buckets):
    csv_codes = {
        entry["code"].upper()
        for rows in buckets.values()
        for entry in rows
    }
    assert code not in csv_codes, (
        f"{code} is now in the CSV; this test's premise needs rechecking"
    )
    matches = doc_codes.lookup_doc_codes(code)
    assert matches and matches[0]["code"].upper() == code
    assert matches[0]["source"] == doc_codes.CURATED_SOURCE


# ===========================================================================
# Lookup behavior
# ===========================================================================

def test_an_exact_match_short_circuits_the_prefix_scan():
    """`WFEE` is both a code and a prefix of `WFEE.APPEAL`. Asking for WFEE
    must answer about WFEE, not hand back a list to disambiguate."""
    matches = doc_codes.lookup_doc_codes("WFEE")
    assert len(matches) == 1
    assert matches[0]["code"].upper() == "WFEE"


def test_a_prefix_lists_its_codes():
    matches = doc_codes.lookup_doc_codes("PETD")
    assert [entry["code"] for entry in matches] == ["PETDEC"]

    wfe = {entry["code"] for entry in doc_codes.lookup_doc_codes("WFE")}
    assert {"WFEE", "WFEE.APPEAL"} <= wfe


def test_lookup_is_case_and_whitespace_insensitive():
    for spelling in ("ctav", "  CTAV ", "CtAv"):
        matches = doc_codes.lookup_doc_codes(spelling)
        assert matches and matches[0]["code"].upper() == "CTAV"


def test_an_unknown_code_returns_nothing_rather_than_a_guess():
    assert doc_codes.lookup_doc_codes("ZZZZQQ") == []
    assert doc_codes.lookup_doc_codes("") == []
    assert doc_codes.lookup_doc_codes(None) == []


def test_a_prefix_scan_is_capped():
    assert len(doc_codes.lookup_doc_codes("P", limit=5)) <= 5


def test_the_curated_gloss_outranks_the_csv():
    """Both sources hold REM and WFEE. The curated one was read out of a live
    documentBag in 2026; the CSV is from 2022."""
    for code in ("REM", "WFEE"):
        assert doc_codes.lookup_doc_codes(code)[0]["source"] == doc_codes.CURATED_SOURCE


def test_wrapped_glosses_are_not_cut_mid_clause(curated):
    """CTAV's gloss wraps across source lines. Truncating it at the line break
    would be a truncation defect inside the fix for a truncation defect."""
    assert curated["CTAV"].endswith(".")
    assert "after-final amendment" in curated["CTAV"]


def test_several_codes_sharing_one_gloss_all_resolve(curated):
    """`- **NRES** / **NTC.A.NONCPL** - ...` is one bullet, two codes."""
    assert curated.get("NRES")
    assert curated.get("NTC.A.NONCPL") == curated.get("NRES")


def test_the_curated_scrape_found_a_real_table(curated):
    """A format change in guidance.py that silently emptied this would leave
    the lookup CSV-only, which is the defect all over again."""
    assert len(curated) > 50


# ===========================================================================
# The resource: paging and an honest pointer
# ===========================================================================

def test_the_table_pages_and_the_second_page_differs(buckets):
    first = doc_codes.render_doc_code_markdown(buckets, offset=0)
    second = doc_codes.render_doc_code_markdown(buckets, offset=60)
    assert first != second
    assert "Showing 1-60 of" in first
    assert "Showing 61-120 of" in second


def test_paging_reaches_the_codes_the_first_page_never_showed(buckets):
    """REM and WFEE are in the CSV, past the sixtieth code. Walking the pages
    must actually arrive at them."""
    prosecution = sorted(buckets["prosecution"], key=lambda e: e["code"])
    everything = "".join(
        doc_codes.render_doc_code_markdown(buckets, offset=offset)
        for offset in range(0, len(prosecution), 60)
    )
    for code in ("REM", "WFEE"):
        assert f"| `{code}` |" in everything


def test_the_last_page_stops_offering_a_next_one(buckets):
    prosecution = buckets["prosecution"]
    last = doc_codes.render_doc_code_markdown(
        buckets, offset=(len(prosecution) // 60) * 60
    )
    assert "To reach the rest" not in last


def test_the_truncation_pointer_names_calls_not_just_a_website(buckets):
    """The old pointer offered only a uspto.gov link, which the model cannot
    call. Every route out must be something this server answers."""
    page = doc_codes.render_doc_code_markdown(buckets, offset=0)
    assert "PFW_get_guidance(section='document_codes', code='CTAV')" in page
    assert "/doc-codes?offset=60" in page


def test_the_pointer_says_where_the_examiner_codes_are(buckets):
    """Without this, a reader pages through all 367 rows looking for CTNF and
    concludes the server is broken. The office-issued codes now sit in their
    own table above the paged one, and the pointer says so."""
    page = doc_codes.render_doc_code_markdown(buckets, offset=0)
    assert "in their own table above" in page
    assert "absent by" not in page
    for code in ("CTNF", "CTFR", "NOA", "CTAV"):
        assert f"`{code}`" in page


def test_a_negative_offset_is_clamped(buckets):
    assert doc_codes.render_doc_code_markdown(
        buckets, offset=-10
    ) == doc_codes.render_doc_code_markdown(buckets, offset=0)


# ===========================================================================
# The guidance tool's rendering
# ===========================================================================

@pytest.mark.parametrize("code", WALKTHROUGH_CODES)
def test_the_guidance_lookup_renders_each_code(code):
    from patent_filewrapper_mcp.tools.guidance_tools import _render_code_lookup

    rendered = _render_code_lookup(code)
    assert f"**`{code}`**" in rendered
    assert "PFW_get_application_documents" in rendered


def test_the_guidance_lookup_lists_a_prefix():
    from patent_filewrapper_mcp.tools.guidance_tools import _render_code_lookup

    rendered = _render_code_lookup("WFE")
    assert "| `WFEE` |" in rendered
    assert "| `WFEE.APPEAL` |" in rendered


def test_an_unknown_code_says_absence_is_not_proof():
    from patent_filewrapper_mcp.tools.guidance_tools import _render_code_lookup

    rendered = _render_code_lookup("ZZZZQQ")
    assert "not proof the code is invalid" in rendered
    assert "documentCodeDescriptionText" in rendered
