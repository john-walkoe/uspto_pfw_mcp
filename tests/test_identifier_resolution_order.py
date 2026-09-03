"""Resolve the RAW identifier FIRST, validate the application number AFTER.

The evals harness (the 2026-08-31 Agent Seer evaluation plan,
"Real findings" #0) caught a live wrong-answer bug: the official slashed serial
"11/752,072" — the format printed on every USPTO filing receipt — was honoured
by PFW_get_oa_rejections and PFW_get_oa_text and silently discarded by
PFW_get_application_documents, PFW_get_family and PFW_get_term_adjustment.

Root cause: those three called `validate_app_number()` BEFORE resolution.
`validate_app_number` strips every non-digit, so resolution saw the bare
8-digit "11752072", which IS ambiguous, took the patent lane, and answered
about patent 11,752,072 (application 16816197) with `identifier_ambiguous:
true` and no warning that a slash had ever been typed.

    input "11/752,072"    correct 11752072       pre-fix 16816197
    input "12/539,322"    correct 12539322       pre-fix 17996652

Every identifier-taking tool now calls `util.identifier_resolution.
resolve_or_error`, which owns the order, so the five tools cannot drift apart
again. Both halves are pinned here: the behaviour (four inputs x five tools)
and the structure (no tool resolves an identifier it has already validated).

Hermetic: no network, no FastMCP server, no USPTO key beyond a placeholder.
"""

import ast
import pathlib

import pytest

from patent_filewrapper_mcp.util.identifier_resolution import resolve_or_error


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _CaptureMCP:
    """Collects the functions each tools module registers."""

    def __init__(self):
        self.tools = {}

    def tool(self, *args, **kwargs):
        if args and callable(args[0]):
            fn = args[0]
            self.tools[kwargs.get("name") or fn.__name__] = fn
            return fn

        def decorator(fn):
            self.tools[kwargs.get("name") or fn.__name__] = fn
            return fn

        return decorator


#: The live patent lane, probed 2026-08-30/31 against api.uspto.gov. Both of
#: these 8-digit values ARE granted patent numbers, which is exactly why the
#: bare form is ambiguous and the slashed form must not be.
_PATENT_LANE = {
    "applicationMetaData.patentNumber:11752072": {
        "applicationNumberText": "16816197",
        "applicationMetaData": {"patentNumber": "11752072"},
    },
    "applicationMetaData.patentNumber:12539322": {
        "applicationNumberText": "17996652",
        "applicationMetaData": {"patentNumber": "12539322"},
    },
}


class _FakeClient:
    """One stand-in for every application-scoped call the five tools make."""

    def __init__(self, hits=None):
        self.hits = dict(_PATENT_LANE if hits is None else hits)
        self.queries = []
        self.app_numbers = []

    async def lookup_identifier_lane(self, query):
        self.queries.append(query)
        return self.hits.get(query)

    async def get_documents(self, app_number, **kwargs):
        self.app_numbers.append(app_number)
        return {
            "application_number": app_number,
            "count": 1,
            "documentBag": [{"documentCode": "CTNF", "documentIdentifier": "X"}],
            "summary": {},
        }

    async def get_continuity(self, app_number):
        self.app_numbers.append(app_number)
        return {"application_number": app_number, "continuity_data": {}}

    async def get_foreign_priority(self, app_number):
        return {"foreign_priority_bag": []}

    async def get_term_adjustment(self, app_number):
        self.app_numbers.append(app_number)
        return {"term_adjustment_data": None}


class _FakeOAClient:
    """Stands in for OARejectionClient / OATextClient."""

    def __init__(self):
        self.criteria = []

    async def search(self, criteria, start=0, rows=10):
        self.criteria.append(criteria)
        return {"response": {"docs": [], "numFound": 0}}

    def extract_body_text(self, doc):
        return doc.get("_body", "")

    def extract_section_text(self, doc, section):
        return ""


@pytest.fixture
def tool_modules(monkeypatch):
    """The five identifier-taking tools, each wired to one fake client."""
    monkeypatch.setenv("USPTO_API_KEY", "test-uspto-key-0123456789")
    from patent_filewrapper_mcp.tools import (
        document_tools,
        family_tools,
        oa_tools,
        term_tools,
    )

    client = _FakeClient()
    oa_client = _FakeOAClient()
    tools = {}
    for mod in (document_tools, family_tools, oa_tools, term_tools):
        fake = _CaptureMCP()
        mod.register(fake)
        tools.update(fake.tools)
        monkeypatch.setattr(mod, "_client", lambda c=client: c)
    monkeypatch.setattr(oa_tools, "_get_oa_rejection_client", lambda: oa_client)
    monkeypatch.setattr(oa_tools, "_get_oa_text_client", lambda: oa_client)
    return tools, client


async def _call(tools, tool_name, identifier):
    """Every one of the five takes the identifier first and positionally."""
    return await tools[tool_name](identifier)


_TOOLS = [
    "PFW_get_application_documents",
    "PFW_get_family",
    "PFW_get_term_adjustment",
    "PFW_get_oa_rejections",
    "PFW_get_oa_text",
]


# ---------------------------------------------------------------------------
# Behaviour: a slashed serial is unambiguous, on every tool
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tool_name", _TOOLS)
@pytest.mark.parametrize("slashed, serial", [("11/752,072", "11752072"),
                                             ("12/539,322", "12539322")])
@pytest.mark.asyncio
async def test_slashed_serial_takes_the_application_lane(tool_modules, tool_name,
                                                         slashed, serial):
    tools, client = tool_modules

    result = await _call(tools, tool_name, slashed)

    assert result["application_number"] == serial, (
        f"{tool_name} answered about {result['application_number']} for {slashed}"
    )
    assert result["identifier_resolved_as"] == "application"
    assert result["identifier_input"] == slashed
    # `identifier_ambiguous` is the marker the caller would have to notice; a
    # slashed serial is not ambiguous, so it must not be set.
    assert "identifier_ambiguous" not in result
    # The lane list says WHY, and the patent lane was never queried.
    assert f"applicationNumberText:{serial}" in result["identifier_lanes_tried"][0]
    assert "unambiguous application format" in result["identifier_lanes_tried"][0]
    assert not any(q.startswith("applicationMetaData.patentNumber:") for q in client.queries)


@pytest.mark.parametrize("tool_name", _TOOLS)
@pytest.mark.parametrize("bare, patent_application", [("11752072", "16816197"),
                                                      ("12539322", "17996652")])
@pytest.mark.asyncio
async def test_bare_eight_digits_still_resolves_through_the_patent_lane(
    tool_modules, tool_name, bare, patent_application
):
    """The bare form genuinely IS both, so the API decides and the response
    says which lane answered. This is the behaviour the slash fix must NOT
    change."""
    tools, client = tool_modules

    result = await _call(tools, tool_name, bare)

    assert result["application_number"] == patent_application
    assert result["identifier_resolved_as"] == "patent"
    assert result["identifier_ambiguous"] is True
    assert client.queries[0] == f"applicationMetaData.patentNumber:{bare}"


@pytest.mark.parametrize("tool_name", _TOOLS)
@pytest.mark.asyncio
async def test_the_resolved_number_is_what_reaches_the_api(tool_modules, tool_name):
    """The slash never reaches a USPTO query — validation still runs, it just
    runs on the RESOLVED value."""
    tools, client = tool_modules
    oa = tool_name.startswith("PFW_get_oa_")

    await _call(tools, tool_name, "11/752,072")

    if oa:
        return  # the OA tools query Solr, asserted in the lanes check above
    assert client.app_numbers, f"{tool_name} made no downstream call"
    assert all(n == "11752072" for n in client.app_numbers)


# ---------------------------------------------------------------------------
# content_type: the caller can force a lane on any resolving tool
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tool_name", _TOOLS)
@pytest.mark.parametrize("bare", ["11752072", "12539322"])
@pytest.mark.asyncio
async def test_content_type_application_skips_the_patent_lane(tool_modules, tool_name,
                                                              bare):
    """The slash format is not the only escape hatch: content_type='application'
    forces the application lane on a bare 8-digit number, and the patent lane is
    never queried even though a granted patent carries those digits."""
    tools, client = tool_modules

    result = await tools[tool_name](bare, content_type="application")

    assert result["application_number"] == bare
    assert result["identifier_resolved_as"] == "application"
    assert "identifier_ambiguous" not in result
    assert not any(q.startswith("applicationMetaData.patentNumber:") for q in client.queries)
    assert "content_type='application'" in result["identifier_note"]


@pytest.mark.parametrize("tool_name", _TOOLS)
@pytest.mark.asyncio
async def test_content_type_auto_is_the_unchanged_default(tool_modules, tool_name):
    """Passing the default explicitly must behave exactly like not passing it."""
    tools, client = tool_modules

    result = await tools[tool_name]("12539322", content_type="auto")

    assert result["application_number"] == "17996652"
    assert result["identifier_resolved_as"] == "patent"
    assert client.queries[0] == "applicationMetaData.patentNumber:12539322"


# ---------------------------------------------------------------------------
# The centralised entry point
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_or_error_validates_after_resolving():
    client = _FakeClient()
    resolution, error = await resolve_or_error(client, " 11/752,072 ")
    assert error is None
    assert resolution.application_number == "11752072"
    assert resolution.resolved_as == "application"


@pytest.mark.asyncio
async def test_resolve_or_error_rejects_an_empty_identifier():
    resolution, error = await resolve_or_error(_FakeClient(), "   ")
    assert resolution is None
    assert error["status_code"] == 400
    assert "empty" in error["message"].lower()


@pytest.mark.asyncio
async def test_resolve_or_error_reports_an_unresolvable_identifier():
    """A 7-digit value reads as a patent number; when no patent carries it the
    caller is told, rather than being handed a stranger's application."""
    resolution, error = await resolve_or_error(_FakeClient(hits={}), "1234567")
    assert error["status_code"] == 404
    assert error["identifier_resolved_as"] == "unresolved"
    assert resolution.application_number is None


@pytest.mark.asyncio
async def test_resolve_or_error_rejects_a_too_short_resolved_number():
    """Validation still happens — it just happens LAST."""
    resolution, error = await resolve_or_error(_FakeClient(hits={}), "12/3")
    assert error is not None
    assert error["status_code"] == 400
    assert "too short" in error["message"].lower()


# ---------------------------------------------------------------------------
# Structure: the five tools cannot drift apart again
# ---------------------------------------------------------------------------

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "patent_filewrapper_mcp"

#: (module file, function name) for every tool that resolves an identifier.
_RESOLVING_TOOLS = [
    ("tools/document_tools.py", "pfw_get_application_documents"),
    ("tools/document_tools.py", "pfw_get_granted_patent_documents_download"),
    ("tools/family_tools.py", "pfw_get_family"),
    ("tools/term_tools.py", "pfw_get_term_adjustment"),
    ("tools/oa_tools.py", "pfw_get_oa_rejections"),
    ("tools/oa_tools.py", "pfw_get_oa_text"),
]


def _function_node(relative_path: str, function_name: str):
    source = (_SRC / relative_path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == function_name:
            return node, source
    raise AssertionError(f"{function_name} not found in {relative_path}")


def _function_source(relative_path: str, function_name: str) -> str:
    node, source = _function_node(relative_path, function_name)
    return ast.get_source_segment(source, node)


@pytest.mark.parametrize("relative_path, function_name", _RESOLVING_TOOLS)
def test_no_resolving_tool_validates_before_it_resolves(relative_path, function_name):
    """`validate_app_number` inside one of these functions is the bug itself:
    it strips the slash on the way in. The only legitimate caller is
    `resolve_or_error`, which runs it on the RESOLVED number."""
    body = _function_source(relative_path, function_name)
    assert "resolve_or_error(" in body, f"{function_name} must resolve through resolve_or_error"
    assert "validate_app_number(" not in body, (
        f"{function_name} calls validate_app_number itself; that strips the slash off a "
        "serial before resolution can see it. resolve_or_error validates after resolving."
    )


@pytest.mark.parametrize("relative_path, function_name", _RESOLVING_TOOLS)
def test_every_resolving_tool_exposes_and_forwards_content_type(relative_path,
                                                                function_name):
    """A resolving tool that cannot be told which lane to use leaves the caller
    no escape from the 8-digit ambiguity except reformatting the identifier, and
    a tool that accepts `content_type` without forwarding it is worse than one
    that never offered it."""
    node, _ = _function_node(relative_path, function_name)

    params = [a.arg for a in node.args.args + node.args.kwonlyargs]
    assert "content_type" in params, f"{function_name} does not expose content_type"

    forwarded = False
    for call in (n for n in ast.walk(node) if isinstance(n, ast.Call)):
        if getattr(call.func, "id", None) != "resolve_or_error":
            continue
        names = [a.id for a in call.args if isinstance(a, ast.Name)]
        names += [k.value.id for k in call.keywords
                  if isinstance(k.value, ast.Name)]
        forwarded = forwarded or "content_type" in names
    assert forwarded, (
        f"{function_name} accepts content_type but never passes it to resolve_or_error, "
        "so the parameter would be silently ignored."
    )
