"""CITATIONS ARE LINKS (2026-09-05).

A twelve-prompt walkthrough of this suite produced answers citing office
actions by date and claims by number with no link anywhere, because the tool
JSON carried none while the MCP App panels built links client-side. Every
citable record now carries `cite_as` and every envelope holding one carries
`citation_note`.

Fixture-based and hermetic: no USPTO call, no network, no key.

The static guard at the bottom is the one that matters most: this server's own
persistent document links are capability URLs minted for one reader, and a
citation target carrying one hands out a credential.
"""

import ast
import pathlib

import pytest

from patent_filewrapper_mcp.util import citation_links as cl
from patent_filewrapper_mcp.tools.family_tools import _attach_node_cite_as
from patent_filewrapper_mcp.tools.oa_tools import _build_oa_entry
from patent_filewrapper_mcp.tools.search_tools import _stamp_search_citations

SRC = pathlib.Path(cl.__file__).resolve().parents[1]


# ===========================================================================
# URL builders — only the two probed forms, and nothing else
# ===========================================================================

def test_google_patents_url_forms_probed_2026_09_05():
    # https://patents.google.com/patent/US7971071      -> 200
    assert cl.google_patents_url("7971071") == "https://patents.google.com/patent/US7971071"
    # commas, a US prefix and a kind code are all normalized away
    assert cl.google_patents_url("US 7,971,071 B2") == "https://patents.google.com/patent/US7971071"
    # https://patents.google.com/patent/US20010056539  -> 200
    assert cl.google_patents_url("20010056539") == "https://patents.google.com/patent/US20010056539"
    assert cl.google_patents_url("US20010056539A1") == "https://patents.google.com/patent/US20010056539"
    assert cl.google_patents_url(None) is None
    assert cl.google_patents_url("") is None


def test_patent_center_url_takes_eight_bare_digits():
    # https://patentcenter.uspto.gov/applications/11752072 -> 200
    expected = "https://patentcenter.uspto.gov/applications/11752072"
    assert cl.patent_center_url("11752072") == expected
    assert cl.patent_center_url("11/752,072") == expected
    # Anything that is not an 8-digit serial gets no URL rather than a guess.
    assert cl.patent_center_url("1175207") is None
    assert cl.patent_center_url("") is None
    assert cl.patent_center_url(None) is None


def test_number_display_forms():
    assert cl.format_application_serial("11752072") == "11/752,072"
    assert cl.format_patent_number("7971071") == "7,971,071"
    # A non-standard length is passed through as digits, never mis-punctuated.
    assert cl.format_application_serial("123") == "123"


# ===========================================================================
# Labels and links
# ===========================================================================

def test_granted_record_cites_google_patents_and_names_both_numbers():
    link = cl.application_cite_as("11752072", patent_number="7971071")
    assert link == "[US 7,971,071 (application 11/752,072)](https://patents.google.com/patent/US7971071)"


def test_ungranted_record_cites_patent_center():
    link = cl.application_cite_as("11752072")
    assert link == "[Application 11/752,072](https://patentcenter.uspto.gov/applications/11752072)"


def test_publication_number_cites_google_patents_when_no_patent_issued():
    link = cl.application_cite_as("09775715", publication_number="20010056539")
    assert link == (
        "[US 2001/0056539 (application 09/775,715)]"
        "(https://patents.google.com/patent/US20010056539)"
    )


def test_prefer_patent_center_overrides_a_known_patent_number():
    link = cl.application_cite_as("11752072", patent_number="7971071", prefer_patent_center=True)
    assert link.endswith("(https://patentcenter.uspto.gov/applications/11752072)")


def test_no_url_means_no_citation_rather_than_a_bare_label():
    assert cl.application_cite_as(None) is None
    assert cl.cite_as_link("anything", None) is None


def test_square_brackets_in_a_label_cannot_break_the_markdown():
    link = cl.cite_as_link("CTNF [draft] 2009-01-29", "https://example.invalid/x")
    assert link == "[CTNF (draft) 2009-01-29](https://example.invalid/x)"


def test_document_label_names_the_code_the_date_and_the_application():
    assert cl.document_label("11752072", "CTNF", "2009-01-29") == (
        "CTNF 2009-01-29, application 11/752,072"
    )
    # Either half may be missing; the label degrades rather than lying.
    assert cl.document_label("11752072") == "Document, application 11/752,072"


def test_document_cite_as_targets_the_application_page():
    link = cl.document_cite_as("11752072", "CTNF", "2009-01-29T00:00:00Z")
    assert link == (
        "[CTNF 2009-01-29, application 11/752,072]"
        "(https://patentcenter.uspto.gov/applications/11752072)"
    )


# ===========================================================================
# Persistent links are credentials, never citation targets
# ===========================================================================

def test_a_persistent_proxy_link_is_refused_as_a_citation_target():
    proxy = "http://localhost:8080/document/persistent/abcdef0123456789"
    assert cl.no_persistent_link(proxy) is None
    assert cl.cite_as_link("Office action", proxy) is None


def test_no_shipped_citation_target_can_be_a_persistent_link():
    """Static guard over the whole package: nothing that builds a citation URL
    may reference the capability-link path. The templates are the only two
    public forms, and both are hard-coded in util/citation_links.py."""
    module = pathlib.Path(cl.__file__).read_text()
    # The marker exists exactly once, as the thing being BLOCKED.
    assert module.count(cl.PERSISTENT_LINK_MARKER) == 1
    for template in (cl._GOOGLE_PATENTS, cl._PATENT_CENTER):
        assert cl.PERSISTENT_LINK_MARKER not in template
        assert template.startswith("https://")

    # And no tool module may construct a cite_as from a proxy/download URL.
    for path in sorted((SRC / "tools").glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name not in {"cite_as_link", "application_cite_as", "document_cite_as"}:
                continue
            rendered = ast.dump(node)
            assert "persistent" not in rendered.lower(), f"{path.name}: {rendered}"
            assert "download" not in rendered.lower(), f"{path.name}: {rendered}"


# ===========================================================================
# Search tools
# ===========================================================================

def _hit(app_number, patent_number=None):
    meta = {"inventionTitle": "A THING"}
    if patent_number:
        meta["patentNumber"] = patent_number
    return {"applicationNumberText": app_number, "applicationMetaData": meta}


def test_search_hits_are_stamped_and_the_envelope_carries_the_note():
    result = _stamp_search_citations({
        "success": True,
        "applications": [_hit("11752072", "7971071"), _hit("16816197")],
    })
    granted, pending = result["applications"]
    assert granted["cite_as"].endswith("(https://patents.google.com/patent/US7971071)")
    assert pending["cite_as"].endswith("(https://patentcenter.uspto.gov/applications/16816197)")
    assert result["citation_note"].startswith("CITATIONS ARE LINKS.")


def test_inventor_hits_land_under_unique_applications():
    result = _stamp_search_citations({
        "success": True, "unique_applications": [_hit("11752072")],
    })
    assert result["unique_applications"][0]["cite_as"]
    assert "citation_note" in result


@pytest.mark.parametrize("envelope", [
    {"success": False, "error": "boom"},
    {"success": True, "applications": []},
    {"success": True, "applications": [{"applicationMetaData": {}}]},
])
def test_no_hits_means_no_promise_of_links(envelope):
    """`citation_note` is ABSENT when nothing was stamped — the same
    absent-on-a-no-op rule `_bounds` and `limit_clamped` follow."""
    out = _stamp_search_citations(dict(envelope))
    assert "citation_note" not in out


def test_an_existing_cite_as_is_never_overwritten():
    hit = _hit("11752072", "7971071")
    hit["cite_as"] = "[kept](https://example.invalid/kept)"
    _stamp_search_citations({"success": True, "applications": [hit]})
    assert hit["cite_as"] == "[kept](https://example.invalid/kept)"


# ===========================================================================
# Family tool
# ===========================================================================

def test_family_nodes_are_stamped_by_grant_status():
    response = {
        "nodes": [
            {"application_number": "11752072", "patent_number": "7971071"},
            {"application_number": "16816197"},
            {"application_number": "60123456"},  # a provisional serial is 8 digits too
        ],
        "foreign_priority": [{"country": "JP", "application_number": "2006-123456"}],
    }
    stamped = _attach_node_cite_as(response)
    assert stamped == 3
    assert response["nodes"][0]["cite_as"].endswith("(https://patents.google.com/patent/US7971071)")
    assert response["nodes"][1]["cite_as"].endswith(
        "(https://patentcenter.uspto.gov/applications/16816197)"
    )
    # Foreign priority entries are deliberately left alone.
    assert "cite_as" not in response["foreign_priority"][0]


def test_family_node_with_no_usable_serial_is_skipped_not_guessed():
    response = {"nodes": [{"application_number": None}, {"application_number": "123"}]}
    assert _attach_node_cite_as(response) == 0
    assert all("cite_as" not in n for n in response["nodes"])


# ===========================================================================
# Office action tools
# ===========================================================================

_OA_BODY = "DETAILED ACTION\nClaims 1-21 are rejected under 35 U.S.C. 112, second paragraph.\n"

_OA_DOC = {
    "inventionTitle": "A THING",
    "documentCode": "CTNF",
    "submissionDate": "2009-01-29",
}


def test_office_action_entry_cites_the_application_page_with_code_and_date():
    entry = _build_oa_entry(_OA_DOC, _OA_BODY, "all", "11752072")
    assert entry["cite_as"] == (
        "[CTNF 2009-01-29, application 11/752,072]"
        "(https://patentcenter.uspto.gov/applications/11752072)"
    )
    assert cl.PERSISTENT_LINK_MARKER not in entry["cite_as"]


def test_office_action_entry_without_an_application_number_is_unchanged():
    """The 3-argument call is still valid; cite_as is simply absent."""
    entry = _build_oa_entry(_OA_DOC, _OA_BODY, "all")
    assert "cite_as" not in entry


def test_rejection_rows_are_stamped_from_their_own_keys():
    rows = [
        {"doc_code": "CTNF", "submission_date": "2018-03-14"},
        {"doc_code": "CTFR", "submission_date": "2018-11-02"},
        {"doc_code": "", "submission_date": ""},
    ]
    assert cl.attach_document_cite_as(
        rows, "15992176", code_keys=("doc_code",), date_keys=("submission_date",)
    ) == 3
    assert rows[0]["cite_as"].startswith("[CTNF 2018-03-14, application 15/992,176]")
    # A row with neither code nor date still cites the application it belongs to.
    assert rows[2]["cite_as"].startswith("[Document, application 15/992,176]")


def test_document_bag_rows_are_stamped_from_the_documentbag_key_names():
    rows = [{"documentCode": "NOA", "officialDate": "2015-06-01T00:00:00Z"}]
    assert cl.attach_document_cite_as(
        rows, "14171705",
        code_keys=("documentCode", "documentCodeDescriptionText"),
        date_keys=("officialDate",),
    ) == 1
    assert rows[0]["cite_as"] == (
        "[NOA 2015-06-01, application 14/171,705]"
        "(https://patentcenter.uspto.gov/applications/14171705)"
    )


def test_solr_single_element_lists_are_unwrapped():
    rows = [{"doc_code": ["CTNF"], "submission_date": ["2018-03-14"]}]
    cl.attach_document_cite_as(
        rows, "15992176", code_keys=("doc_code",), date_keys=("submission_date",)
    )
    assert rows[0]["cite_as"].startswith("[CTNF 2018-03-14,")


# ===========================================================================
# Notes and slimming
# ===========================================================================

def test_both_envelope_notes_open_with_the_rule_and_say_what_is_not_a_citation():
    for note in (cl.CITATION_NOTE, cl.DOCUMENT_CITATION_NOTE):
        assert note.startswith("CITATIONS ARE LINKS.")
        assert "cite_as" in note
        assert "not a citation" in note
        # No em dashes in new prose (repo rule).
        assert "—" not in note
    assert "Google Patents" in cl.CITATION_NOTE
    assert "Patent Center" in cl.DOCUMENT_CITATION_NOTE
    assert "credentials" in cl.DOCUMENT_CITATION_NOTE


def test_envelope_note_blocks_are_absent_on_a_no_op():
    assert cl.citation_block([{"cite_as": "[x](https://e.invalid)"}], "N") == {"citation_note": "N"}
    assert cl.citation_block([{"doc_code": "CTNF"}], "N") == {}
    assert cl.citation_block(None, "N") == {}
    assert cl.single_citation_block("[x](https://e.invalid)", "N") == {
        "cite_as": "[x](https://e.invalid)", "citation_note": "N",
    }
    assert cl.single_citation_block(None, "N") == {}


def test_xml_publication_number_comes_only_from_the_publication_lane():
    """A guess would cite the wrong document: only `identifier_resolved_as`
    == 'publication' establishes that the caller's identifier IS a pre-grant
    publication number. Both printed forms normalize to the bare digits."""
    from patent_filewrapper_mcp.tools.document_tools import _resolved_publication_number

    assert _resolved_publication_number(
        {"identifier_resolved_as": "publication"}, "20010056539"
    ) == "20010056539"
    assert _resolved_publication_number(
        {"identifier_resolved_as": "publication"}, "US20010056539A1"
    ) == "20010056539"
    assert _resolved_publication_number({"identifier_resolved_as": "patent"}, "7971071") is None
    assert _resolved_publication_number({}, "11752072") is None


def test_cite_as_survives_the_response_guard_slim_list():
    """The nested documentBag/associatedDocuments projection is the only
    non-empty keep_fields list in the repo; slimming must not be what strips a
    row's only clickable field."""
    from patent_filewrapper_mcp.tools import _DOC_SLIM_FIELDS

    assert "cite_as" in _DOC_SLIM_FIELDS


_CITED_TOOLS = (
    "PFW_search_applications",
    "PFW_search_applications_minimal",
    "PFW_search_applications_balanced",
    "PFW_search_inventor",
    "PFW_search_inventor_minimal",
    "PFW_search_inventor_balanced",
    "PFW_get_family",
    "PFW_get_term_adjustment",
    "PFW_get_patent_or_application_xml",
    "PFW_get_oa_text",
    "PFW_get_oa_rejections",
    "PFW_get_application_documents",
)

_PROBE = (
    "from patent_filewrapper_mcp.main import mcp\n"
    "from fastmcp.tools import Tool\n"
    "comps = list(mcp.local_provider._components.values())\n"
    "tools = {c.name: c for c in comps if isinstance(c, Tool)}\n"
    "for name, tool in sorted(tools.items()):\n"
    "    d = tool.description or ''\n"
    "    print('T:%s:%s:%s' % (name, 'CITATIONS ARE LINKS' in d, tool.title == name))\n"
)


def test_the_rule_reaches_the_client_visible_tool_description():
    """FastMCP cuts a Google-style docstring at `Args:`, so a paragraph placed
    after that block never reaches the client. The paragraph is only useful if
    the model can read it, so assert the SERVER CONTRACT, not the source text.
    Also pins `title` == name, which the same registration path controls."""
    import os
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True, text=True, env={**os.environ}, timeout=180,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    seen = {}
    for line in result.stdout.splitlines():
        if line.startswith("T:"):
            _, name, cited, titled = line.split(":")
            seen[name] = (cited == "True", titled == "True")

    for name in _CITED_TOOLS:
        assert name in seen, f"{name} is not registered"
        cited, titled = seen[name]
        assert cited, f"{name}: the CITATIONS ARE LINKS paragraph is not in its description"
        assert titled, f"{name}: title drifted away from the tool name"


def test_guidance_carries_the_rule():
    from patent_filewrapper_mcp.guidance import get_guidance_sections

    overview = get_guidance_sections()["overview"]
    assert "CITATIONS ARE LINKS" in overview
    assert "cite_as" in overview
    assert "not** a citation" in overview or "not a citation" in overview
    assert "Documents & Transactions" in overview
