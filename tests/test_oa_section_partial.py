"""PFW_get_oa_text: a section excerpt that holds fewer rejection statements than
the full office action is labelled `section_partial` (2026-09-05).

Application 11/752,072's 2009-01-29 CTNF rejects claims 1, 2, 3, 11 and 24
under § 112 first paragraph AND claims 1-21 under § 112 second paragraph. A
caller who read section_returned="112" as "every § 112 ground" while holding
only one of them missed the other (incognito walkthrough run, 2026-09-05).

Since the 2026-10-11 port to the ODP Office Action API the excerpt is cut from
the full text at the office action's own "Claim Rejections - 35 USC § <n>"
heading (the API serves no section sub-documents), so a ground stated under a
different heading falls outside it. The entry counts the statements on both
sides and says so; nothing is dropped or re-sliced.
"""

from patent_filewrapper_mcp.api.office_action_client import extract_section_text
from patent_filewrapper_mcp.tools.oa_tools import _build_oa_entry, _count_section_rejections

BODY = (
    "DETAILED ACTION\n"
    "Claim Rejections - 35 USC § 112\n"
    "Claims 1, 2, 3, 11, 24 are rejected under 35 U.S.C. 112, first paragraph, "
    "as failing to comply with the written description requirement.\n"
    "Claims 1-21 are rejected under 35 U.S.C. 112, second paragraph, as being "
    "indefinite for failing to particularly point out the invention.\n"
    "Claim Rejections - 35 USC § 102\n"
    "Claims 1, 26, 27 are rejected under 35 U.S.C. 102(b) as being anticipated by Pavlin.\n"
    "Claims 16, 20-22 are rejected under 35 U.S.C. 103(a) as being unpatentable over Mathers.\n"
)

#: The second § 112 ground sits under its own non-standard heading, so the
#: "Claim Rejections - 35 USC § 112" excerpt carries only the first.
BODY_SPLIT_112 = (
    "DETAILED ACTION\n"
    "Claim Rejections - 35 USC § 112\n"
    "Claims 1, 2, 3, 11, 24 are rejected under 35 U.S.C. 112, first paragraph, "
    "as failing to comply with the written description requirement.\n"
    "Response to Arguments\n"
    "Applicant's arguments have been considered. Claims 1-21 are rejected under "
    "35 U.S.C. 112, second paragraph, as being indefinite.\n"
    "Conclusion\n"
    "Any inquiry concerning this communication should be directed to the examiner.\n"
)

_DOC = {"inventionTitle": "X", "documentCode": "CTNF", "submissionDate": "2009-01-29"}


def test_counter_reads_the_examiner_variants_and_does_not_bleed_across_sections():
    assert _count_section_rejections(BODY, "112") == 2
    assert _count_section_rejections(BODY, "102") == 1
    assert _count_section_rejections(BODY, "103") == 1
    # "1120" or "112(a)" style suffixes: the digit guard only blocks more digits
    assert _count_section_rejections("rejected under 35 USC § 112(a) as", "112") == 1
    assert _count_section_rejections("rejected under 35 U.S.C. 1120", "112") == 0
    assert _count_section_rejections("", "112") == 0


def test_partial_section_excerpt_is_labelled_with_counts():
    entry = _build_oa_entry(_DOC, BODY_SPLIT_112, "112")
    assert entry["section_returned"] == "112"
    assert entry["section_partial"] == {
        "rejections_in_excerpt": 1,
        "rejections_in_full_text": 2,
        "note": entry["section_partial"]["note"],
    }
    assert "PARTIAL § 112 EXCERPT" in entry["section_partial"]["note"]
    assert "section='all'" in entry["section_partial"]["note"]
    # The excerpt is the office action's own text, case preserved.
    assert entry["text"].startswith("Claim Rejections - 35 USC § 112")
    assert "first paragraph" in entry["text"]
    assert "second paragraph" not in entry["text"]


def test_complete_section_excerpt_carries_no_marker():
    entry = _build_oa_entry(_DOC, BODY, "112")
    assert entry["section_returned"] == "112"
    assert "section_partial" not in entry
    assert "first paragraph" in entry["text"] and "second paragraph" in entry["text"]
    # The § 112 excerpt stops at the next rejection heading.
    assert "Pavlin" not in entry["text"]


def test_full_body_fallback_carries_no_partial_marker():
    entry = _build_oa_entry(_DOC, BODY, "101")
    assert entry["section_returned"] == "all"
    assert "section_note" in entry
    assert "section_partial" not in entry
    assert entry["text"] == BODY


def test_missing_text_is_an_empty_entry_not_a_crash():
    entry = _build_oa_entry(_DOC, None, "103")
    assert entry["text"] == ""
    assert entry["section_returned"] == "all"


def test_section_cut_follows_a_heading_naming_two_sections():
    body = (
        "Claim Rejections - 35 USC § 102/103\n"
        "Claims 1-3 are rejected under 35 U.S.C. 103 as being unpatentable over A.\n"
        "Conclusion\n"
    )
    assert "unpatentable over A" in extract_section_text(body, "103")
    assert "unpatentable over A" in extract_section_text(body, "102")
    assert extract_section_text(body, "112") == ""
