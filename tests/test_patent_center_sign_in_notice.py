"""Patent Center is only readable signed in, and every surface says so.

A Patent Center link handed to a reader with no USPTO.gov account does not
error: it silently renders the site's own front page. The reader then believes
the citation was wrong. So both surfaces that hand out such a link carry the
same sentence — the JSON `citation_note` the model reads, and the MCP App
panels that render an "Open in Patent Center" button.

The sentence is asserted verbatim so a reworded copy in one place cannot drift
away from the other.
"""

import pytest

from patent_filewrapper_mcp.util import citation_links as cl
from patent_filewrapper_mcp.ui.views import (
    FAMILY_VIEW_HTML,
    SEARCH_RESULTS_HTML,
    XML_VIEW_HTML,
)

SIGN_IN_SENTENCE = (
    "Patent Center shows an application only to a signed-in reader: without a "
    "free USPTO.gov account the link lands on its own front page rather than "
    "on the desired application."
)

#: The views that render a Patent Center button.
PATENT_CENTER_VIEWS = {
    "search": SEARCH_RESULTS_HTML,
    "family": FAMILY_VIEW_HTML,
    "xml": XML_VIEW_HTML,
}


@pytest.mark.parametrize("note_name", ["CITATION_NOTE", "DOCUMENT_CITATION_NOTE"])
def test_every_envelope_note_carries_the_sign_in_sentence(note_name):
    note = getattr(cl, note_name)
    assert SIGN_IN_SENTENCE in note
    assert cl.PATENT_CENTER_SIGN_IN_RULE in note
    # No em dashes in new prose (repo rule).
    assert "—" not in cl.PATENT_CENTER_SIGN_IN_RULE


def test_the_rule_tells_the_model_what_to_do_with_each_target():
    rule = cl.PATENT_CENTER_SIGN_IN_RULE
    assert "patentcenter.uspto.gov" in rule
    assert "Google Patents" in rule
    assert "no account" in rule


@pytest.mark.parametrize(
    "html", PATENT_CENTER_VIEWS.values(), ids=PATENT_CENTER_VIEWS.keys()
)
def test_every_patent_center_view_shows_the_notice(html):
    assert SIGN_IN_SENTENCE in html
    assert 'class="pc-note"' in html
    assert ".pc-note {" in html


@pytest.mark.parametrize(
    "html", PATENT_CENTER_VIEWS.values(), ids=PATENT_CENTER_VIEWS.keys()
)
def test_the_existing_button_text_is_untouched(html):
    assert "Open in Patent Center →" in html
