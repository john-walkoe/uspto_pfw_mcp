"""The design-patent routing note: it fires on design records and ONLY on them.

A design patent's claim is one sentence ending "as shown and described", so a
model that reads the claim and answers has described nothing. The note points
it at the DRW documents. The gate is the point: a note attached to every
response trains the consuming model to ignore it, so these tests pin both
halves, the firing and the silence.
"""

import pytest

from patent_filewrapper_mcp.util.design_patents import (
    DESIGN_DOCUMENTS_NOTE,
    DESIGN_DRAWINGS_NOTE,
    attach_design_note,
    claims_ornamental_design,
    is_design_application,
    is_design_patent_number,
    iter_claim_texts,
    looks_like_design_record,
)


# --- the signals -------------------------------------------------------------

@pytest.mark.parametrize("value", ["29328018", "29/328,018", "29201636"])
def test_design_series_application_numbers(value):
    assert is_design_application(value) is True


@pytest.mark.parametrize("value", ["11752072", "12/950,321", "16816197", "", None, "29"])
def test_utility_and_junk_application_numbers_are_not_design(value):
    assert is_design_application(value) is False


@pytest.mark.parametrize("value", ["D618677", "D618,677", "USD618677"])
def test_design_patent_numbers(value):
    assert is_design_patent_number(value) is True


@pytest.mark.parametrize("value", ["7971071", "8539047", "", None, "RE51034"])
def test_utility_patent_numbers_are_not_design(value):
    assert is_design_patent_number(value) is False


def test_ornamental_claim_text_is_a_signal():
    assert claims_ornamental_design(
        ["The ornamental design for an electronic device, as shown and described."]
    ) is True
    assert claims_ornamental_design(["1. An apparatus comprising a housing 10..."]) is False


def test_claim_texts_are_read_out_of_any_of_the_shapes():
    as_list_of_dicts = {"claims": [{"text": "The ornamental design for a candy."}]}
    as_list_of_strings = {"claims": ["The ornamental design for a candy."]}
    as_one_string = {"claims": "The ornamental design for a candy."}
    for shape in (as_list_of_dicts, as_list_of_strings, as_one_string):
        assert claims_ornamental_design(iter_claim_texts(shape)) is True
    assert list(iter_claim_texts(None)) == []
    assert list(iter_claim_texts({"claims": None})) == []


def test_any_one_signal_is_enough():
    assert looks_like_design_record(application_number="29328018") is True
    assert looks_like_design_record(patent_number="D618677") is True
    assert looks_like_design_record(claim_texts=["the ornamental design for a lamp"]) is True
    assert looks_like_design_record(
        application_number="11752072", patent_number="7971071",
        claim_texts=["1. An apparatus comprising..."],
    ) is False


def test_attach_never_overwrites_an_existing_note():
    result = {"design_patent_note": "already here"}
    attach_design_note(result, DESIGN_DRAWINGS_NOTE)
    assert result["design_patent_note"] == "already here"


# --- the note text itself ----------------------------------------------------

@pytest.mark.parametrize("note", [DESIGN_DRAWINGS_NOTE, DESIGN_DOCUMENTS_NOTE])
def test_each_note_names_the_download_tool_and_says_not_to_ocr(note):
    """The note has to be actionable on its own: a model that reads only this
    sentence must know which tool hands the sheets over."""
    assert "PFW_get_document_download" in note
    assert "reference numerals" in note


def test_the_xml_note_states_the_line_rule():
    lowered = DESIGN_DRAWINGS_NOTE.lower()
    assert "solid" in lowered and "broken" in lowered
    assert "document_code='DRW'" in DESIGN_DRAWINGS_NOTE


# --- the surfaces that carry it ----------------------------------------------

def test_guidance_holds_the_rule_once():
    """One authoritative home: the docstrings and the return notes point at
    the rule, the guidance document states it."""
    from patent_filewrapper_mcp.guidance import get_guidance_sections

    sections = get_guidance_sections()
    holders = [
        name for name, text in sections.items()
        if "as shown and described" in text and "document_code='DRW'" in text
    ]
    assert holders, "no guidance section carries the design-patent rule"
    documents = sections["documents"]
    assert "design_patent_note" in documents


def test_the_xml_note_rides_the_failure_path_too():
    """Design applications commonly have no XML, and a bare 404 reads as
    'nothing here' when the whole patent is in the DRW document."""
    from patent_filewrapper_mcp.tools.document_tools import _attach_xml_design_note

    not_found = {
        "error": True, "success": False, "status_code": 404,
        "message": "No application XML available",
        "identifier_input": "29/328,018",
        "identifier_resolved_as": "application",
    }
    _attach_xml_design_note(not_found)
    assert "document_code='DRW'" in not_found["design_patent_note"]

    utility_not_found = {**not_found, "identifier_input": "11/752,072"}
    utility_not_found.pop("design_patent_note", None)
    _attach_xml_design_note(utility_not_found)
    assert "design_patent_note" not in utility_not_found


def test_the_documents_note_needs_both_a_design_series_and_a_drawing():
    from patent_filewrapper_mcp.tools.document_tools import _design_documents_note

    drw = {"documentCode": "DRW"}
    clm = {"documentCode": "CLM"}
    assert _design_documents_note("29328018", [clm, drw]) != {}
    assert _design_documents_note("29328018", [clm]) == {}
    assert _design_documents_note("11752072", [drw]) == {}
    assert _design_documents_note(None, []) == {}


def test_only_the_series_google_patents_actually_serves_get_a_link():
    """Probed 2026-09-20: USD618677, USRE45123, USPP12345, USH1234 and
    UST100001 answer 200; USAI00001 answers 404. A recognised-but-unhosted
    series returns None, because a missing link is a smaller failure than a
    dead one -- and the prefix stays recognised so its letters are never
    mistaken for part of the number and retargeted at a live patent."""
    from patent_filewrapper_mcp.util.citation_links import (
        google_patents_url,
        patent_series_prefix,
    )

    assert google_patents_url("D618677").endswith("USD618677")
    assert google_patents_url("RE51034").endswith("USRE51034")
    assert google_patents_url("PP12345").endswith("USPP12345")
    assert google_patents_url("8539047").endswith("US8539047")

    for unhosted in ("AI00001", "X00001"):
        assert patent_series_prefix(unhosted) in {"AI", "X"}
        assert google_patents_url(unhosted) is None
