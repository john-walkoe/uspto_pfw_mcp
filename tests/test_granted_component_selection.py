"""The granted-package component pick must prefer the complete document.

Amendment papers share the component's document code: on application
11/752,072 a 2-page replacement-paragraphs filing (2007-08-14) is coded
SPEC exactly like the 21-page original specification (2007-05-22), and the
API returns newest first. Taking documents[0] served the 2-page delta as
"the specification" (found live 2026-09-02). The rule under test: most PDF
pages wins, earliest officialDate breaks ties.
"""

from patent_filewrapper_mcp.api.enhanced_client import (
    _pdf_page_count,
    _select_complete_version,
)


def _doc(ident, date, pages):
    bag = []
    if pages is not None:
        bag = [{"mimeTypeIdentifier": "PDF", "pageTotalQuantity": pages}]
    return {
        "documentIdentifier": ident,
        "officialDate": date,
        "downloadOptionBag": bag,
    }


def test_complete_document_beats_newer_delta():
    # The live 11/752,072 shape: newest-first ordering, delta in front.
    docs = [
        _doc("AMENDMENT", "2007-08-14", 2),
        _doc("ORIGINAL", "2007-05-22", 21),
    ]
    assert _select_complete_version(docs)["documentIdentifier"] == "ORIGINAL"


def test_single_version_unchanged():
    docs = [_doc("ONLY", "2010-01-01", 7)]
    assert _select_complete_version(docs)["documentIdentifier"] == "ONLY"


def test_page_tie_breaks_to_earliest():
    docs = [
        _doc("LATER", "2012-06-01", 30),
        _doc("EARLIER", "2009-03-15", 30),
    ]
    assert _select_complete_version(docs)["documentIdentifier"] == "EARLIER"


def test_missing_page_counts_fall_back_to_earliest():
    # No PDF option on either: both count 0, earliest date wins.
    docs = [
        _doc("NEWER", "2015-01-01", None),
        _doc("OLDER", "2014-01-01", None),
    ]
    assert _select_complete_version(docs)["documentIdentifier"] == "OLDER"


def test_pdf_page_count_reads_the_pdf_option_only():
    doc = {
        "downloadOptionBag": [
            {"mimeTypeIdentifier": "XML", "pageTotalQuantity": 99},
            {"mimeTypeIdentifier": "PDF", "pageTotalQuantity": 21},
        ]
    }
    assert _pdf_page_count(doc) == 21
    assert _pdf_page_count({"downloadOptionBag": []}) == 0
