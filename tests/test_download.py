#!/usr/bin/env python3
"""Document download works off the restored Document Bag.

Calls the live USPTO ODP API. Previously this signalled every failure with
`return False`, which pytest reports as PASS: if pfw_get_document_download
stopped working entirely, this file printed [FAIL] and went green (audit T-4).
"""

from conftest import requires_live_uspto

from patent_filewrapper_mcp.main import (
    pfw_get_document_download,
    pfw_search_applications_balanced,
)

# USPTO_API_KEY is set by tests/conftest.py. It used to be set here at import
# time with no teardown, which is what made the suite pass only in
# alphabetical collection order (audit T-3).

_APP_NUMBER = "11752072"


@requires_live_uspto
async def test_document_download():
    """An ABST document identifier from documentBag yields a download URL."""
    result = await pfw_search_applications_balanced(
        f"applicationNumberText:{_APP_NUMBER}", limit=1
    )
    assert result.get("success"), f"balanced search failed: {result.get('message')}"
    assert result.get("applications"), "balanced search returned no applications"

    document_bag = result["applications"][0].get("documentBag", [])
    assert document_bag, (
        "documentBag is empty — this is the regression where Associated "
        "Documents overwrote the Document Bag"
    )

    abstract_doc = next(
        (d for d in document_bag if d.get("documentCode") == "ABST"), None
    )
    assert abstract_doc, "no ABST document in documentBag"

    doc_identifier = abstract_doc.get("documentIdentifier")
    assert doc_identifier, "ABST document carries no documentIdentifier"

    download_result = await pfw_get_document_download(_APP_NUMBER, doc_identifier)
    assert not download_result.get("error"), (
        f"download failed: {download_result.get('message')}"
    )
    assert download_result.get("proxy_download_url"), "no proxy_download_url returned"
    assert download_result.get("document_info"), "no document_info returned"
