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
from typing import Dict, List

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
    "| Code | Description | Business Process |",
    "|------|-------------|------------------|",
)


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


def _code_table(rows: List[dict], limit: int = None) -> List[str]:
    lines = list(_TABLE_HEADER)
    shown = rows[:limit] if limit is not None else rows
    for entry in shown:
        lines.append(
            f"| `{entry['code']}` | {entry['description']} | {entry['process']} |"
        )
    if limit is not None and len(rows) > len(shown):
        lines.append("")
        lines.append(
            f"*Showing {len(shown)} of {len(rows)} prosecution document codes. "
            "The full USPTO EFS-Web Document Description List is linked above.*"
        )
    return lines


def render_doc_code_markdown(buckets: Dict[str, List[dict]]) -> str:
    """Render the parsed buckets as the decoder table both endpoints serve."""
    output = [
        "# USPTO Document Code Decoder Table",
        "",
        f"**Source**: [USPTO EFS-Web Document Description List]({_SOURCE_URL})",
        f"**Updated**: {_SOURCE_UPDATED}",
        "",
        "This table provides document codes used in USPTO patent prosecution, "
        "PTAB proceedings, and FPD petitions.",
        "",
        "## Common Prosecution Document Codes",
        "",
    ]

    prosecution = sorted(buckets["prosecution"], key=lambda entry: entry["code"])
    output.extend(_code_table(prosecution, _PROSECUTION_DISPLAY_LIMIT))

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
            "*This table is generated from the USPTO EFS-Web Document "
            "Description List and includes document codes used in patent "
            "prosecution, PTAB proceedings, and FPD petitions.*",
        ]
    )

    return "\n".join(output)


def build_doc_code_table(csv_path: str = None) -> str:
    """Parse and render in one call — what both endpoints actually want."""
    return render_doc_code_markdown(
        parse_doc_code_csv(csv_path or find_doc_code_csv())
    )
