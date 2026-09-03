"""Tests for the family (continuity) normalizer in api/helpers.py.

The ODP /continuity response is the trap this normalizer exists to defuse:
either bag can be ABSENT, so "no parentContinuityBag" is a real answer ("this
application claims no earlier US benefit") and must never read as a failed
lookup or as "no family". The other trap is root-finding — the dead helper this
replaced took parentContinuityBag[0] as the family root, which is neither the
only parent nor the earliest one.

Fixture shapes are copied from live ODP responses (14104993 / 14853719).
"""

from patent_filewrapper_mcp.api.helpers import (
    build_family_graph,
    extract_patent_families,
    normalize_foreign_priority,
)


def _parent_entry(parent: str, child: str, code: str = "DIV", **overrides) -> dict:
    entry = {
        "parentApplicationStatusCode": 150,
        "firstInventorToFileIndicator": False,
        "claimParentageTypeCode": code,
        "claimParentageTypeCodeDescriptionText": "is a Division of",
        "parentApplicationStatusDescriptionText": "Patented Case",
        "parentApplicationNumberText": parent,
        "parentApplicationFilingDate": "2013-12-12",
        "childApplicationNumberText": child,
        "parentPatentNumber": "9362380",
    }
    entry.update(overrides)
    return entry


def _child_entry(parent: str, child: str, code: str = "CON", **overrides) -> dict:
    entry = {
        "firstInventorToFileIndicator": False,
        "childApplicationStatusDescriptionText": "Patented Case",
        "claimParentageTypeCode": code,
        "childApplicationStatusCode": 150,
        "claimParentageTypeCodeDescriptionText": "is a Continuation of",
        "childPatentNumber": "9704967",
        "parentApplicationNumberText": parent,
        "childApplicationFilingDate": "2015-09-14",
        "childApplicationNumberText": child,
    }
    entry.update(overrides)
    return entry


def _record(app: str, parents=None, children=None) -> dict:
    """One get_continuity() success response. `None` means the bag was ABSENT."""
    return {
        "success": True,
        "application_number": app,
        "parent_continuity_bag": parents or [],
        "child_continuity_bag": children or [],
        "parent_bag_present": parents is not None,
        "child_bag_present": children is not None,
    }


def _node(graph: dict, app: str) -> dict:
    return next(n for n in graph["nodes"] if n["application_number"] == app)


def test_both_bags_present():
    graph = build_family_graph(
        "14104993",
        [_record(
            "14104993",
            parents=[_parent_entry("13000001", "14104993", code="CIP")],
            children=[_child_entry("14104993", "14853719")],
        )],
    )

    assert graph["parents"] == ["13000001"]
    assert graph["children"] == ["14853719"]
    assert graph["roots"] == ["13000001"]
    assert graph["counts"]["nodes"] == 3
    assert graph["counts"]["edges"] == 2
    # No emptiness note fires when both directions have content.
    assert graph["notes"] == [
        "foreign_priority: none — USPTO reports no foreign priority claim for 14104993."
    ]

    relations = {(e["parent_app"], e["child_app"]): e for e in graph["edges"]}
    cip = relations[("13000001", "14104993")]
    assert cip["relation_type"] == "CIP"
    assert cip["claim_parentage_type_code"] == "CIP"
    assert cip["description"] == "is a Division of"
    con = relations[("14104993", "14853719")]
    assert con["relation_type"] == "CON"

    assert _node(graph, "14104993")["is_queried"] is True
    child = _node(graph, "14853719")
    assert child["patent_number"] == "9704967"
    assert child["filing_date"] == "2015-09-14"
    assert child["status"] == "Patented Case"
    assert child["status_code"] == 150


def test_child_only_response_says_no_parents_explicitly():
    graph = build_family_graph(
        "14104993",
        [_record("14104993", parents=None, children=[_child_entry("14104993", "14853719")])],
    )

    assert graph["parents"] == []
    assert graph["children"] == ["14853719"]
    # With no parents the queried application is its own earliest ancestor.
    assert graph["roots"] == ["14104993"]

    parent_note = next(n for n in graph["notes"] if n.startswith("parents:"))
    assert "no parentContinuityBag" in parent_note
    assert "not missing data" in parent_note
    assert not any(n.startswith("children:") for n in graph["notes"])


def test_parent_only_response_says_no_children_explicitly():
    graph = build_family_graph(
        "14853719",
        [_record("14853719", parents=[_parent_entry("14104993", "14853719")], children=None)],
    )

    assert graph["parents"] == ["14104993"]
    assert graph["children"] == []
    assert graph["roots"] == ["14104993"]

    child_note = next(n for n in graph["notes"] if n.startswith("children:"))
    assert "no childContinuityBag" in child_note
    assert "not missing data" in child_note
    assert not any(n.startswith("parents:") for n in graph["notes"])


def test_empty_response_reports_both_directions():
    graph = build_family_graph("15992176", [_record("15992176", parents=None, children=None)])

    assert graph["parents"] == []
    assert graph["children"] == []
    assert graph["edges"] == []
    assert graph["roots"] == ["15992176"]
    assert [n["application_number"] for n in graph["nodes"]] == ["15992176"]
    assert any(n.startswith("parents:") for n in graph["notes"])
    assert any(n.startswith("children:") for n in graph["notes"])


def test_empty_bag_present_is_reported_differently_from_absent_bag():
    graph = build_family_graph("15992176", [_record("15992176", parents=[], children=[])])

    parent_note = next(n for n in graph["notes"] if n.startswith("parents:"))
    assert "parentContinuityBag was empty" in parent_note
    assert "no parentContinuityBag" not in parent_note


def test_root_walk_goes_past_first_parent_entry():
    """The earliest ancestor is 100000001, reached by walking; the naive
    parentContinuityBag[0] answer would have been 30000003."""
    graph = build_family_graph(
        "40000004",
        [
            _record("40000004", parents=[
                # Deliberately NOT the earliest, and listed first.
                _parent_entry("30000003", "40000004", code="CON"),
                _parent_entry("20000002", "40000004", code="CIP"),
            ]),
            _record("30000003", parents=[_parent_entry("20000002", "30000003")]),
            _record("20000002", parents=[_parent_entry("100000001", "20000002")]),
            _record("100000001", parents=None, children=[
                _child_entry("100000001", "20000002"),
            ]),
        ],
    )

    assert graph["parents"] == ["20000002", "30000003"]
    assert graph["roots"] == ["100000001"]
    assert graph["nodes"][0]["application_number"] == "100000001"


def test_cyclic_continuity_data_terminates():
    graph = build_family_graph(
        "20000002",
        [
            _record("20000002", parents=[_parent_entry("30000003", "20000002")]),
            _record("30000003", parents=[_parent_entry("20000002", "30000003")]),
        ],
    )

    # Malformed data: every node has a parent, so no root exists — but the walk
    # still returns rather than spinning.
    assert graph["roots"] == []
    assert graph["counts"]["edges"] == 2


def test_foreign_priority_normalized_and_flagged():
    bag = [{"filingDate": "2012-12-19", "applicationNumberText": "1262321", "ipOfficeName": "FRANCE"}]

    assert normalize_foreign_priority(bag) == [
        {"country": "FRANCE", "application_number": "1262321", "filing_date": "2012-12-19"}
    ]

    graph = build_family_graph("14853719", [_record("14853719")], foreign_priority_bag=bag)
    assert graph["foreign_priority"] == normalize_foreign_priority(bag)
    assert graph["counts"]["foreign_priority"] == 1
    assert not any(n.startswith("foreign_priority:") for n in graph["notes"])


def test_foreign_priority_opt_out_is_not_an_absence_claim():
    graph = build_family_graph(
        "14853719", [_record("14853719")], foreign_priority_requested=False
    )
    note = next(n for n in graph["notes"] if n.startswith("foreign_priority:"))
    assert "not requested" in note

    graph = build_family_graph(
        "14853719", [_record("14853719")], foreign_priority_available=False
    )
    note = next(n for n in graph["notes"] if n.startswith("foreign_priority:"))
    assert "unavailable" in note


def test_application_numbers_are_normalized_across_formats():
    graph = build_family_graph(
        "14853719",
        [_record("14/853,719", parents=[
            _parent_entry("14/104,993", "14/853,719"),
        ])],
    )

    assert graph["parents"] == ["14104993"]
    assert graph["edges"][0]["child_app"] == "14853719"


def test_extract_patent_families_keys_on_earliest_ancestor():
    """The repaired grouping helper must not key on parentContinuityBag[0]."""
    applications = [
        {
            "applicationNumberText": "40000004",
            "parentContinuityBag": [
                {"parentApplicationNumberText": "30000003",
                 "childApplicationNumberText": "40000004"},
            ],
        },
        {
            "applicationNumberText": "30000003",
            "parentContinuityBag": [
                {"parentApplicationNumberText": "20000002",
                 "childApplicationNumberText": "30000003"},
            ],
        },
        {
            "applicationNumberText": "20000002",
            "childContinuityBag": [
                {"parentApplicationNumberText": "20000002",
                 "childApplicationNumberText": "30000003"},
            ],
        },
    ]

    families = extract_patent_families(applications)

    assert list(families) == ["20000002"]
    assert len(families["20000002"]) == 3
