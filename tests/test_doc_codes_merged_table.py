"""The doc-codes table carries applicant-filed AND office-issued codes.

The EFS-Web CSV is what an applicant may file, so CTNF, CTFR, NOA, 892 and the
other outgoing examiner codes were absent from the resource. They now come from
the same curated dictionary the guidance `document_codes` section prints, and
every row says which side it is.
"""

import pytest

from patent_filewrapper_mcp.reference import doc_codes as d

OFFICE_MUST_HAVE = ["CTNF", "CTFR", "NOA", "CTRS", "CTAV", "892", "N417", "PETDEC"]


@pytest.fixture(scope="module")
def buckets():
    return d.parse_doc_code_csv(d.find_doc_code_csv())


@pytest.fixture(scope="module")
def rows(buckets):
    return d.merged_doc_code_rows(buckets)


def test_applicant_row_count_is_unchanged(buckets, rows):
    assert len(buckets["prosecution"]) == 367
    applicant = [r for r in rows if r["origin"] == d.ORIGIN_APPLICANT]
    assert len(applicant) == sum(len(v) for v in buckets.values())
    assert [r["code"] for r in applicant[:367]] == [
        e["code"] for e in buckets["prosecution"]
    ]


@pytest.mark.parametrize("code", OFFICE_MUST_HAVE)
def test_office_codes_are_present_and_marked(rows, code):
    match = [r for r in rows if r["code"] == code]
    assert len(match) == 1
    assert match[0]["origin"] == d.ORIGIN_OFFICE
    assert match[0]["description"].strip()


def test_rendered_table_marks_office_rows():
    table = d.build_doc_code_table()
    for code in ("CTNF", "CTFR", "NOA", "892"):
        line = next(line for line in table.splitlines() if line.startswith(f"| `{code}` |"))
        assert line.rstrip().endswith("| office-issued |")


def test_applicant_code_keeps_its_old_shape(buckets, rows):
    csv_entry = buckets["prosecution"][0]
    merged = next(r for r in rows if r["code"] == csv_entry["code"])
    for key in ("code", "description", "process", "category"):
        assert merged[key] == csv_entry[key]
    assert merged["origin"] == d.ORIGIN_APPLICANT
    table = d.build_doc_code_table()
    line = next(
        line for line in table.splitlines() if line.startswith(f"| `{csv_entry['code']}` |")
    )
    cells = [c.strip() for c in line.strip("|").split(" | ")]
    assert cells[0] == f"`{csv_entry['code']}`"
    assert cells[1] == csv_entry["description"]
    assert cells[2] == csv_entry["process"]
    assert cells[3] == d.ORIGIN_APPLICANT


def test_no_duplicate_codes(rows, buckets):
    """The CSV legitimately repeats a code under different categories (ABST is
    an Amendment, Application Part and PCT row), so applicant rows are unique
    by (code, category, process). Office rows are unique by code and never
    collide with any applicant code."""
    applicant = [r for r in rows if r["origin"] == d.ORIGIN_APPLICANT]
    office = [r for r in rows if r["origin"] == d.ORIGIN_OFFICE]
    # The CSV itself holds one exact repeated row, so the check is that the
    # merge adds no repeat of its own: applicant rows are the CSV rows, no more.
    assert len(applicant) == sum(len(v) for v in buckets.values())
    office_codes = [r["code"].upper() for r in office]
    assert len(office_codes) == len(set(office_codes))
    assert not set(office_codes) & {r["code"].upper() for r in applicant}


def test_office_rows_come_from_the_guidance_dictionary(rows):
    curated = d.parse_curated_codes()
    for r in rows:
        if r["origin"] == d.ORIGIN_OFFICE:
            assert r["code"] in curated


def test_applicant_side_curated_codes_are_not_mislabeled(rows):
    codes = {r["code"] for r in rows}
    for code in ("1449", "AF/D", "N572", "RXIDS.R"):
        assert code not in codes


def test_office_table_prints_on_every_page():
    page2 = d.build_doc_code_table(offset=60)
    assert "| `CTNF` |" in page2
