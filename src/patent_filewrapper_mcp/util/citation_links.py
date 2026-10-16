"""`cite_as`: a ready-made markdown link on every citable record.

Why this module exists (2026-09-05)
-----------------------------------
A twelve-prompt walkthrough of this suite produced answers that cited office
actions by date and claim numbers by number, with no link anywhere, because
the tool JSON carried none. The MCP App panels build Patent Center and Google
Patents links client-side (see `ui/views.py`), but the JSON return paths the
model reads never did, so a reader could not click through to the record an
assertion rested on.

The fix is the one the EDGAR server settled on: every citable record carries
`cite_as`, a markdown link whose LABEL names what the record is and whose
TARGET is the public record, plus a `citation_note` on the envelope telling
the model to paste it after the sentence it supports.

URL patterns
------------
Only two public forms are emitted, both probed live 2026-09-05 with
`curl -s -o /dev/null -w "%{http_code}" -L <url>`:

  https://patents.google.com/patent/US7971071        -> 200  (patent number)
  https://patents.google.com/patent/US20010056539    -> 200  (publication number)
  https://patentcenter.uspto.gov/applications/11752072 -> 200 (8-digit serial,
      no slash and no comma; the form ui/views.py already opens from the panels)

Do not invent a third form. USPTO publishes no per-document public URL for a
file-wrapper document, so an office action or a documentBag row cites the
APPLICATION's Patent Center page and the note says where to look once there.

NEVER cite this server's own persistent document links. They are capability
URLs minted for one reader, not public records, and pasting one into an answer
hands out a credential. `no_persistent_link` is the guard, and
`tests/test_citation_links.py` fails the build if any shipped target carries
one.
"""

from typing import Any, Dict, Iterable, List, Optional

#: Substring that marks this server's own capability links (proxy/server.py).
#: A citation target containing it is a credential leak, not a citation.
PERSISTENT_LINK_MARKER = "/document/persistent/"

_GOOGLE_PATENTS = "https://patents.google.com/patent/US{number}"
_PATENT_CENTER = "https://patentcenter.uspto.gov/applications/{serial}"


# ---------------------------------------------------------------------------
# Envelope notes
# ---------------------------------------------------------------------------

_BASE_NOTE = (
    "CITATIONS ARE LINKS. Every record here carries `cite_as`, a ready-made "
    "markdown link: the label names what the record is, the target is the "
    "public record. When you quote a record, rely on it, or put it in a table "
    "or a memo, paste its cite_as after the sentence it supports. A footnote "
    "number, a date, a document code or a claim number with no link is not a "
    "citation in this corpus: the reader has to be able to click through to "
    "the source."
)

_PUBLIC_RECORD_RULE = (
    " Granted patents link to Google Patents; everything else links to the "
    "application's Patent Center page."
)

_NO_DOCUMENT_URL_RULE = (
    " USPTO publishes no public per-document URL, so each cite_as opens the "
    "APPLICATION in Patent Center; the document itself is under Documents & "
    "Transactions there, by date and document code. Never cite this server's "
    "own persistent document links: those are credentials, not public records."
)

#: Patent Center is not a public page: it renders an application only to a
#: signed-in reader. A reader handed a bare patentcenter.uspto.gov link with no
#: account lands on the site's own front page and concludes the citation was
#: wrong, so every note that can hand out such a link says so, and says that
#: Google Patents carries no such condition.
PATENT_CENTER_SIGN_IN_RULE = (
    " Patent Center shows an application only to a signed-in reader: without a "
    "free USPTO.gov account the link lands on its own front page rather than on "
    "the desired application. So whenever you paste a cite_as whose target is "
    "patentcenter.uspto.gov, say in the same breath that opening it needs a "
    "free USPTO.gov account; a Google Patents link needs no account and needs "
    "no such warning."
)

#: For search, family, term-adjustment and XML envelopes.
CITATION_NOTE = _BASE_NOTE + _PUBLIC_RECORD_RULE + PATENT_CENTER_SIGN_IN_RULE

#: For office-action and documentBag envelopes.
DOCUMENT_CITATION_NOTE = _BASE_NOTE + _NO_DOCUMENT_URL_RULE + PATENT_CENTER_SIGN_IN_RULE


# ---------------------------------------------------------------------------
# Number formatting
# ---------------------------------------------------------------------------

def _digits(value: Any) -> str:
    """Every digit in the value, in order. Raw filter only: a kind code has to
    be removed before this runs (see `_patent_digits`), or its digit is kept."""
    if value is None:
        return ""
    return "".join(ch for ch in str(value) if ch.isdigit())


def _patent_digits(value: Any) -> str:
    """Digits of a patent or publication number, kind code removed.

    'US 7,971,071 B2' -> '7971071'; 'US20010056539A1' -> '20010056539'.
    A trailing letter-plus-digit kind code is dropped BEFORE the digit filter,
    or its digit would be glued onto the number.
    """
    if value is None:
        return ""
    text = str(value).strip().upper()
    if not text:
        return ""
    # Trailing kind code: A1, B2, P3, S1 ...
    if len(text) >= 2 and text[-1].isdigit() and text[-2].isalpha():
        text = text[:-2]
    return _digits(text)


#: Leading series letters that are PART of a US patent number, not a kind
#: code. Dropping one does not degrade a citation, it retargets it: patent
#: D618,677 is Apple's iPhone design and patent 618,677 is an 1899 grant, and
#: https://patents.google.com/patent/US618677 served the second one under the
#: first one's label until 2026-09-20.
#:
#: Every prefix here is RECOGNISED so it is never silently stripped, but only
#: the ones Google Patents actually serves get a link; see
#: `_UNLINKABLE_SERIES`. Probed 2026-09-20: USD618677, USRE45123, USPP12345,
#: USH1234 and UST100001 all answer 200.
_PATENT_SERIES_PREFIXES = ("RE", "PP", "AI", "D", "H", "T", "X")

#: Recognised series that Google Patents does NOT host, so no URL is built for
#: them. USAI00001 answers 404 (probed 2026-09-20); AI is the 1838-1861
#: "Additional Improvement" series and X the pre-1836 unnumbered one, neither
#: of which can appear in a corpus that starts in 2002. They stay in the
#: prefix list above so the letters are never mistaken for part of the number
#: and retargeted at a live patent, which is the bug this whole block exists
#: to prevent -- a missing link is a smaller failure than a wrong one.
_UNLINKABLE_SERIES = frozenset({"AI", "X"})


def patent_series_prefix(value: Any) -> str:
    """The series letters leading a patent number, or '' for a utility number.

    'D618677' and 'USD618,677 S1' -> 'D'; '7971071' -> ''. A pre-grant
    publication ('US20010056539A1') has no series prefix.
    """
    text = str(value or "").strip().upper().replace(" ", "")
    for lead in ("US", "USPAT"):
        if text.startswith(lead) and len(text) > len(lead) and not text[len(lead)].isdigit():
            text = text[len(lead):]
            break
    for prefix in _PATENT_SERIES_PREFIXES:
        if text.startswith(prefix) and any(ch.isdigit() for ch in text[len(prefix):]):
            return prefix
    return ""


def format_patent_number(value: Any) -> str:
    """'7971071' -> '7,971,071'; 'D618677' -> 'D618,677' (display form).

    The series prefix is kept: it is part of the number a reader would look
    up, and a design patent printed without its D names a different patent.
    """
    digits = _patent_digits(value)
    if not digits:
        return ""
    return f"{patent_series_prefix(value)}{int(digits):,}"


def format_application_serial(value: Any) -> str:
    """'11752072' -> '11/752,072', the unambiguous printed serial form.

    Anything that is not exactly 8 digits comes back as the plain digits: the
    slash-comma shape is only defined for a standard serial.
    """
    digits = _digits(value)
    if len(digits) == 8:
        return f"{digits[:2]}/{digits[2:5]},{digits[5:]}"
    return digits


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

def google_patents_url(number: Any) -> Optional[str]:
    """Google Patents URL for a patent or pre-grant publication number.

    Probed 2026-09-05: US7971071 (patent) and US20010056539 (publication) both
    return 200 without a kind code.

    The series prefix is carried through (USD618677, USRE51034, USPP12345):
    Google Patents keys on it, so stripping it does not fail, it silently
    serves a DIFFERENT patent. Verified 2026-09-20 against D618,677.
    """
    digits = _patent_digits(number)
    if not digits:
        return None
    prefix = patent_series_prefix(number)
    if prefix in _UNLINKABLE_SERIES:
        return None
    return _GOOGLE_PATENTS.format(number=f"{prefix}{digits}")


def patent_center_url(application_number: Any) -> Optional[str]:
    """Patent Center application URL. Requires an 8-digit serial.

    Probed 2026-09-05: .../applications/11752072 returns 200. The path segment
    takes the bare digits, so a slash-comma serial is normalized first.
    """
    digits = _digits(application_number)
    if len(digits) != 8:
        return None
    return _PATENT_CENTER.format(serial=digits)


def no_persistent_link(url: Optional[str]) -> Optional[str]:
    """Drop a URL that is one of this server's own capability links.

    Belt and braces: nothing in this module can build one, but a caller that
    passes a proxy URL in should get no citation rather than a leaked link.
    """
    if url and PERSISTENT_LINK_MARKER in url:
        return None
    return url


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

def cite_as_link(label: Optional[str], url: Optional[str]) -> Optional[str]:
    """A markdown citation link, or None without a URL.

    Square brackets in the label would end the link text early, so they are
    replaced; whitespace is collapsed so a label never breaks the markdown.
    """
    url = no_persistent_link(url)
    if not url:
        return None
    text = " ".join(str(label or "source").split()).replace("[", "(").replace("]", ")")
    return f"[{text}]({url})"


def application_label(
    application_number: Any, patent_number: Any = None, publication_number: Any = None
) -> str:
    """The label naming a patent or application record.

    Granted: 'US 7,971,071 (application 11/752,072)'.
    Published, not granted: 'US 2001/0056539 (application 09/775,715)'.
    Neither: 'Application 11/752,072'.
    """
    serial = format_application_serial(application_number)
    patent = format_patent_number(patent_number)
    if patent:
        return f"US {patent} (application {serial})" if serial else f"US {patent}"
    publication = _patent_digits(publication_number)
    if publication:
        pub = f"{publication[:4]}/{publication[4:]}" if len(publication) == 11 else publication
        return f"US {pub} (application {serial})" if serial else f"US {pub}"
    return f"Application {serial}" if serial else "Application"


def application_cite_as(
    application_number: Any,
    patent_number: Any = None,
    publication_number: Any = None,
    prefer_patent_center: bool = False,
) -> Optional[str]:
    """`cite_as` for an application or patent record.

    Target: Google Patents when a patent number is known, else Google Patents
    for a known pre-grant publication number, else the application's Patent
    Center page. `prefer_patent_center=True` forces the Patent Center page even
    for a granted patent, for the tools whose subject is the prosecution record
    rather than the issued document.
    """
    url = None
    if not prefer_patent_center:
        url = google_patents_url(patent_number) or google_patents_url(publication_number)
    url = url or patent_center_url(application_number)
    return cite_as_link(
        application_label(application_number, patent_number, publication_number), url
    )


def document_label(
    application_number: Any, document_code: Any = None, document_date: Any = None
) -> str:
    """'CTNF 2009-01-29, application 11/752,072' — what the row IS.

    Either part may be missing; the label degrades to whatever is known.
    """
    serial = format_application_serial(application_number)
    code = " ".join(str(document_code or "").split())
    date = " ".join(str(document_date or "").split())[:10]
    head = " ".join(part for part in (code, date) if part) or "Document"
    return f"{head}, application {serial}" if serial else head


def document_cite_as(
    application_number: Any, document_code: Any = None, document_date: Any = None
) -> Optional[str]:
    """`cite_as` for one file-wrapper document (an office action, a documentBag
    row). USPTO publishes no public per-document URL, so the target is the
    APPLICATION's Patent Center page; DOCUMENT_CITATION_NOTE says where to look
    once it opens. The server's own persistent links are never emitted here.
    """
    return cite_as_link(
        document_label(application_number, document_code, document_date),
        patent_center_url(application_number),
    )


# ---------------------------------------------------------------------------
# Bulk attachment
# ---------------------------------------------------------------------------

def _metadata(record: Dict[str, Any]) -> Dict[str, Any]:
    meta = record.get("applicationMetaData")
    return meta if isinstance(meta, dict) else {}


def attach_application_cite_as(records: Optional[Iterable[Any]]) -> int:
    """Stamp `cite_as` on each USPTO search record. Returns how many were
    stamped. A record already carrying `cite_as` is left alone, and a record
    with no usable application number is skipped rather than given a guess."""
    stamped = 0
    for record in records or []:
        if not isinstance(record, dict) or record.get("cite_as") is not None:
            continue
        meta = _metadata(record)
        link = application_cite_as(
            record.get("applicationNumberText") or meta.get("applicationNumberText"),
            patent_number=meta.get("patentNumber") or record.get("patentNumber"),
            publication_number=(
                meta.get("earliestPublicationNumber") or record.get("earliestPublicationNumber")
            ),
        )
        if link:
            record["cite_as"] = link
            stamped += 1
    return stamped


def attach_document_cite_as(
    rows: Optional[Iterable[Any]],
    application_number: Any,
    code_keys: Iterable[str],
    date_keys: Iterable[str],
) -> int:
    """Stamp `cite_as` on each file-wrapper document row. Returns the count.

    `code_keys` / `date_keys` are tried in order because the three row shapes
    name the same two facts differently (documentBag uses documentCode /
    officialDate, the office-action tools' rows use doc_code / submission_date).
    """
    code_keys = list(code_keys)
    date_keys = list(date_keys)
    stamped = 0
    for row in rows or []:
        if not isinstance(row, dict) or row.get("cite_as") is not None:
            continue
        link = document_cite_as(
            application_number,
            _first_present(row, code_keys),
            _first_present(row, date_keys),
        )
        if link:
            row["cite_as"] = link
            stamped += 1
    return stamped


def citation_block(records: Optional[Iterable[Any]], note: str) -> Dict[str, str]:
    """`{"citation_note": note}` when at least one record carries `cite_as`,
    else `{}` — the same absent-on-a-no-op rule `_bounds` and `limit_clamped`
    follow, so an envelope never promises links it does not hold.

    Returned as a mergeable dict rather than set with an `if` on purpose: the
    tool bodies are already at the mccabe ceiling, and a citation must not be
    the branch that pushes one over.
    """
    for record in records or []:
        if isinstance(record, dict) and record.get("cite_as"):
            return {"citation_note": note}
    return {}


def single_citation_block(cite_as: Optional[str], note: str) -> Dict[str, str]:
    """`{"cite_as": ..., "citation_note": ...}` for an envelope that IS one
    record, or `{}` when no link could be built. Mergeable, for the same
    reason as `citation_block`."""
    if not cite_as:
        return {}
    return {"cite_as": cite_as, "citation_note": note}


def _first_present(row: Dict[str, Any], keys: List[str]) -> Any:
    """First non-empty value among `keys`, unwrapping the single-element lists
    the Solr-backed office-action datasets return."""
    for key in keys:
        value = row.get(key)
        if isinstance(value, list):
            value = value[0] if value else None
        if value:
            return value
    return None
