"""PFW_get_family: the ambiguous-8-digit response note (2026-09-01 fix).

A real session called PFW_get_family("11752072") meaning application serial
11/752,072 and was silently answered about the unrelated granted patent
11,752,072 (application 16816197). Resolution is patent-number-first by
design, so the fix is disclosure, not rerouting: when a bare 8-digit input
was resolved through the patent lane, `identifier_note` says how it was read
and how to reach the application serial instead. A slash-comma serial and an
explicit content_type never carry that note.

Hermetic: no network, no FastMCP server, no USPTO key beyond a placeholder.
"""

import pytest


class _CaptureMCP:
    """Collects the functions the tools module registers."""

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


#: Live patent lane, probed 2026-08-30/31 against api.uspto.gov: 11752072 IS
#: a granted patent number (US 11,752,072 -> application 16816197), which is
#: exactly why the bare form is ambiguous.
_PATENT_LANE = {
    "applicationMetaData.patentNumber:11752072": {
        "applicationNumberText": "16816197",
        "applicationMetaData": {"patentNumber": "11752072"},
    },
}


class _FakeClient:
    def __init__(self, hits=None):
        self.hits = dict(_PATENT_LANE if hits is None else hits)
        self.queries = []

    async def lookup_identifier_lane(self, query):
        self.queries.append(query)
        return self.hits.get(query)

    async def get_continuity(self, app_number):
        return {"application_number": app_number, "continuity_data": {}}

    async def get_foreign_priority(self, app_number):
        return {"foreign_priority_bag": []}


@pytest.fixture
def family_tool(monkeypatch):
    monkeypatch.setenv("USPTO_API_KEY", "test-uspto-key-0123456789")
    from patent_filewrapper_mcp.tools import family_tools as mod

    fake = _CaptureMCP()
    mod.register(fake)
    client = _FakeClient()
    monkeypatch.setattr(mod, "_client", lambda: client)
    return fake.tools["PFW_get_family"], client


@pytest.mark.asyncio
async def test_bare_eight_digits_resolved_patent_first_carries_the_note(family_tool):
    tool, client = family_tool

    result = await tool("11752072")

    assert result["application_number"] == "16816197"
    assert result["identifier_resolved_as"] == "patent"
    assert result["identifier_ambiguous"] is True
    note = result["identifier_note"]
    assert 'Interpreted "11752072" as patent number 11,752,072' in note
    assert "(application 16816197)" in note
    assert "application serial 11/752,072" in note
    assert "re-call with that format or content_type='application'" in note


@pytest.mark.asyncio
async def test_slash_format_carries_no_ambiguity_note(family_tool):
    tool, client = family_tool

    result = await tool("11/752,072")

    assert result["application_number"] == "11752072"
    assert "identifier_ambiguous" not in result
    note = result.get("identifier_note", "")
    assert "Interpreted" not in note
    assert "re-call" not in note
    # The patent lane was never even probed.
    assert not any(
        q.startswith("applicationMetaData.patentNumber:") for q in client.queries
    )


@pytest.mark.asyncio
async def test_explicit_content_type_carries_no_ambiguity_note(family_tool):
    tool, client = family_tool

    result = await tool("11752072", content_type="application")

    assert result["application_number"] == "11752072"
    assert "identifier_ambiguous" not in result
    note = result.get("identifier_note", "")
    assert "Interpreted" not in note
    assert "re-call" not in note
    assert not any(
        q.startswith("applicationMetaData.patentNumber:") for q in client.queries
    )
