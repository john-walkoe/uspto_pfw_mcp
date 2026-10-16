"""The free-text `query` keeps its grouping parentheses (2026-10-07).

`applicationNumberText:(11752072 OR 11478856)` was sent with the parentheses
escaped, so the group became literal text that matched other fields and
answered with application 16/409,911 (patent 11,478,856). The index is public
USPTO data with no per-user filter, so grouping is allowed; the other Lucene
specials stay escaped, and the convenience parameters are untouched.
"""

import pytest

from patent_filewrapper_mcp.api.helpers import escape_lucene_free_query
from patent_filewrapper_mcp.exceptions import ValidationError
from patent_filewrapper_mcp.tools.search_tools import _build_query_from_params


def test_grouping_parentheses_reach_the_query():
    assert (_build_query_from_params(query="applicationNumberText:(11752072 OR 11478856)")
            == "applicationNumberText:(11752072 OR 11478856)")


def test_a_free_query_binds_before_the_convenience_filters():
    query = _build_query_from_params(query="inventionTitle:drone OR inventionTitle:uav", art_unit="3664")
    # (field names are mapped to their applicationMetaData paths)
    assert query.startswith("(applicationMetaData.inventionTitle:drone OR applicationMetaData.inventionTitle:uav) AND ")
    assert query.endswith("groupArtUnitNumber:3664")


def test_other_specials_stay_escaped():
    assert escape_lucene_free_query("a && b || !c ^2 ~1 {x}") == r"a \&\& b \|\| \!c \^2 \~1 \{x\}"


@pytest.mark.parametrize("bad", ["applicationNumberText:(11752072 OR 11478856", "a) OR (b"])
def test_unbalanced_parentheses_are_refused_with_a_clear_message(bad):
    with pytest.raises(ValidationError, match="Unbalanced parentheses"):
        escape_lucene_free_query(bad)


def test_convenience_values_still_escape_parentheses():
    assert r"\(" in _build_query_from_params(applicant_name="Acme (USA)")
