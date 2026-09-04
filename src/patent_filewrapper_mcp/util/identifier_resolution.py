"""Resolve a user-supplied patent identifier to an application number, and SAY
which lane answered.

Why this module exists (OPEN_ITEMS #9, 2026-08-30)
--------------------------------------------------
An 8-digit bare number is simultaneously a valid US patent number and a valid
application serial. `util/identifier_normalization.py` used to break the tie
with arithmetic — "8 digits and >= 8,000,000 means application serial" — which
was true only while patent numbers stayed below 8 million. They passed
12,000,000 in 2024, so every recent grant was silently routed to
`applicationNumberText:<n>` and answered with an unrelated application.

Live-verified 2026-08-30 against api.uspto.gov:
  applicationMetaData.patentNumber:12539322 -> application 17996652
      ("USE OF MULBERRY EXTRACT ...", Societe des Produits Nestle S.A.)
  applicationNumberText:12539322            -> application 12/539,322
      ("IMAGE SENSOR COMPRISING A WAVEGUIDE STRUCTURE ...", patent 8,334,497)

Both lanes are real. No heuristic can choose between them, so the API chooses:
the patent lane is queried first and the application lane is the fallback, and
every affected tool reports `identifier_resolved_as` plus `identifier_lanes_tried`.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..models.constants import IdentifierType
from ..shared.safe_logger import get_safe_logger
from .identifier_normalization import normalize_identifier

logger = get_safe_logger(__name__)

#: Values accepted by the `content_type` parameter that forces one lane.
CONTENT_TYPE_AUTO = "auto"
CONTENT_TYPE_PATENT = "patent"
CONTENT_TYPE_APPLICATION = "application"
CONTENT_TYPES = (CONTENT_TYPE_AUTO, CONTENT_TYPE_PATENT, CONTENT_TYPE_APPLICATION)


def patent_lane_query(value: str) -> str:
    return f"applicationMetaData.patentNumber:{value}"


def application_lane_query(value: str) -> str:
    return f"applicationNumberText:{value}"


#: The search index crosswalks an 11-digit pre-grant publication number to its
#: application through `applicationMetaData.earliestPublicationNumber`, but the
#: resolver never queried it: a publication number resolved to
#: `application_number=None` and every tool answered "Could not resolve" (skill
#: QA ledger, 2026-09-03). USPTO prints the field both bare ("20080141381") and
#: in the WIPO ST.16 form with a country prefix and a kind code
#: ("US20080141381A1"), so both shapes are tried, in that order, and whichever
#: matched is reported in `identifier_lanes_tried`.
PUBLICATION_LANE_FIELD = "applicationMetaData.earliestPublicationNumber"


def publication_lane_queries(digits: str) -> List[str]:
    return [
        f"{PUBLICATION_LANE_FIELD}:{digits}",
        f"{PUBLICATION_LANE_FIELD}:US{digits}*",
    ]


def format_patent_number(digits: str) -> str:
    """'11752072' -> '11,752,072' (display form for ambiguity notes)."""
    return f"{int(digits):,}"


def format_application_serial(digits: str) -> str:
    """'11752072' -> '11/752,072', the slash-comma serial format that
    resolution treats as unambiguous. Only meaningful for an 8-digit value."""
    return f"{digits[:2]}/{digits[2:5]},{digits[5:]}"


@dataclass
class ResolvedIdentifier:
    """What the identifier turned out to be, and how that was established."""

    input_value: str
    cleaned_value: str
    resolved_as: str  # "patent" | "application" | "publication" | "unresolved"
    application_number: Optional[str] = None
    patent_number: Optional[str] = None
    ambiguous: bool = False
    lanes_tried: List[str] = field(default_factory=list)
    note: str = ""

    def response_fields(self) -> Dict[str, Any]:
        """The block every affected tool merges into its response."""
        block: Dict[str, Any] = {
            "identifier_input": self.input_value,
            "identifier_resolved_as": self.resolved_as,
            "identifier_lanes_tried": list(self.lanes_tried),
        }
        if self.ambiguous:
            block["identifier_ambiguous"] = True
        if self.note:
            block["identifier_note"] = self.note
        return block


async def _lane_hit(client, query: str) -> Optional[Dict[str, Any]]:
    """Run one identifier lane. Returns the first hit or None (never raises)."""
    try:
        return await client.lookup_identifier_lane(query)
    except Exception as e:  # pragma: no cover - defensive; lane misses are not errors
        logger.warning(f"Identifier lane lookup failed ({type(e).__name__})")
        return None


def _hit_fields(hit: Dict[str, Any]):
    app_number = hit.get("applicationNumberText")
    patent_number = (hit.get("applicationMetaData") or {}).get("patentNumber")
    return app_number, patent_number


async def _resolve_forced_lane(client, cleaned, identifier, content_type, lanes):
    """content_type='patent'/'application' skip the ambiguity dance entirely.
    Returns None for 'auto'."""
    if content_type == CONTENT_TYPE_PATENT:
        query = patent_lane_query(cleaned)
        hit = await _lane_hit(client, query)
        if hit:
            app_number, patent_number = _hit_fields(hit)
            lanes.append(f"{query} -> matched application {app_number}")
            return ResolvedIdentifier(
                identifier, cleaned, IdentifierType.PATENT, app_number,
                patent_number or cleaned, False, lanes,
                "content_type='patent' forced the patent-number lane.",
            )
        lanes.append(f"{query} -> no match")
        return ResolvedIdentifier(
            identifier, cleaned, "unresolved", None, None, False, lanes,
            "content_type='patent' forced the patent-number lane and it matched "
            "nothing. Drop content_type to let both lanes be tried.",
        )

    if content_type == CONTENT_TYPE_APPLICATION:
        lanes.append(f"{application_lane_query(cleaned)} -> used (content_type='application')")
        return ResolvedIdentifier(
            identifier, cleaned, IdentifierType.APPLICATION, cleaned, None, False, lanes,
            "content_type='application' forced the application-serial lane.",
        )
    return None


async def _resolve_publication(client, cleaned, identifier, lanes) -> ResolvedIdentifier:
    """Crosswalk a pre-grant publication number to its application.

    The search index carries the mapping on
    `applicationMetaData.earliestPublicationNumber`; before this the resolver
    simply declared the format "not an application serial" and returned nothing
    to resolve, so PFW_get_patent_or_application_xml could not be given a
    publication number at all.
    """
    for query in publication_lane_queries(cleaned):
        hit = await _lane_hit(client, query)
        if not hit:
            lanes.append(f"{query} -> no match")
            continue
        app_number, patent_number = _hit_fields(hit)
        lanes.append(f"{query} -> matched application {app_number}")
        return ResolvedIdentifier(
            identifier, cleaned, IdentifierType.PUBLICATION, app_number,
            patent_number, False, lanes,
            f"Publication number {cleaned} resolved to application {app_number} "
            f"through {PUBLICATION_LANE_FIELD}. Pre-grant publication XML "
            "(APPXML) is what this identifier names; pass the granted patent "
            "number, or content_type='patent', for the issued claims.",
        )
    return ResolvedIdentifier(
        identifier, cleaned, "unresolved", None, None, False, lanes,
        f"{cleaned} reads as a pre-grant publication number, but no application "
        f"in the search index carries it on {PUBLICATION_LANE_FIELD}. Check the "
        "number, or search for the application directly.",
    )


async def resolve_identifier_lanes(
    client,
    identifier: str,
    content_type: str = CONTENT_TYPE_AUTO,
    verify_application_lane: bool = False,
) -> ResolvedIdentifier:
    """Resolve `identifier` to an application number, reporting the lane used.

    Args:
        client: an EnhancedPatentClient (only `lookup_identifier_lane` is used)
        identifier: whatever the caller typed
        content_type: 'auto' (default), 'patent' or 'application'. The two
            explicit values force a single lane and skip the ambiguity dance.
        verify_application_lane: when the patent lane misses, actually QUERY
            `applicationNumberText:<n>` instead of assuming it. The XML tool
            sets this because it needs the matched record; the tools that only
            need an application number leave it False and spend one call less
            (their own next call confirms the number anyway).

    Returns:
        ResolvedIdentifier. `resolved_as == "unresolved"` means neither lane
        matched; the caller decides whether that is an error.
    """
    info = normalize_identifier(identifier)
    cleaned = info.cleaned_value
    lanes: List[str] = []

    forced = await _resolve_forced_lane(client, cleaned, identifier, content_type, lanes)
    if forced is not None:
        return forced

    if info.identifier_type == IdentifierType.APPLICATION:
        lanes.append(f"{application_lane_query(cleaned)} -> used (unambiguous application format)")
        return ResolvedIdentifier(
            identifier, cleaned, IdentifierType.APPLICATION,
            info.app_number_for_docs or cleaned, None, False, lanes, info.notes,
        )

    if info.identifier_type == IdentifierType.PUBLICATION:
        return await _resolve_publication(client, cleaned, identifier, lanes)

    if info.identifier_type == IdentifierType.PATENT:
        query = patent_lane_query(cleaned)
        hit = await _lane_hit(client, query)
        if hit:
            app_number, patent_number = _hit_fields(hit)
            lanes.append(f"{query} -> matched application {app_number}")
            return ResolvedIdentifier(
                identifier, cleaned, IdentifierType.PATENT, app_number,
                patent_number or cleaned, False, lanes,
                "7-digit-or-shorter identifier: patent number, unambiguous.",
            )
        lanes.append(f"{query} -> no match")
        return ResolvedIdentifier(
            identifier, cleaned, "unresolved", None, None, False, lanes,
            "Identifier reads as a patent number but no granted patent carries it.",
        )

    # AMBIGUOUS (8 digits) and anything unknown: patent lane first, then the
    # application lane.
    patent_query = patent_lane_query(cleaned)
    hit = await _lane_hit(client, patent_query)
    if hit:
        app_number, patent_number = _hit_fields(hit)
        lanes.append(f"{patent_query} -> matched application {app_number}")
        return ResolvedIdentifier(
            identifier, cleaned, IdentifierType.PATENT, app_number,
            patent_number or cleaned, True, lanes,
            f'Interpreted "{identifier}" as patent number '
            f"{format_patent_number(cleaned)} (application {app_number}). "
            f"If you meant application serial {format_application_serial(cleaned)}, "
            "re-call with that format or content_type='application'.",
        )
    lanes.append(f"{patent_query} -> no match")

    app_query = application_lane_query(cleaned)
    if verify_application_lane:
        hit = await _lane_hit(client, app_query)
        if not hit:
            lanes.append(f"{app_query} -> no match")
            return ResolvedIdentifier(
                identifier, cleaned, "unresolved", None, None, True, lanes,
                f"Neither lane matched {cleaned}: it is not a granted patent number "
                "and not an application serial USPTO serves.",
            )
        app_number, patent_number = _hit_fields(hit)
        lanes.append(f"{app_query} -> matched application {app_number}")
        return ResolvedIdentifier(
            identifier, cleaned, IdentifierType.APPLICATION, app_number or cleaned,
            patent_number, True, lanes,
            f"{cleaned} is 8 digits. No granted patent carries that number, so it "
            "was read as an application serial.",
        )

    lanes.append(f"{app_query} -> used (patent lane matched nothing)")
    return ResolvedIdentifier(
        identifier, cleaned, IdentifierType.APPLICATION, cleaned, None, True, lanes,
        f"{cleaned} is 8 digits. No granted patent carries that number, so it was "
        "read as an application serial. Pass content_type='patent' to force the "
        "patent lane.",
    )


async def resolve_application_number(
    client, identifier: str, content_type: str = CONTENT_TYPE_AUTO
) -> ResolvedIdentifier:
    """Resolve whatever the caller typed into an application number for the
    application-scoped tools (documents, office actions, family, term
    adjustment, granted-patent package).

    Costs at most ONE extra USPTO call, and only for an identifier that could
    be a patent number. When the patent lane misses, the identifier IS the
    application serial, which the tool's own next call confirms — so the
    application lane is not queried a second time.
    """
    return await resolve_identifier_lanes(
        client, identifier, content_type, verify_application_lane=False
    )


VALID_CONTENT_TYPES = (CONTENT_TYPE_AUTO, CONTENT_TYPE_PATENT, CONTENT_TYPE_APPLICATION)


def content_type_error_message(content_type: str):
    """The rejection text for an unrecognized content_type value, or None.

    A caller reaching for content_type is exactly the caller trying to escape
    the 8-digit ambiguity, so a typo ('applicaton') must fail loudly: until
    2026-09-02 any unrecognized value silently behaved as 'auto', which put
    the caller right back in the ambiguous lane they were trying to leave.
    """
    if content_type in VALID_CONTENT_TYPES:
        return None
    return (
        f"content_type must be 'auto', 'patent', or 'application' (got "
        f"'{content_type}'). Use 'application' to force the application-serial "
        "lane or 'patent' to force the granted-patent lane."
    )


async def resolve_or_error(client, identifier: str, content_type: str = CONTENT_TYPE_AUTO):
    """(resolution, error_response_or_None) — the SINGLE entry point every
    identifier-taking tool uses, so the "could not resolve" branch and the
    resolve/validate ORDER are written once.

    THE ORDER IS THE WHOLE POINT (evals finding, 2026-08-31)
    -------------------------------------------------------
    The RAW string the caller typed is resolved FIRST; `validate_app_number`
    runs only on what resolution returned. Doing it the other way round is a
    wrong-answer bug, not a style preference: `validate_app_number` strips
    every non-digit, so the official slashed serial "11/752,072" — the format
    printed on every USPTO filing receipt — reached resolution as the bare
    8-digit "11752072", which IS ambiguous, took the patent lane, and answered
    about patent 11,752,072 (application 16816197) with `identifier_ambiguous:
    true` and no hint that a slash had ever been typed. Same on "12/539,322"
    (correct 12539322 versus wrong 17996652).

    A slashed serial is unambiguous: `normalize_identifier` types it
    APPLICATION and `resolve_identifier_lanes` short-circuits on that, sending
    `identifier_resolved_as: "application"` and a `lanes_tried` entry saying
    why — but only while it can still see the slash.

    `PFW_get_application_documents`, `PFW_get_family`,
    `PFW_get_term_adjustment` and `PFW_get_granted_patent_documents_download`
    each carried their own copy of the order and three of them had it
    backwards. They now all call this function and none of them calls
    `validate_app_number` on a raw identifier;
    `tests/test_identifier_resolution_order.py` pins both halves.

    `content_type` is forwarded to `resolve_identifier_lanes` so a tool can
    expose it and let the caller force one lane (PFW_get_family does); the
    default 'auto' leaves every other caller's behavior unchanged.
    """
    from ..api.helpers import format_error_response, validate_app_number
    from ..exceptions import ValidationError

    raw = "" if identifier is None else str(identifier).strip()
    if not raw:
        return None, format_error_response("Application number cannot be empty", 400)

    bad_content_type = content_type_error_message(content_type)
    if bad_content_type:
        return None, format_error_response(bad_content_type, 400)

    resolution = await resolve_application_number(client, raw, content_type)
    if not resolution.application_number:
        error = {
            **format_error_response(
                f"Could not resolve '{raw}' to a USPTO application. "
                + (resolution.note or ""),
                404,
            ),
            **resolution.response_fields(),
        }
        return resolution, error

    # Validate AFTER resolution: at this point the value is an application
    # number the API produced (or the serial the caller typed), never a
    # formatted identifier whose punctuation still carries meaning.
    try:
        resolution.application_number = validate_app_number(resolution.application_number)
    except ValidationError as exc:
        error = {
            **format_error_response(str(exc), 400),
            **resolution.response_fields(),
        }
        return resolution, error
    return resolution, None
