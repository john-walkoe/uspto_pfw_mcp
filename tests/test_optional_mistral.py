#!/usr/bin/env python3
"""Missing MISTRAL_API_KEY degrades gracefully rather than failing.

A user with only USPTO_API_KEY who asks for content from a document PyPDF2
cannot read should get actionable guidance, not an authentication error.

Calls the live USPTO ODP API. Previously this signalled failure with
`return False`, which pytest reports as PASS (audit T-4), and imported the
package as `src.patent_filewrapper_mcp`, creating a SECOND module object with
its own singletons so nothing here could be monkeypatched (audit T-5).
"""

import pytest
from conftest import requires_live_uspto

from patent_filewrapper_mcp.api.enhanced_client import EnhancedPatentClient

_APP_NUMBER = "17896175"
_DOC_IDENTIFIER = "test_doc_123"


@pytest.fixture
def client_without_mistral(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    return EnhancedPatentClient()


def test_the_client_constructs_without_a_mistral_key(client_without_mistral):
    """The paid tier is optional; its absence must not break construction."""
    assert client_without_mistral.mistral_api_key is None


@requires_live_uspto
async def test_auto_optimize_explains_itself_when_ocr_is_unavailable(
    client_without_mistral,
):
    result = await client_without_mistral.extract_document_content_hybrid(
        _APP_NUMBER, _DOC_IDENTIFIER, auto_optimize=True
    )
    assert isinstance(result, dict)
    assert not result.get("success"), "an unknown document identifier succeeded"
    # The point of the finding: the caller is told what to do, not just that
    # something failed.
    assert result.get("error") or result.get("message"), (
        "failure carried neither an error nor a message"
    )


@requires_live_uspto
async def test_a_direct_ocr_request_names_the_missing_key(client_without_mistral):
    result = await client_without_mistral.extract_document_content_hybrid(
        _APP_NUMBER, _DOC_IDENTIFIER, auto_optimize=False
    )
    assert isinstance(result, dict)
    assert not result.get("success")
