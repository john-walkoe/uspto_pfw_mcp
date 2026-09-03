"""H-2: unescaped third-party text reached innerHTML in three of four views.

`escapeHtml` existed inside FAMILY_VIEW_HTML only, and `ui/user_management_view.py`
had its own `esc()`. The search, XML and downloads views interpolated
`inventionTitle`, `firstApplicantName`, `examinerNameText` and claim text
directly. Those are applicant-authored free text that USPTO republishes
largely as filed, so they are attacker-influenceable by anyone willing to file
an application.

Structural checks: real rendering is validated manually in Claude Desktop via
tests/TEST_SUITE.md.
"""

import pytest

from patent_filewrapper_mcp.ui.views import (
    DOWNLOADS_HTML,
    FAMILY_VIEW_HTML,
    SEARCH_RESULTS_HTML,
    XML_VIEW_HTML,
)

ALL_VIEWS = {
    "search": SEARCH_RESULTS_HTML,
    "xml": XML_VIEW_HTML,
    "downloads": DOWNLOADS_HTML,
    "family": FAMILY_VIEW_HTML,
}


@pytest.mark.parametrize("html", ALL_VIEWS.values(), ids=ALL_VIEWS.keys())
def test_every_view_defines_the_escape_helper(html):
    assert "function escapeHtml(value)" in html


@pytest.mark.parametrize(
    "field",
    ["title", "applicant", "inventor", "examiner", "artUnit", "appNum",
     "patentNum", "filingDate"],
)
def test_search_card_escapes_applicant_authored_fields(field):
    assert f"escapeHtml({field})" in SEARCH_RESULTS_HTML
    # The one remaining bare use is inside a JS URL string handed to
    # app.openLink, not an HTML sink.
    bare = SEARCH_RESULTS_HTML.count("${" + field + "}")
    if field == "patentNum":
        assert bare == 1 and "patents.google.com/patent/US${patentNum}" in SEARCH_RESULTS_HTML
    else:
        assert bare == 0


def test_search_filter_pill_escapes_its_label():
    """Pill labels are examiner and applicant names from the result set."""
    assert "escapeHtml(label)" in SEARCH_RESULTS_HTML


def test_search_summary_bar_escapes_the_echoed_query():
    assert 'title="${escapeHtml(q)}"' in SEARCH_RESULTS_HTML
    assert "${q}" not in SEARCH_RESULTS_HTML


def test_xml_view_escapes_claim_text_and_meta_values():
    assert "escapeHtml(text)" in XML_VIEW_HTML
    assert "escapeHtml(claimsRaw)" in XML_VIEW_HTML
    assert "escapeHtml(val)" in XML_VIEW_HTML
    assert "${text}" not in XML_VIEW_HTML
    assert "${val}" not in XML_VIEW_HTML


@pytest.mark.parametrize("field", ["doc.proxy_url", "doc.app_number", "docType"])
def test_downloads_card_escapes_document_fields(field):
    assert f"escapeHtml({field})" in DOWNLOADS_HTML
    assert "${" + field + "}" not in DOWNLOADS_HTML


def test_downloads_card_escapes_the_type_class_attribute():
    """docType lands in class="${typeCls}", so a quote would break out."""
    assert "doc-type-${escapeHtml(docType)}" in DOWNLOADS_HTML


def test_family_view_sibling_interpolations_are_escaped():
    """The view that owned the helper still had two bare interpolations."""
    assert "escapeHtml(queried)" in FAMILY_VIEW_HTML
    assert "escapeHtml(filingDate)" in FAMILY_VIEW_HTML
    assert "${queried" not in FAMILY_VIEW_HTML.replace("${escapeHtml(queried)", "")
