"""MCP tool registration package (audit F2: main.py God File split).

Each module exposes register(mcp) and holds the tools for one concern.
Registration order matches the historical main.py order so tools/list is
unchanged.

register_all also wraps the FastMCP object in a thin registration proxy
(`_BoundedRegistrar`) so EVERY tool response passes through the shared
response-size guard (`shared/response_bounds.py`) on the way out — one attach
point instead of per-tool wiring. claude.ai replaces an oversized tool result
with a client-side truncation error the server never sees, so an unguarded
tool is an unrecoverable failure for the model; the guard trades some
records/fields for a usable response plus a recovery note. Responses that
already fit are returned byte-identically (no `_bounds` key at all).

PFW tools return DICTS (FastMCP serializes them), so — unlike PTAB — there is
no data-bearing `json.dumps(..., indent=2)` to compact: the guard measures
exactly what FastMCP will serialize. The only `indent=2` in the package is
`config/field_manager.py`'s YAML dump, which is not a tool response.

PFW-SPECIFIC DEVIATION from the FPD/PTAB proxies: `register_guarded` hands
back the UNGUARDED function. PFW's tier tools call one another inside
`register()` (`PFW_search_applications_minimal` delegates to
`pfw_search_applications`, the inventor tiers to `pfw_search_inventor`), and
fastmcp 3.4's `@mcp.tool(...)` returns the plain function — so returning the
guarded wrapper would bound an inner call a second time and stamp it with the
wrong tool's recovery note. Guarding happens exactly once, at the MCP
boundary.
"""

import functools
import inspect
import json
from typing import Any, Dict

from ..shared import response_bounds


# ---------------------------------------------------------------------------
# Per-tool guard configuration
# ---------------------------------------------------------------------------
# Everything repo-specific lives HERE; shared/response_bounds.py stays
# repo-agnostic and byte-identical across the USPTO MCPs.

#: Application-search records land under `applications`
#: (api/enhanced_client.py::search_applications). Tier field filtering already
#: selected the fields, so stage 1 has nothing to slim and stage 2 halves the
#: record list toward the floor.
_APPLICATIONS_SPEC = {
    "path": ["applications"],
    "keep_fields": (),
    "min_items": 5,
    "label": "applications",
}

#: Inventor searches return their de-duplicated hits under a different key.
_UNIQUE_APPLICATIONS_SPEC = {
    "path": ["unique_applications"],
    "keep_fields": (),
    "min_items": 5,
    "label": "unique_applications",
}

#: `PFW_search_applications` / `PFW_search_inventor` accept a caller-supplied
#: `fields` list, so a record can drag in heavy nested bags the tiers exclude.
#: Slim those to what a follow-up call actually needs before dropping records.
_DOC_SLIM_FIELDS = (
    "documentIdentifier",
    "documentCode",
    "documentCodeDescriptionText",
    "officialDate",
    "directionCategory",
)

_NESTED_BAG_SPECS = tuple(
    {
        "path": [records_key, "*", bag],
        "keep_fields": _DOC_SLIM_FIELDS,
        "min_items": 10,
        "label": bag,
    }
    for records_key in ("applications", "unique_applications")
    for bag in ("documentBag", "associatedDocuments")
)

#: PFW_get_application_documents. tools/document_tools.py runs the same spec at
#: its own attach point (after the PDF-option pre-slim); this is the
#: registrar-level backstop for anything that gets past it.
_DOCUMENT_BAG_SPEC = {
    "path": ["documentBag"],
    "keep_fields": (),
    "min_items": 10,
    "label": "documentBag",
}

_OA_REJECTIONS_SPEC = {
    "path": ["rejections"],
    "keep_fields": (),
    "min_items": 5,
    "label": "rejections",
}

_OA_TEXT_SPEC = {
    "path": ["office_actions"],
    "keep_fields": (),
    "min_items": 1,
    "label": "office_actions",
}

_FAMILY_SPECS = (
    {"path": ["edges"], "keep_fields": (), "min_items": 10, "label": "edges"},
    {"path": ["nodes"], "keep_fields": (), "min_items": 10, "label": "nodes"},
)

_SEARCH_NOTE_TEMPLATE = (
    "Response exceeded the client response-size limit, so fewer records were "
    "returned than requested. Re-call {tool} with a smaller limit= and page with "
    "offset= (the response's `paging.next_offset`) to retrieve the rest."
)

_INVENTOR_NOTE_TEMPLATE = (
    "Response exceeded the client response-size limit, so fewer applications were "
    "returned than requested. Re-call {tool} with a smaller limit=, or narrow with "
    "art_unit / status_code / filing_date_start."
)

_DOCUMENTS_NOTE = (
    "Response exceeded the client response-size limit, so document entries were "
    "slimmed and the list truncated. Narrow with document_code (NOA, CTNF, CTFR, "
    "892, CLM) or direction_category (INCOMING/OUTGOING/INTERNAL), or lower limit."
)

_XML_NOTE = (
    "Response exceeded the client response-size limit. Re-call "
    "PFW_get_patent_or_application_xml(identifier=..., include_raw_xml=False) and "
    "narrow include_fields=['claims'] (or ['abstract']) — raw_xml alone is ~50K "
    "tokens and is almost never needed."
)

_CONTENT_NOTE = (
    "Extracted content exceeded the content-size limit. Re-call "
    "PFW_get_document_content_with_ocr(app_number=..., document_identifier=..., "
    "char_offset=<_window.next_offset>) to continue from where this window ended."
)

_OA_TEXT_NOTE = (
    "Office action text exceeded the content-size limit. Re-call "
    "PFW_get_oa_text(application_number=..., char_offset=<_window.next_offset>) to "
    "continue, narrow with section='101'|'102'|'103'|'112', or set latest_only=True."
)

#: Canonical `_bounds` sub-key -> this repo's pre-existing top-level key. Kept
#: for this release so consumers written against the old vocabulary
#: (documents_returned / documents_total / documents_note) keep working.
_DOCUMENT_ALIASES = {
    "items_returned": "documents_returned",
    "items_total": "documents_total",
    "note": "documents_note",
}

_TOOL_BOUNDS: Dict[str, Dict[str, Any]] = {
    # ---- application searches ----
    "PFW_search_applications": {
        "bags": _NESTED_BAG_SPECS + (_APPLICATIONS_SPEC,),
        "note": _SEARCH_NOTE_TEMPLATE.format(tool="PFW_search_applications"),
    },
    "PFW_search_applications_minimal": {
        "bags": _NESTED_BAG_SPECS + (_APPLICATIONS_SPEC,),
        "note": _SEARCH_NOTE_TEMPLATE.format(tool="PFW_search_applications_minimal"),
    },
    "PFW_search_applications_balanced": {
        "bags": _NESTED_BAG_SPECS + (_APPLICATIONS_SPEC,),
        "note": _SEARCH_NOTE_TEMPLATE.format(tool="PFW_search_applications_balanced"),
    },
    # ---- inventor searches ----
    "PFW_search_inventor": {
        "bags": _NESTED_BAG_SPECS + (_UNIQUE_APPLICATIONS_SPEC,),
        "note": _INVENTOR_NOTE_TEMPLATE.format(tool="PFW_search_inventor"),
    },
    "PFW_search_inventor_minimal": {
        "bags": _NESTED_BAG_SPECS + (_UNIQUE_APPLICATIONS_SPEC,),
        "note": _INVENTOR_NOTE_TEMPLATE.format(tool="PFW_search_inventor_minimal"),
    },
    "PFW_search_inventor_balanced": {
        "bags": _NESTED_BAG_SPECS + (_UNIQUE_APPLICATIONS_SPEC,),
        "note": _INVENTOR_NOTE_TEMPLATE.format(tool="PFW_search_inventor_balanced"),
    },
    # ---- documents ----
    "PFW_get_application_documents": {
        "bags": (_DOCUMENT_BAG_SPEC,),
        "note": _DOCUMENTS_NOTE,
        "aliases": _DOCUMENT_ALIASES,
    },
    "PFW_get_patent_or_application_xml": {
        "bags": (),
        "note": _XML_NOTE,
    },
    # ---- office actions ----
    "PFW_get_oa_rejections": {
        "bags": (_OA_REJECTIONS_SPEC,),
        "note": (
            "Response exceeded the client response-size limit, so rejection rows were "
            "dropped. Re-call PFW_get_oa_rejections(application_number=..., rows=<smaller>) "
            "or latest_only=True."
        ),
    },
    # The caller explicitly asked for office-action text, so the ceiling is the
    # higher content budget and the tool's own cursor (`_window`) has already
    # bounded it; this is the backstop against a pathological payload.
    "PFW_get_oa_text": {
        "bags": (_OA_TEXT_SPEC,),
        "budget": "content",
        "note": _OA_TEXT_NOTE,
    },
    "PFW_get_document_content_with_ocr": {
        "bags": (),
        "budget": "content",
        "note": _CONTENT_NOTE,
    },
    # ---- family ----
    "PFW_get_family": {
        "bags": _FAMILY_SPECS,
        "note": (
            "Response exceeded the client response-size limit, so family edges/nodes "
            "were dropped. Re-call PFW_get_family(application_number=..., "
            "include_foreign_priority=False) or walk the family one member at a time."
        ),
    },
}

#: Anything not listed above (downloads, guidance, term adjustment, admin) gets
#: the plain response budget with the largest-free-text-field fallback, so
#: coverage is 100% without per-tool wiring.
_DEFAULT_BOUNDS: Dict[str, Any] = {"bags": ()}


def _bound_result(result: Any, tool_name: str) -> Any:
    """Apply the shared guard to one tool result (dict or JSON string)."""
    config = dict(_TOOL_BOUNDS.get(tool_name) or _DEFAULT_BOUNDS)
    budget = config.pop("budget", "response")
    config.setdefault("text_fallback", True)
    config["limit"] = (
        response_bounds.content_char_budget()
        if budget == "content"
        else response_bounds.response_char_budget()
    )

    if isinstance(result, dict):
        return response_bounds.bound_structured_response(result, **config)

    if isinstance(result, str) and result.lstrip().startswith("{"):
        try:
            parsed = json.loads(result)
        except ValueError:
            return result
        if not isinstance(parsed, dict):
            return result
        bounded = response_bounds.bound_structured_response(parsed, **config)
        if response_bounds.BOUNDS_KEY not in bounded:
            return result  # no-op: hand back the original string byte-for-byte
        return json.dumps(bounded, default=str)

    return result


def _guard(fn, tool_name: str):
    """Wrap a tool function so its response passes through the guard.

    The signature is preserved (both via functools.wraps' ``__wrapped__`` and
    an explicit ``__signature__``) so FastMCP derives the same input schema it
    would from the unwrapped function.
    """
    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            return _bound_result(await fn(*args, **kwargs), tool_name)
    else:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return _bound_result(fn(*args, **kwargs), tool_name)

    try:
        wrapper.__signature__ = inspect.signature(fn)
    except (TypeError, ValueError):  # pragma: no cover - builtins only
        pass
    return wrapper


class _BoundedRegistrar:
    """Thin proxy over the FastMCP object that guards every registered tool.

    Only ``.tool(...)`` is intercepted; every other attribute (resources,
    templates, custom routes, run) passes straight through to the real object.
    Handles both PFW's decorator form (``@mcp.tool(name=...)``) and the
    imperative form admin_tools uses (``mcp.tool(name=...)(fn)``).
    """

    def __init__(self, mcp) -> None:
        self._mcp = mcp

    def __getattr__(self, name):
        return getattr(self._mcp, name)

    def tool(self, *args, **kwargs):
        if args and callable(args[0]):  # bare @mcp.tool usage
            fn = args[0]
            name = kwargs.get("name") or getattr(fn, "__name__", "")
            self._mcp.tool(_guard(fn, name), *args[1:], **kwargs)
            return fn

        decorator = self._mcp.tool(*args, **kwargs)

        def register_guarded(fn):
            name = kwargs.get("name") or getattr(fn, "__name__", "")
            decorator(_guard(fn, name))
            # Hand back the UNGUARDED function — see the module docstring:
            # PFW's tier tools call one another, and double-guarding an inner
            # call would stamp it with the wrong tool's recovery note.
            return fn

        return register_guarded


def register_all(mcp, auth_provider=None) -> None:
    """Register every PFW tool on the FastMCP server."""
    from . import (
        admin_tools,
        document_tools,
        family_tools,
        guidance_tools,
        oa_tools,
        search_tools,
        term_tools,
    )

    bounded = _BoundedRegistrar(mcp)
    admin_tools.register(bounded, auth_provider)
    search_tools.register(bounded)
    document_tools.register(bounded)
    guidance_tools.register(bounded)
    oa_tools.register(bounded)
    family_tools.register(bounded)
    term_tools.register(bounded)
