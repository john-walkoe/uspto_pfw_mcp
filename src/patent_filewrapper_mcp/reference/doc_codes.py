"""One parser and one renderer for the USPTO document-code decoder table.

There were two copies (audit D-1): `main.read_doc_codes` behind the MCP
resource `uspto://pfw/doc-codes`, and `proxy/routes/reference.get_doc_codes`
behind `GET /doc-codes`. Both are live — the resource calls the proxy first
and falls back to its own copy — and they had drifted in four ways, so the
same CSV rendered differently depending on which endpoint a client hit:

  behaviour                    main.py     reference.py
  description truncation       100 chars   120 chars
  business-process truncation  80 chars    100 chars
  prosecution rows shown       50          60
  `|` escaped for markdown     NO          yes
  FPD category bucket          MISSING     present
  rows sorted by code          no          yes

The two on the left were defects, not preferences: an unescaped `|` in a USPTO
description breaks the markdown row it sits in, and without the FPD bucket
those codes were silently filed under "Common Prosecution Document Codes".
The proxy's values win.

Both copies also shared a latent bug: the bucket lists were built OUTSIDE the
encoding-retry loop but appended to inside it, so a decode failure partway
through a file left partial rows in place and the next encoding appended the
same rows again, emitting duplicates. `_parse_rows` builds its buckets locally
and returns them only on success, so a partial parse can never escape.
"""

import csv
import os
import re
from typing import Dict, List, Optional

_ENCODINGS = ("utf-8", "utf-8-sig", "latin1", "cp1252", "iso-8859-1")

_DESC_CAP = 120
_PROCESS_CAP = 100
_PROSECUTION_DISPLAY_LIMIT = 60

_SOURCE_URL = (
    "https://www.uspto.gov/patents/apply/filing-online/"
    "efs-info-document-description"
)
_SOURCE_UPDATED = "April 27, 2022"

_TABLE_HEADER = (
    "| Code | Description | Business Process | Origin |",
    "|------|-------------|------------------|--------|",
)

#: The two values of the `Origin` column / `origin` key.
ORIGIN_APPLICANT = "applicant-filed"
ORIGIN_OFFICE = "office-issued"


def _clean(value: str, cap: int) -> str:
    """Flatten, de-non-ASCII, truncate, then escape for a markdown cell."""
    value = value.replace("\n", " ").replace("\r", " ")
    value = "".join(char if ord(char) < 128 else "?" for char in value)
    if len(value) > cap:
        value = value[: cap - 3] + "..."
    # Escape LAST: truncating after escaping could cut a backslash off its pipe.
    return value.replace("|", "\\|")


def _parse_rows(csv_reader) -> Dict[str, List[dict]]:
    """Buckets built locally, so a mid-file failure yields nothing at all."""
    buckets: Dict[str, List[dict]] = {"prosecution": [], "ptab": [], "fpd": []}
    headers = None

    for row in csv_reader:
        if not headers:
            headers = row
            continue
        if len(row) < 4:
            continue

        category = row[0].strip()
        doc_code = row[3].strip()
        if not doc_code or doc_code == "DOC CODE":
            continue

        entry = {
            "code": doc_code,
            "description": _clean(row[1].strip(), _DESC_CAP),
            "process": _clean(row[2].strip(), _PROCESS_CAP),
            "category": category,
        }

        if "PTAB" in category:
            buckets["ptab"].append(entry)
        elif "FPD" in category or "Final Petition Decision" in category:
            buckets["fpd"].append(entry)
        else:
            buckets["prosecution"].append(entry)

    return buckets


def find_doc_code_csv() -> str:
    """Locate reference/Document_Descriptions_List.csv.

    Checked relative to the working directory first (how the server is
    normally started) and then relative to the package, which is what makes
    the resource work from an installed wheel.
    """
    cwd_path = os.path.join("reference", "Document_Descriptions_List.csv")
    if os.path.exists(cwd_path):
        return cwd_path

    package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    project_root = os.path.join(package_root, "..", "..")
    return os.path.join(project_root, "reference", "Document_Descriptions_List.csv")


def parse_doc_code_csv(csv_path: str) -> Dict[str, List[dict]]:
    """Return {'prosecution': [...], 'ptab': [...], 'fpd': [...]}.

    Raises:
        ValueError: if the file is missing or no encoding decodes it.
    """
    if not os.path.exists(csv_path):
        raise ValueError("Document_Descriptions_List.csv not found")

    for encoding in _ENCODINGS:
        try:
            with open(csv_path, "r", encoding=encoding) as handle:
                return _parse_rows(csv.reader(handle))
        except UnicodeDecodeError:
            continue

    raise ValueError(
        f"Unable to read {csv_path} with any of the attempted encodings: "
        f"{list(_ENCODINGS)}"
    )


# ---------------------------------------------------------------------------
# Lookup by code or prefix (2026-09-05)
# ---------------------------------------------------------------------------
#
# The decoder RESOURCE renders 60 of 367 prosecution rows, sorted by code, so
# it runs 136A..COVID-19 and stops. A reader who held CTAV, PETDEC, REM, N417
# or WFEE saw none of them and had no way forward: the only pointer offered was
# a link to uspto.gov (walkthrough follow-up, 2026-09-05).
#
# Two different gaps produced that, and only one of them is truncation:
#
#   * TRUNCATION. REM and WFEE are in the CSV, past row 60. Paging reaches them.
#   * ABSENCE. CTAV, PETDEC, N417 — and CTNF, CTFR and NOA, the three most
#     common codes in prosecution — are NOT in the CSV AT ALL. It is the
#     EFS-Web list of what an APPLICANT may file, so no outgoing examiner code
#     appears in it. No amount of paging reaches those.
#
# So the lookup reads BOTH sources: the curated table in
# `guidance.py::_get_document_codes_section`, whose codes were read live out of
# real documentBags, and the CSV. Curated wins on a conflict, which is the rule
# that section already states for itself.

#: A curated-table entry: `- **CODE** - description`, `- **CODE**: description`,
#: or several codes sharing one gloss: `- **NRES** / **NTC.A.NONCPL** - ...`.
_CURATED_LINE_RE = re.compile(
    r"^-\s+(?P<head>(?:\*\*[A-Z0-9][A-Z0-9./_-]*\*\*\s*(?:/\s*)?)+)(?:[-:—])\s*(?P<desc>.+)$"
)
_CURATED_CODE_RE = re.compile(r"\*\*([A-Z0-9][A-Z0-9./_-]*)\*\*")

#: Markdown emphasis carried into a plain-text gloss reads as noise.
_MARKDOWN_NOISE_RE = re.compile(r"\*\*|`")

CURATED_SOURCE = "curated (live documentBag, 2026-08-30)"
CSV_SOURCE = "USPTO EFS-Web Document Description List (2022-04-27)"


def _curated_section_text() -> str:
    """The curated decoder markdown, or "" if it cannot be loaded.

    Imported lazily: `guidance` is a package-root module and this one lives
    under `reference/`, so a module-level import would couple the two at import
    time for a function most callers never reach.

    `_get_document_codes_section` is called directly rather than through
    `get_guidance_sections()`, which builds every section including `limits` —
    and `limits` imports the HTTP client to read live budgets. Decoding a
    document code has no business dragging httpx in behind it.
    """
    try:
        from ..guidance import _get_document_codes_section

        return _get_document_codes_section() or ""
    except Exception:  # pragma: no cover - guidance is always importable
        return ""


def _joined_bullets(text: str) -> List[str]:
    """The section's bullets as whole logical lines.

    Several glosses wrap across source lines, the continuation indented under
    its bullet. Read line by line, CTAV decodes as "Advisory Action (PTOL-303)
    — the examiner's response to an after-final" and stops mid-clause, which
    reads as a truncation defect in the very fix meant to end one.
    """
    lines: List[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        is_continuation = (
            raw.startswith(("  ", "\t"))
            and not stripped.startswith(("-", "*", "#", "|"))
            and stripped
            and lines
            and lines[-1].startswith("- ")
        )
        if is_continuation:
            lines[-1] = f"{lines[-1]} {stripped}"
        else:
            lines.append(stripped)
    return lines


def parse_curated_codes(section_text: Optional[str] = None) -> Dict[str, str]:
    """`{CODE: description}` scraped from the curated decoder section.

    Scraped rather than duplicated on purpose: a second hand-maintained copy of
    these glosses is a copy that goes stale, and this section is already the
    repo's authority on the outgoing examiner codes. The format it depends on
    is pinned by tests/test_doc_code_lookup.py, which fails if a future edit
    changes the bullet shape.
    """
    text = _curated_section_text() if section_text is None else section_text
    found: Dict[str, str] = {}
    for line in _joined_bullets(text):
        match = _CURATED_LINE_RE.match(line)
        if not match:
            continue
        description = _MARKDOWN_NOISE_RE.sub("", match.group("desc")).strip()
        if not description:
            continue
        for code in _CURATED_CODE_RE.findall(match.group("head")):
            found.setdefault(code, description)
    return found


#: Headings of the curated decoder whose bullets are Office-issued. Matched by
#: substring so an emoji or punctuation change in the heading does not break it.
_OFFICE_HEADINGS = ("Examiner Communications", "Fees, Issue and Administrative")
#: A bold sub-heading inside the applicant block that introduces Office receipts.
_RECEIPT_SUBHEAD = "receipts"


def parse_curated_office_codes(section_text: Optional[str] = None) -> Dict[str, str]:
    """`{CODE: description}` for the curated codes the Office issues.

    Same source as `parse_curated_codes` (the guidance `document_codes`
    section), narrowed by the section the bullet sits in: the examiner
    communications block, the fees/issue/administrative block, and the
    filing-system receipts sub-block. Codes the decoder files under applicant
    responses, patent components or reexamination are left out, because the
    decoder does not say which side issued them and guessing would mislabel
    (1449, AF/D, N572 and the reexam third-party filings are applicant-side).
    """
    text = _curated_section_text() if section_text is None else section_text
    found: Dict[str, str] = {}
    in_office_block = False
    in_receipts = False
    for line in _joined_bullets(text):
        if line.startswith("#"):
            in_office_block = any(h in line for h in _OFFICE_HEADINGS)
            in_receipts = False
            continue
        if line.startswith("**") and line.rstrip().endswith(":**"):
            in_receipts = _RECEIPT_SUBHEAD in line.lower()
            continue
        if line == "---":
            in_office_block = False
            in_receipts = False
            continue
        if not (in_office_block or in_receipts):
            continue
        match = _CURATED_LINE_RE.match(line)
        if not match:
            continue
        description = _MARKDOWN_NOISE_RE.sub("", match.group("desc")).strip()
        if not description:
            continue
        for code in _CURATED_CODE_RE.findall(match.group("head")):
            found.setdefault(code, description)
    return found


def merged_doc_code_rows(
    buckets: Dict[str, List[dict]],
    office: Optional[Dict[str, str]] = None,
) -> List[dict]:
    """Applicant rows (every CSV bucket) plus Office-issued rows, one per code.

    Applicant rows keep their exact shape (`code`, `description`, `process`,
    `category`) and gain only `origin`. An Office row is added only for a code
    the CSV does not already hold, so no code appears twice and the applicant
    row count is the CSV's own.
    """
    if office is None:
        office = parse_curated_office_codes()
    rows: List[dict] = []
    seen = set()
    for key in ("prosecution", "ptab", "fpd"):
        for entry in buckets.get(key) or []:
            seen.add(entry["code"].upper())
            rows.append({**entry, "origin": ORIGIN_APPLICANT})
    for code in sorted(office):
        if code.upper() in seen:
            continue
        seen.add(code.upper())
        rows.append(
            {
                "code": code,
                "description": _escape_cell(office[code]),
                "process": "",
                "category": "",
                "origin": ORIGIN_OFFICE,
            }
        )
    return rows


def _escape_cell(value: str) -> str:
    return value.replace("\n", " ").replace("\r", " ").replace("|", "\\|")


def lookup_doc_codes(
    query: str,
    buckets: Optional[Dict[str, List[dict]]] = None,
    curated: Optional[Dict[str, str]] = None,
    limit: int = 25,
) -> List[dict]:
    """Every known entry whose code equals or starts with `query`.

    An EXACT match short-circuits: asking for `A` must not bury
    "Amendment/Req. Reconsideration-After Non-Final Reject" under the eighty
    codes that happen to begin with A. Only when nothing matches exactly does
    this widen to a prefix scan, which is what makes `PET` reach `PETDEC`.

    Each entry is `{code, description, source, category?, process?}`. `source`
    is load-bearing: a 2022 CSV gloss and a value read out of a live
    documentBag are not equally authoritative, and the caller is told which
    it got.
    """
    normalized = re.sub(r"[\s]", "", str(query or "")).upper()
    if not normalized:
        return []

    if buckets is None:
        buckets = parse_doc_code_csv(find_doc_code_csv())
    if curated is None:
        curated = parse_curated_codes()

    entries: Dict[str, dict] = {}
    # CSV first, curated second: setdefault would keep the CSV gloss, so the
    # curated pass overwrites deliberately. Curated wins, as that section says.
    for category, rows in sorted(buckets.items()):
        for row in rows:
            entries[row["code"].upper()] = {
                "code": row["code"],
                "description": row["description"].replace("\\|", "|"),
                "process": row.get("process", ""),
                "category": row.get("category", category),
                "source": CSV_SOURCE,
            }
    for code, description in curated.items():
        existing = entries.get(code.upper(), {})
        entries[code.upper()] = {
            "code": code,
            "description": description,
            "process": existing.get("process", ""),
            "category": existing.get("category", ""),
            "source": CURATED_SOURCE,
        }

    exact = entries.get(normalized)
    if exact:
        return [exact]
    matches = [
        entry for code, entry in sorted(entries.items()) if code.startswith(normalized)
    ]
    return matches[:limit]


def _code_table(
    rows: List[dict], limit: int = None, offset: int = 0
) -> List[str]:
    lines = list(_TABLE_HEADER)
    window = rows[offset:]
    shown = window[:limit] if limit is not None else window
    for entry in shown:
        lines.append(
            f"| `{entry['code']}` | {entry['description']} | {entry['process']} "
            f"| {entry.get('origin', ORIGIN_APPLICANT)} |"
        )
    if limit is not None and len(window) > len(shown):
        next_offset = offset + len(shown)
        lines.append("")
        # The old pointer here named only uspto.gov, which is not something the
        # model can call. Every line below is a call this server answers.
        lines.append(
            f"*Showing {offset + 1}-{next_offset} of {len(rows)} prosecution "
            f"document codes (sorted by code, so this window stops at "
            f"`{shown[-1]['code']}`).*"
        )
        lines.append("")
        lines.append("**To reach the rest:**")
        lines.append(
            "- The next page of this table: "
            f"`GET /doc-codes?offset={next_offset}` on the download proxy."
        )
        lines.append(
            "- One code or prefix: `PFW_get_guidance(section='document_codes', "
            "code='CTAV')`."
        )
        lines.append(
            "- The curated decoder: "
            "`PFW_get_guidance(section='document_codes')`."
        )
        lines.append("")
        lines.append(
            "The office-issued codes (`CTNF`, `CTFR`, `NOA`, `CTAV`, `CTRS`, "
            "`892`, `N417`, `PETDEC` and the rest) are in their own table above "
            "and are printed in full on every page. Whatever the source, the "
            "`documentCodeDescriptionText` returned beside a document in its own "
            "documentBag outranks both."
        )
    return lines


def render_doc_code_markdown(
    buckets: Dict[str, List[dict]], offset: int = 0
) -> str:
    """Render the parsed buckets as the decoder table both endpoints serve.

    `offset` pages the prosecution table. The PTAB and FPD tables are short
    enough to print whole and are unaffected.
    """
    output = [
        "# USPTO Document Code Decoder Table",
        "",
        f"**Source**: [USPTO EFS-Web Document Description List]({_SOURCE_URL}) "
        "(applicant-filed) and the curated examiner decoder (office-issued)",
        f"**Updated**: {_SOURCE_UPDATED}",
        "",
        "This table provides document codes used in USPTO patent prosecution, "
        "PTAB proceedings, and FPD petitions. Every row carries an `Origin`: "
        f"`{ORIGIN_APPLICANT}` rows come from the USPTO EFS-Web list of what an "
        f"applicant may file; `{ORIGIN_OFFICE}` rows are the outgoing examiner "
        "and USPTO papers (office actions, allowances, citations, receipts, "
        "petition decisions), which that list does not contain, taken from the "
        "curated examiner decoder, read from live documentBags on 2026-08-30.",
        "",
    ]

    office = [
        row
        for row in merged_doc_code_rows(buckets)
        if row["origin"] == ORIGIN_OFFICE
    ]
    if office:
        output.extend(["## Office-Issued Document Codes (Examiner and USPTO)", ""])
        output.extend(_code_table(office))
        output.append("")

    output.extend(["## Common Prosecution Document Codes (Applicant-Filed)", ""])

    prosecution = sorted(buckets["prosecution"], key=lambda entry: entry["code"])
    offset = max(0, int(offset or 0))
    output.extend(
        _code_table(prosecution, _PROSECUTION_DISPLAY_LIMIT, offset=offset)
    )

    for key, heading in (
        ("ptab", "## PTAB (Patent Trial and Appeal Board) Document Codes"),
        ("fpd", "## FPD (Final Petition Decision) Document Codes"),
    ):
        rows = buckets.get(key) or []
        if not rows:
            continue
        output.extend(["", heading, ""])
        output.extend(_code_table(sorted(rows, key=lambda entry: entry["code"])))

    output.extend(
        [
            "",
            "## Quick Reference - Most Common Codes",
            "",
            "| Code | Document Type |",
            "|------|---------------|",
            "| `A...` | Amendment/Request for Reconsideration-After Non-Final "
            "Rejection |",
            "| `A.PE` | Preliminary Amendment |",
            "| `A.NE` | Response After Final Action |",
            "| `SPEC` | Specification |",
            "| `CLM` | Claims |",
            "| `DRW` | Drawings (black and white line drawings) |",
            "| `N/AP` | Notice of Appeal Filed |",
            "| `AP.B` | Appeal Brief Filed |",
            "| `APRB` | Reply Brief Filed |",
            "| `PA..` | Power of Attorney |",
            "| `IDS` | Information Disclosure Statement |",
            "",
            "---",
            "*Applicant-filed rows are generated from the USPTO EFS-Web "
            "Document Description List (patent prosecution, PTAB proceedings "
            "and FPD petitions); office-issued rows come from the curated "
            "examiner decoder.*",
        ]
    )

    return "\n".join(output)


def build_doc_code_table(csv_path: str = None, offset: int = 0) -> str:
    """Parse and render in one call — what both endpoints actually want."""
    return render_doc_code_markdown(
        parse_doc_code_csv(csv_path or find_doc_code_csv()), offset=offset
    )
