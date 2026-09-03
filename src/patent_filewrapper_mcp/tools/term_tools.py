"""Patent term adjustment tool (USPTO ODP /adjustment endpoint)."""

from typing import Any, Dict

from ..api.helpers import (
    PTA_HISTORY_DEFAULT_CAP,
    normalize_term_adjustment,
)
from ..client_registry import _client
from ..shared.safe_logger import get_safe_logger
from ..util.error_handlers import mcp_error_handler
from ..util.identifier_resolution import resolve_or_error

logger = get_safe_logger(__name__)

# Upper bound on the history the tool will return in one call. The full bag
# runs to 60+ events on a normal prosecution and is mostly docketing noise.
MAX_PTA_EVENTS = 200


def register(mcp) -> None:
    """Register PFW_get_term_adjustment."""
    @mcp.tool(name="PFW_get_term_adjustment", annotations={"defer_loading": True, "readOnlyHint": True})
    @mcp_error_handler
    async def pfw_get_term_adjustment(
        application_number: str,
        max_events: int = PTA_HISTORY_DEFAULT_CAP,
        content_type: str = "auto",
    ) -> Dict[str, Any]:
        """Get Patent Term Adjustment (PTA) data for an application.
    PTA, term adjustment, extra days, patent term, A delay, B delay, C delay, applicant delay, office delay, how long was it pending.

    Returns the USPTO's own PTA accounting from the ODP /adjustment endpoint, flattened:
    the total adjustment in days, the A / B / C delay components, applicant delay, the
    overlap figures, and a capped, most-recent-first history of the PTA events behind
    the number.

    Args:
        application_number: Patent application number (e.g., '15992176') or the granted
                    patent number. WARNING: a bare 8-digit number is ambiguous. It is a
                    valid application serial and, since patent numbers crossed
                    US 10,000,000 in mid-2018, also a valid patent number, and
                    resolution is patent-number-first, so an 8-digit serial can be
                    captured by an unrelated granted patent. For an application serial,
                    use the slash-comma format (e.g. '11/752,072') or pass
                    content_type='application'; the response reports
                    identifier_resolved_as, identifier_note and
                    identifier_lanes_tried.
        max_events: How many history events to return, most recent first (default 20,
                    max 200). The response reports history_total and history_truncated
                    so you always know how much history exists beyond what came back.
        content_type: 'auto' (default), 'patent' or 'application'. The two explicit
                    values force one resolution lane for a bare 8-digit identifier
                    instead of the patent-number-first probe.

    Returns:
        adjustment: {adjustment_total_days, a_delay_days, b_delay_days, c_delay_days,
                     applicant_delay_days, overlapping_days, non_overlapping_delay_days,
                     ip_office_adjustment_delay_days}
        history: [{event_date, description, event_sequence_number,
                   originating_event_sequence_number, pta_pte_code,
                   applicant_delay_days, ip_office_delay_days}]
        history_returned / history_total / history_truncated

    SCOPE: this tool reports the adjustment data faithfully and does NOT compute a patent
    expiration date. Expiration depends on the 20-year term measured from the earliest
    US filing or priority date, terminal disclaimers, maintenance-fee status and any
    patent term EXTENSION (PTE, a separate 35 U.S.C. 156 mechanism) — none of which this
    endpoint carries. Combine adjustment_total_days with filing/priority dates from the
    search tools and PFW_get_family, and check for terminal disclaimers in the file
    wrapper, before stating a term.

    PTA is computed at issuance: a pending or abandoned application normally returns no
    patentTermAdjustmentData, which comes back success=True with an explanatory note.

    Examples:
        PFW_get_term_adjustment('15/992,176')                  # summary + 20 recent events
        PFW_get_term_adjustment('15/992,176', max_events=100)  # deeper history
        """
        try:
            client = _client()

            # PTA is asked about by patent number as often as by serial, and an
            # 8-digit value is both — resolve it and report the lane used
            # (OPEN_ITEMS #9). The RAW input is resolved first and validated
            # after (resolve_or_error does both): validating first strips the
            # slash off "12/539,322" and answers about patent 12,539,322
            # instead (evals finding 2026-08-31).
            resolution, resolve_error = await resolve_or_error(
                client, application_number, content_type
            )
            if resolve_error:
                return resolve_error
            app_number = resolution.application_number

            result = await client.get_term_adjustment(app_number)
            if result.get('error'):
                return {**result, **resolution.response_fields()}

            capped = max(1, min(int(max_events), MAX_PTA_EVENTS))
            normalized = normalize_term_adjustment(
                result.get('term_adjustment_data'),
                max_events=capped,
            )

            return {
                "success": True,
                **resolution.response_fields(),
                "application_number": app_number,
                **normalized,
                "data_note": "Source: USPTO ODP /adjustment endpoint. No expiration date is "
                             "computed — combine with filing/priority dates and check for "
                             "terminal disclaimers and any patent term extension (PTE).",
            }

        except Exception as e:
            return {"success": False, "error": str(e), "application_number": application_number}
