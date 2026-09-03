"""Family tool: continuity + foreign priority as one normalized graph."""

from typing import Any, Dict, List

from fastmcp.apps import AppConfig

from ..api.helpers import build_family_graph, compute_earliest_priority
from ..app_uris import _FAMILY_URI
from ..client_registry import _client
from ..shared.safe_logger import get_safe_logger
from ..util.error_handlers import mcp_error_handler
from ..util.identifier_resolution import (
    application_lane_query,
    resolve_or_error,
)

logger = get_safe_logger(__name__)

# Depth is hard-capped: depth 1 is the single /continuity call, depth 2 spends
# one extra call per direct parent and child. Anything deeper is unbounded
# recursion against a rate-limited API and is deliberately not offered.
MAX_FAMILY_DEPTH = 2

# Backstop on the depth-2 fan-out. A prolific parent can carry dozens of
# children; expanding all of them would turn one tool call into dozens of
# USPTO requests. The response says how many were skipped.
MAX_DEPTH_2_EXPANSIONS = 12


async def _collect_continuity(client, app_numbers: List[str]) -> List[Dict[str, Any]]:
    """Fetch /continuity for each application, dropping failures.

    Sequential on purpose: every call goes through USPTOTransport and the
    shared USPTO rate limiter, so a depth-2 fan-out queues rather than bursts.
    """
    records = []
    for app_number in app_numbers:
        result = await client.get_continuity(app_number)
        if result.get('error') or not result.get('success'):
            logger.info("Continuity expansion skipped for one application (non-success response)")
            continue
        records.append(result)
    return records


def _direct_relations(root_result: Dict[str, Any], queried: str) -> List[str]:
    """Normalized application numbers of the queried app's direct parents and
    children, de-duplicated and excluding the queried application itself."""
    raw = [
        entry.get('parentApplicationNumberText')
        for entry in root_result.get('parent_continuity_bag') or []
    ] + [
        entry.get('childApplicationNumberText')
        for entry in root_result.get('child_continuity_bag') or []
    ]

    seen = {queried}
    relations = []
    for value in raw:
        if not value:
            continue
        normalized = ''.join(ch for ch in str(value) if ch.isdigit())
        if normalized and normalized not in seen:
            seen.add(normalized)
            relations.append(normalized)
    return relations


async def _expand_depth_2(client, root_result: Dict[str, Any], queried: str):
    """One extra /continuity call per direct relation, capped. Returns
    (extra_records, expansion_note)."""
    to_expand = _direct_relations(root_result, queried)

    skipped = max(0, len(to_expand) - MAX_DEPTH_2_EXPANSIONS)
    to_expand = to_expand[:MAX_DEPTH_2_EXPANSIONS]

    records = await _collect_continuity(client, to_expand)

    note = None
    if skipped:
        note = (
            f"Depth 2 expanded {len(to_expand)} of {len(to_expand) + skipped} direct "
            f"relations (cap {MAX_DEPTH_2_EXPANSIONS} per call). Query a skipped "
            "application directly to expand it."
        )
    return records, note


def _ancestor_entries(graph: Dict[str, Any], queried: str) -> List[Dict[str, Any]]:
    """Every ancestor of the queried application present in the graph, with its
    filing date and the parentage code that links it in.

    Walks up the parent edges rather than reading `parents` alone, so a depth-2
    call contributes grandparents (and the provisional at the top of the chain)
    to the priority computation.
    """
    nodes = {n.get("application_number"): n for n in graph.get("nodes") or []}
    parents_of: Dict[str, List[Dict[str, Any]]] = {}
    for edge in graph.get("edges") or []:
        parents_of.setdefault(edge.get("child_app"), []).append(edge)

    entries: List[Dict[str, Any]] = []
    seen = {queried}
    queue = [queried]
    while queue:
        current = queue.pop(0)
        for edge in parents_of.get(current) or []:
            parent = edge.get("parent_app")
            if not parent or parent in seen:
                continue
            seen.add(parent)
            queue.append(parent)
            entries.append({
                "application_number": parent,
                "filing_date": (nodes.get(parent) or {}).get("filing_date"),
                "relation_type": edge.get("relation_type"),
            })
    return entries


async def _own_filing_date(client, app_number: str):
    """The queried application's own filingDate. The /continuity response does
    not carry it, so this is one minimal search; a failure is not fatal (the
    priority computation simply loses one candidate and says so)."""
    try:
        hit = await client.lookup_identifier_lane(application_lane_query(app_number))
    except Exception as e:  # pragma: no cover - defensive
        logger.info(f"Own filing-date lookup failed ({type(e).__name__})")
        return None, None
    if not hit:
        return None, None
    meta = hit.get("applicationMetaData") or {}
    return meta.get("filingDate"), meta.get("effectiveFilingDate")


def register(mcp) -> None:
    """Register PFW_get_family."""
    @mcp.tool(
        name="PFW_get_family",
        app=AppConfig(resource_uri=_FAMILY_URI),
        annotations={"defer_loading": True, "readOnlyHint": True},
    )
    @mcp_error_handler
    async def pfw_get_family(
        application_number: str,
        include_foreign_priority: bool = True,
        max_depth: int = 1,
        content_type: str = "auto",
    ) -> Dict[str, Any]:
        """Get the patent family (continuity + foreign priority) for an application.
    Family, continuity, parent, child, continuation, CIP, divisional, priority claim, related applications, benefit chain, family tree.

    STRUCTURE tool: returns a compact normalized family graph — a `nodes` list and an
    `edges` list — not the raw USPTO continuity bags. Use it to see what a patent's
    domestic benefit chain looks like (parents, children, continuation type) and what
    foreign priority it claims, then pull the interesting members with the search,
    document or office-action tools.

    Args:
        application_number: Patent application number (e.g., '14853719') or the granted
                                  patent number. WARNING: a bare 8-digit number is ambiguous.
                                  It is a valid application serial and, since patent numbers
                                  crossed US 10,000,000 in mid-2018, also a valid patent
                                  number, and resolution is patent-number-first, so an
                                  8-digit serial can be captured by an unrelated granted
                                  patent. For an application serial, use the slash-comma
                                  format (e.g. '11/752,072') or pass
                                  content_type='application'; the response reports
                                  identifier_resolved_as and identifier_lanes_tried.
        content_type: 'auto' (default), 'patent' or 'application'. The two explicit
                                  values force one resolution lane for a bare 8-digit
                                  identifier instead of the patent-number-first probe.
        include_foreign_priority: Also call /foreign-priority (default True). Set False
                                  to save one USPTO call when only continuity matters.
        max_depth: 1 (default) — one /continuity call: the direct parents and children
                   of the queried application.
                   2 — one additional /continuity call per direct parent and child, so
                   grandparents, siblings and grandchildren appear. Capped at 2;
                   the fan-out is capped at 12 expansions per call.

    Returns:
        nodes: [{application_number, patent_number, filing_date, status, status_code,
                 is_queried}] — the queried application is flagged is_queried=True.
        edges: [{parent_app, child_app, relation_type, claim_parentage_type_code,
                 description}] — relation_type is the USPTO claimParentageTypeCode
                 (CON, CIP, DIV, ...), description its official text ("is a Division of").
        parents / children: direct relations of the queried application.
        roots: earliest ancestors reachable in the graph (walked up the parent chain,
               not simply the first parent bag entry).
        foreign_priority: [{country, application_number, filing_date}].
        earliest_priority_date: the MINIMUM over the foreign priority bag, the domestic
                 parent chain (provisionals included) and the application's own filing
                 date, with `priority_basis` naming what produced it and
                 `priority_candidates` listing every date considered.
        filing_date / effective_filing_date: the application's own dates, for contrast.
        notes: per-direction emptiness statements.

    DO NOT USE effectiveFilingDate AS THE PRIORITY DATE. It is the §371 national-stage
    ENTRY date for a national-stage case and the child's own filing date for a
    continuation, so an AIA or prior-art cutoff built on it inverts. Live example
    (2026-08-30): application 13975827 / US 9,135,462 reports effectiveFilingDate
    2013-08-26 while its provisional 61/694,492 was filed 2012-08-29. Use
    `earliest_priority_date` and read `priority_basis`. Depth 1 sees direct parents
    only — raise max_depth to 2 when the chain runs through a grandparent.

    PER-DIRECTION EMPTINESS. The USPTO continuity response can contain ONLY
    childContinuityBag or ONLY parentContinuityBag — an original application has no
    parents, a childless one has no children. Empty `parents` or `children` is an
    answer, not missing data, and `notes` says which case applies. Never read an empty
    list here as "this application has no family".

    Cost: depth 1 is 1 call (2 with foreign priority). Depth 2 is 1 + one call per
    direct parent and child, so a family with 5 members costs ~6 calls. Start at
    depth 1 and only step up when the direct relations are not enough.

    Examples:
        PFW_get_family('14/853,719')                     # direct parents + children
        PFW_get_family('14/104,993', max_depth=2)        # plus grandparents/grandchildren
        PFW_get_family('14/104,993', include_foreign_priority=False)
        """
        try:
            client = _client()

            # Resolve the RAW input first; resolve_or_error validates the
            # application number it produces. Validating first strips the slash
            # off "12/539,322" and silently answers about patent 12,539,322
            # (application 17996652) instead (evals finding 2026-08-31).
            resolution, resolve_error = await resolve_or_error(
                client, application_number, content_type
            )
            if resolve_error:
                return resolve_error
            app_number = resolution.application_number

            depth = max(1, min(int(max_depth), MAX_FAMILY_DEPTH))

            root_result = await client.get_continuity(app_number)
            if root_result.get('error'):
                return root_result

            records = [root_result]
            expansion_note = None

            if depth >= 2:
                extra, expansion_note = await _expand_depth_2(client, root_result, app_number)
                records.extend(extra)

            foreign_bag = None
            foreign_available = True
            if include_foreign_priority:
                fp_result = await client.get_foreign_priority(app_number)
                if fp_result.get('error'):
                    foreign_available = False
                    logger.info("Foreign priority lookup returned an error response")
                else:
                    foreign_bag = fp_result.get('foreign_priority_bag') or []

            graph = build_family_graph(
                app_number,
                records,
                foreign_priority_bag=foreign_bag,
                foreign_priority_requested=include_foreign_priority,
                foreign_priority_available=foreign_available,
            )

            own_filing, own_effective = await _own_filing_date(client, app_number)
            priority = compute_earliest_priority(
                own_filing_date=own_filing,
                own_application_number=app_number,
                parent_entries=_ancestor_entries(graph, app_number),
                foreign_priority=graph.get("foreign_priority"),
            )

            response = {
                "success": True,
                **resolution.response_fields(),
                "application_number": app_number,
                "filing_date": own_filing,
                "effective_filing_date": own_effective,
                "max_depth": depth,
                "continuity_calls": len(records),
                **priority,
                **graph,
            }
            if expansion_note:
                response["expansion_note"] = expansion_note
            return response

        except Exception as e:
            return {"success": False, "error": str(e), "application_number": application_number}
