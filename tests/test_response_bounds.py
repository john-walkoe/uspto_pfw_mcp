"""Tests for the shared response-size guard (shared/response_bounds.py) and
its attach point, the tools/__init__.py registration proxy.

The module itself is VENDORED byte-identically from uspto_fpd_mcp (md5
699a1647c2fcff064f60aedd0ae08003, same file PTAB carries), so the module-level
tests below are FPD's, ported only by import path — if they diverge, the
vendored copy has drifted and should be re-copied rather than patched. The
registration-proxy tests are adapted to PFW, whose tools return DICTS (FastMCP
serializes them) and whose proxy hands back the UNGUARDED function so the tier
tools can keep calling one another without double-guarding.

Hermetic: no network, no FastMCP server. The registration-proxy tests drive a
stand-in `mcp` object that records what was registered.
"""

import json

from patent_filewrapper_mcp.shared.response_bounds import (
    BOUNDS_KEY,
    WINDOW_KEY,
    apply_text_window,
    bound_structured_response,
    bounds_config,
    content_char_budget,
    measure_chars,
    response_char_budget,
    window_text,
)

_BAG_PATH = ["records", "*", "documentBag"]


def _doc(i: int) -> dict:
    return {
        "documentIdentifier": f"DOC{i:04d}",
        "documentCode": "PET",
        "pageCount": 3,
        # The payload hog the guard is meant to shed.
        "downloadOptionBag": [
            {"mimeTypeIdentifier": "PDF", "downloadUrl": "https://api.uspto.gov/" + "x" * 200}
            for _ in range(3)
        ],
    }


def _payload(n_docs: int = 40) -> dict:
    return {"records": [{"id": "abc", "documentBag": [_doc(i) for i in range(n_docs)]}]}


def _spec(min_items: int = 10) -> dict:
    return {
        "path": _BAG_PATH,
        "keep_fields": ("documentIdentifier", "documentCode", "pageCount"),
        "min_items": min_items,
        "label": "documentBag",
    }


# ---------------------------------------------------------------------------
# Environment configuration
# ---------------------------------------------------------------------------

def test_env_defaults_and_overrides(monkeypatch):
    monkeypatch.delenv("USPTO_MAX_RESPONSE_CHARS", raising=False)
    monkeypatch.delenv("USPTO_MAX_CONTENT_CHARS", raising=False)
    monkeypatch.delenv("USPTO_RESPONSE_BOUNDS_ENABLED", raising=False)
    assert response_char_budget() == 40_000
    assert content_char_budget() == 120_000
    assert bounds_config()["enabled"] is True

    monkeypatch.setenv("USPTO_MAX_RESPONSE_CHARS", "12345")
    monkeypatch.setenv("USPTO_MAX_CONTENT_CHARS", "9999")
    monkeypatch.setenv("USPTO_RESPONSE_BOUNDS_ENABLED", "false")
    config = bounds_config()
    assert config["max_response_chars"] == 12345
    assert config["max_content_chars"] == 9999
    assert config["enabled"] is False

    # Garbage and non-positive values fall back to the defaults rather than
    # disabling the guard by accident.
    monkeypatch.setenv("USPTO_MAX_RESPONSE_CHARS", "not-a-number")
    assert response_char_budget() == 40_000
    monkeypatch.setenv("USPTO_MAX_RESPONSE_CHARS", "0")
    assert response_char_budget() == 40_000


# ---------------------------------------------------------------------------
# Guard 1: structured responses
# ---------------------------------------------------------------------------

def test_no_op_is_identity_and_byte_equal():
    payload = _payload(2)
    before = json.dumps(payload, default=str)

    result = bound_structured_response(payload, bags=(_spec(),), limit=1_000_000)

    assert result is payload  # same object, not a copy
    assert json.dumps(result, default=str) == before
    assert BOUNDS_KEY not in result


def test_disabled_guard_is_identity_even_when_oversized(monkeypatch):
    monkeypatch.setenv("USPTO_RESPONSE_BOUNDS_ENABLED", "0")
    payload = _payload(40)
    before = json.dumps(payload, default=str)

    result = bound_structured_response(payload, bags=(_spec(),), limit=500)

    assert result is payload
    assert json.dumps(result, default=str) == before
    assert BOUNDS_KEY not in result


def test_stage_1_slims_heavy_fields_only():
    payload = _payload(20)
    limit = 4_000
    assert measure_chars(payload) > limit

    result = bound_structured_response(payload, bags=(_spec(),), limit=limit, note="recover me")

    bounds = result[BOUNDS_KEY]
    assert bounds["stages"] == ["slimmed"]  # halving was not needed
    assert bounds["slimmed_fields"] == ["downloadOptionBag"]
    assert bounds["items_returned"] == bounds["items_total"] == 20
    assert bounds["note"] == "recover me"
    assert measure_chars(result) <= limit
    docs = result["records"][0]["documentBag"]
    assert all("downloadOptionBag" not in d for d in docs)
    assert docs[0]["documentIdentifier"] == "DOC0000"


def test_stage_2_halves_down_to_the_floor():
    payload = _payload(400)
    limit = 2_000

    result = bound_structured_response(payload, bags=(_spec(min_items=10),), limit=limit)

    bounds = result[BOUNDS_KEY]
    assert bounds["stages"] == ["slimmed", "truncated"]
    assert bounds["items_total"] == 400
    assert bounds["items_returned"] >= 10  # floor respected
    assert bounds["items_returned"] < 400
    assert len(result["records"][0]["documentBag"]) == bounds["items_returned"]


def test_floor_is_respected_even_when_it_cannot_fit():
    """The floor wins over the budget: dropping below it would leave the
    caller with nothing useful. The marker still tells the truth."""
    payload = _payload(40)

    result = bound_structured_response(payload, bags=(_spec(min_items=30),), limit=1_000)

    assert result[BOUNDS_KEY]["items_returned"] == 30


def test_marker_vocabulary_is_exact():
    result = bound_structured_response(_payload(400), bags=(_spec(),), limit=2_000)

    assert set(result[BOUNDS_KEY]) == {
        "applied",
        "reason",
        "size_chars",
        "size_limit",
        "stages",
        "slimmed_fields",
        "items_returned",
        "items_total",
        "note",
    }
    assert result[BOUNDS_KEY]["applied"] is True
    assert result[BOUNDS_KEY]["reason"] == "size"
    assert result[BOUNDS_KEY]["size_limit"] == 2_000
    assert result[BOUNDS_KEY]["size_chars"] == measure_chars(result)


def test_legacy_aliases_are_mirrored():
    aliases = {
        "items_returned": "documents_returned",
        "items_total": "documents_total",
        "note": "documents_note",
    }
    result = bound_structured_response(
        _payload(400), bags=(_spec(),), limit=2_000, note="use PFW_get_document_download", aliases=aliases
    )

    assert result["documents_total"] == 400
    assert result["documents_returned"] == result[BOUNDS_KEY]["items_returned"]
    assert result["documents_note"] == "use PFW_get_document_download"


def test_text_fallback_truncates_the_largest_string_with_a_marker():
    payload = {"extracted_content": "z" * 50_000, "meta": "small"}

    result = bound_structured_response(payload, bags=(), limit=5_000, text_fallback=True)

    assert measure_chars(result) <= 5_000
    assert result[BOUNDS_KEY]["stages"] == ["truncated"]
    assert "extracted_content" in result[BOUNDS_KEY]["note"]
    assert len(result["extracted_content"]) < 50_000


def test_oversized_with_nothing_to_shed_is_still_marked():
    payload = {"extracted_content": "z" * 50_000}

    result = bound_structured_response(payload, bags=(), limit=5_000, text_fallback=False)

    # Nothing could be dropped, but the caller is told the client may reject it.
    assert result[BOUNDS_KEY]["applied"] is True
    assert result[BOUNDS_KEY]["stages"] == []


# ---------------------------------------------------------------------------
# Guard 2: text windows
# ---------------------------------------------------------------------------

_PAGES = "\n\n".join(f"=== PAGE {i} ===\n{'abcde ' * 100}" for i in range(1, 21))


def test_window_text_no_op_when_everything_fits():
    result = window_text("short text", max_chars=1_000)

    assert result == {"text": "short text"}
    assert WINDOW_KEY not in result


def test_window_text_char_unit():
    text = "y" * 10_000

    result = window_text(text, offset=0, max_chars=1_000, note="next")

    window = result[WINDOW_KEY]
    assert window["unit"] == "char"
    assert window["offset"] == 0
    assert window["returned"] == 1_000
    assert window["total"] == 10_000
    assert window["has_more"] is True
    assert window["next_offset"] == 1_000
    assert window["note"] == "next"
    assert result["text"] == text[:1_000]


def test_window_text_page_unit_snaps_to_page_boundaries():
    result = window_text(_PAGES, offset=0, max_chars=2_000)

    window = result[WINDOW_KEY]
    assert window["unit"] == "page"
    assert window["returned"] <= 2_000
    # The window ends exactly where a page marker begins.
    assert _PAGES[window["next_offset"]:].startswith("=== PAGE ")
    assert result["text"].startswith("=== PAGE 1 ===")


def test_window_text_cursor_walks_the_whole_document():
    seen, offset, guard = [], 0, 0
    while True:
        guard += 1
        assert guard < 100
        result = window_text(_PAGES, offset=offset, max_chars=2_000)
        seen.append(result["text"])
        window = result.get(WINDOW_KEY)
        if not window or not window["has_more"]:
            break
        offset = window["next_offset"]

    # Pages are never split and nothing is lost.
    assert "".join(seen) == _PAGES


def test_window_text_offset_snaps_back_to_the_containing_page():
    first_page_len = _PAGES.index("=== PAGE 2 ===")

    result = window_text(_PAGES, offset=first_page_len - 5, max_chars=2_000)

    assert result[WINDOW_KEY]["offset"] == 0
    assert result["text"].startswith("=== PAGE 1 ===")


def test_window_text_single_oversized_page_degrades_to_char_unit():
    text = "=== PAGE 1 ===\n" + "q" * 5_000

    result = window_text(text, max_chars=1_000)

    assert result[WINDOW_KEY]["unit"] == "char"
    assert result[WINDOW_KEY]["returned"] == 1_000


def test_window_marker_vocabulary_is_exact():
    result = window_text("y" * 10_000, max_chars=1_000)

    assert set(result[WINDOW_KEY]) == {
        "unit",
        "offset",
        "returned",
        "total",
        "has_more",
        "next_offset",
        "note",
    }


def test_apply_text_window_attaches_markers_and_aliases():
    payload = {"extracted_content": "y" * 10_000}

    apply_text_window(
        payload,
        "extracted_content",
        max_chars=1_000,
        note="call again with char_offset",
        aliases={"applied": "truncated", "note": "truncation_note"},
    )

    assert payload[WINDOW_KEY]["has_more"] is True
    assert payload["truncated"] is True
    assert payload["truncation_note"] == "call again with char_offset"
    assert payload[BOUNDS_KEY]["reason"] == "window"


def test_apply_text_window_is_identity_when_it_fits():
    payload = {"extracted_content": "short"}
    before = json.dumps(payload)

    apply_text_window(payload, "extracted_content", max_chars=1_000)

    assert json.dumps(payload) == before
    assert WINDOW_KEY not in payload
    assert BOUNDS_KEY not in payload



# ---------------------------------------------------------------------------
# Attach point: the tools/__init__.py registration proxy
# ---------------------------------------------------------------------------

class _FakeMCP:
    """Records what a register() call would have registered."""

    def __init__(self):
        self.registered = {}

    def tool(self, *args, **kwargs):
        if args and callable(args[0]):
            fn = args[0]
            self.registered[kwargs.get("name") or fn.__name__] = fn
            return fn

        def decorator(fn):
            self.registered[kwargs.get("name") or fn.__name__] = fn
            return fn

        return decorator


async def test_registration_proxy_guards_dict_returns():
    """PFW tools return DICTS — FastMCP serializes them, so the guard measures
    exactly what ships and there is no re-serialization step."""
    from patent_filewrapper_mcp.tools import _BoundedRegistrar

    fake = _FakeMCP()

    async def big_tool(query: str = "", limit: int = 50):
        return {
            "success": True,
            "applications": [
                {"applicationNumberText": f"1{i:07d}", "blob": "z" * 400}
                for i in range(400)
            ],
        }

    _BoundedRegistrar(fake).tool(name="PFW_search_applications_minimal")(big_tool)
    registered = fake.registered["PFW_search_applications_minimal"]

    # Signature is preserved, so FastMCP derives the same input schema.
    import inspect

    assert list(inspect.signature(registered).parameters) == ["query", "limit"]

    result = await registered()
    assert isinstance(result, dict)
    assert result[BOUNDS_KEY]["applied"] is True
    assert result[BOUNDS_KEY]["items_total"] == 400
    assert len(result["applications"]) == result[BOUNDS_KEY]["items_returned"] < 400
    assert measure_chars(result) <= response_char_budget()


async def test_registration_proxy_hands_back_the_unguarded_function():
    """PFW-SPECIFIC: the decorator's RETURN value is the plain function.

    PFW's tier tools call one another inside register() and fastmcp 3.4's
    @mcp.tool returns the plain function, so returning the guarded wrapper
    would bound an inner call a second time and stamp it with the wrong tool's
    recovery note. The REGISTERED object is still guarded.
    """
    from patent_filewrapper_mcp.tools import _BoundedRegistrar

    fake = _FakeMCP()

    async def inner(limit: int = 10):
        return {"applications": [{"blob": "z" * 500} for _ in range(400)]}

    returned = _BoundedRegistrar(fake).tool(name="PFW_search_applications")(inner)

    assert returned is inner
    # ...and calling the returned function is NOT guarded.
    assert BOUNDS_KEY not in await returned()
    # ...while the registered one is.
    assert BOUNDS_KEY in await fake.registered["PFW_search_applications"]()


async def test_registration_proxy_is_byte_transparent_for_small_responses():
    """A response that already fits comes back as the IDENTICAL object — no
    copy, no `_bounds` key."""
    from patent_filewrapper_mcp.tools import _BoundedRegistrar

    fake = _FakeMCP()
    payload = {"success": True, "applications": [], "count": 0}

    async def small_tool():
        return payload

    _BoundedRegistrar(fake).tool(name="PFW_search_applications_minimal")(small_tool)

    result = await fake.registered["PFW_search_applications_minimal"]()
    assert result is payload
    assert BOUNDS_KEY not in result


async def test_registration_proxy_passes_plain_strings_through():
    """PFW_get_guidance returns markdown, not JSON — it must not be touched."""
    from patent_filewrapper_mcp.tools import _BoundedRegistrar

    fake = _FakeMCP()

    async def guidance_tool(section: str = "overview"):
        return "# Markdown guidance\n\nnot JSON at all"

    _BoundedRegistrar(fake).tool(name="PFW_get_guidance")(guidance_tool)

    assert await fake.registered["PFW_get_guidance"]() == "# Markdown guidance\n\nnot JSON at all"


async def test_registration_proxy_handles_the_imperative_form():
    """admin_tools registers with mcp.tool(name=...)(fn) rather than as a
    decorator; the proxy must guard that path too."""
    from patent_filewrapper_mcp.tools import _BoundedRegistrar

    fake = _FakeMCP()

    async def admin_tool(action: str = "list"):
        return {"action": action, "report": "y" * 200_000}

    _BoundedRegistrar(fake).tool(name="pfw_manage_users")(admin_tool)

    result = await fake.registered["pfw_manage_users"]()
    assert measure_chars(result) <= response_char_budget()
    assert result[BOUNDS_KEY]["applied"] is True
    assert len(result["report"]) < 200_000


async def test_unlisted_tool_with_many_small_records_is_marked_not_shrunk():
    """A KNOWN LIMIT of the default config, pinned so it stays visible.

    The default `_DEFAULT_BOUNDS` has no bag spec, and the text fallback only
    halves the single LARGEST string. A response made of many small records
    (no one string big enough to matter) therefore CANNOT be brought under
    budget — the guard shrinks the one string it can find, marks what it did,
    and returns an oversized payload rather than silently dropping records it
    was never told how to drop. This is vendored-module behavior, identical in
    FPD and PTAB.

    The fix for any tool that actually hits this is a bag spec in _TOOL_BOUNDS,
    not a change to the shared module. `pfw_manage_users` is deliberately left
    unlisted, matching FPD's `FPD_manage_users` and PTAB's `ptab_manage_users`.
    """
    from patent_filewrapper_mcp.tools import _BoundedRegistrar

    fake = _FakeMCP()

    async def many_small():
        return {"users": [{"email": f"u{i}@example.com", "pad": "y" * 300} for i in range(400)]}

    _BoundedRegistrar(fake).tool(name="pfw_manage_users")(many_small)

    result = await fake.registered["pfw_manage_users"]()
    assert result[BOUNDS_KEY]["applied"] is True
    assert len(result["users"]) == 400  # no record was silently dropped
    # The marker never claims success it did not achieve.
    assert measure_chars(result) > response_char_budget()
    assert "truncated to fit" in result[BOUNDS_KEY]["note"]


async def test_unlisted_tool_gets_the_default_budget_and_text_fallback():
    """Coverage is 100% without per-tool wiring: a tool with no _TOOL_BOUNDS
    entry still gets the response budget plus the largest-string fallback."""
    from patent_filewrapper_mcp.tools import _BoundedRegistrar

    fake = _FakeMCP()

    async def unlisted():
        return {"application_number": "14171705", "blob": "y" * 200_000}

    _BoundedRegistrar(fake).tool(name="PFW_get_term_adjustment")(unlisted)

    result = await fake.registered["PFW_get_term_adjustment"]()
    assert result[BOUNDS_KEY]["stages"] == ["truncated"]
    assert len(result["blob"]) < 200_000


async def test_content_tools_use_the_higher_content_budget():
    from patent_filewrapper_mcp.tools import _BoundedRegistrar

    size = response_char_budget() + 20_000
    assert size < content_char_budget()

    for tool_name in ("PFW_get_document_content_with_ocr", "PFW_get_oa_text"):
        fake = _FakeMCP()

        async def content_tool():
            return {"text": "z" * size}

        _BoundedRegistrar(fake).tool(name=tool_name)(content_tool)

        result = await fake.registered[tool_name]()
        # Comfortably over the RESPONSE budget but under the CONTENT budget, so
        # the guard leaves it alone.
        assert measure_chars(result) > response_char_budget()
        assert BOUNDS_KEY not in result


async def test_custom_fields_search_slims_nested_bags_before_dropping_records():
    """PFW_search_applications takes a caller-supplied `fields` list, so a
    record can drag in documentBag / associatedDocuments that the tiers
    exclude. Those get slimmed before whole applications are dropped."""
    from patent_filewrapper_mcp.tools import _BoundedRegistrar

    fake = _FakeMCP()

    async def custom_tool():
        return {
            "success": True,
            "applications": [
                {
                    "applicationNumberText": f"1{i:07d}",
                    "documentBag": [
                        {
                            "documentIdentifier": f"DOC{i}{j}",
                            "documentCode": "CTNF",
                            "downloadOptionBag": [
                                {"mimeTypeIdentifier": "PDF", "downloadUrl": "u" * 250}
                            ],
                        }
                        for j in range(12)
                    ],
                }
                for i in range(20)
            ],
        }

    _BoundedRegistrar(fake).tool(name="PFW_search_applications")(custom_tool)

    result = await fake.registered["PFW_search_applications"]()
    bounds = result[BOUNDS_KEY]
    assert "slimmed" in bounds["stages"]
    assert "downloadOptionBag" in bounds["slimmed_fields"]
    for record in result["applications"]:
        for doc in record["documentBag"]:
            assert "downloadOptionBag" not in doc
            assert "documentIdentifier" in doc


def test_registration_proxy_passes_other_attributes_through():
    from patent_filewrapper_mcp.tools import _BoundedRegistrar

    fake = _FakeMCP()
    fake.custom_route = lambda *a, **k: "routed"

    assert _BoundedRegistrar(fake).custom_route() == "routed"


def test_every_registered_tool_name_is_covered():
    """Either an explicit _TOOL_BOUNDS entry or the default config — the point
    is that no tool escapes the guard. The name list is the full registered
    surface (17 tools); if a tool is added and not listed here the count
    assertion below fails loudly."""
    from patent_filewrapper_mcp.tools import _DEFAULT_BOUNDS, _TOOL_BOUNDS, _bound_result

    all_tools = [
        "PFW_search_applications",
        "PFW_search_applications_minimal",
        "PFW_search_applications_balanced",
        "PFW_search_inventor",
        "PFW_search_inventor_minimal",
        "PFW_search_inventor_balanced",
        "PFW_get_application_documents",
        "PFW_get_document_content_with_ocr",
        "PFW_get_document_download",
        "PFW_get_patent_or_application_xml",
        "PFW_get_granted_patent_documents_download",
        "PFW_get_oa_rejections",
        "PFW_get_oa_text",
        "PFW_get_family",
        "PFW_get_term_adjustment",
        "PFW_get_guidance",
        "pfw_manage_users",
    ]
    assert len(all_tools) == 17
    assert set(_TOOL_BOUNDS) <= set(all_tools)
    for name in all_tools:
        # A small payload is a no-op for every configuration.
        assert _bound_result({"ok": True}, name) == {"ok": True}
    assert _DEFAULT_BOUNDS["bags"] == ()


def test_registered_tool_names_match_the_source():
    """_TOOL_BOUNDS keys must be real tool names — a typo would silently give
    that tool the default config instead of its bag specs."""
    import pathlib
    import re

    from patent_filewrapper_mcp.tools import _TOOL_BOUNDS

    tools_dir = pathlib.Path(__file__).resolve().parents[1] / "src" / "patent_filewrapper_mcp" / "tools"
    registered = set()
    for path in tools_dir.glob("*.py"):
        registered.update(re.findall(r'mcp\.tool\(\s*\n?\s*name="([^"]+)"', path.read_text()))

    assert len(registered) == 17
    assert set(_TOOL_BOUNDS) <= registered
