#!/usr/bin/env python3
"""Proxy server basics: app construction, rate limiting, and a live
end-to-end document fetch through the proxy.

Split into a local part that always runs and a live part that needs a real
USPTO key. Previously the whole file signalled failure with `return False`,
which pytest reports as PASS, so the proxy could stop serving documents
entirely and this stayed green (audit T-4).
"""

import asyncio

import httpx
from conftest import requires_live_uspto

from patent_filewrapper_mcp.api.enhanced_client import EnhancedPatentClient
from patent_filewrapper_mcp.proxy.rate_limiter import rate_limiter
from patent_filewrapper_mcp.proxy.server import create_proxy_app

_APP_NUMBER = "19145362"
_DOC_IDENTIFIER = "MCMLYGLL182X243"


class TestLocal:
    def test_the_proxy_app_builds(self):
        assert create_proxy_app() is not None

    def test_the_rate_limiter_blocks_past_its_ceiling(self):
        """5 per 10s is the advertised limit; a 6th request in the window must
        be refused."""
        test_ip = "203.0.113.100"  # RFC 5737 example range; not the download tests' IP.
        # Buckets are keyed by (IP, policy) now (audit L-1).
        rate_limiter.requests.clear()

        verdicts = [rate_limiter.is_allowed(test_ip) for _ in range(6)]

        assert verdicts[: rate_limiter.max_requests] == [True] * rate_limiter.max_requests
        assert verdicts[rate_limiter.max_requests] is False, (
            "the rate limiter allowed a request past its ceiling"
        )


@requires_live_uspto
class TestLive:
    async def test_the_target_document_is_reachable_through_the_client(self):
        client = EnhancedPatentClient()
        docs_result = await client.get_documents(_APP_NUMBER)

        assert not docs_result.get("error"), (
            f"get_documents failed: {docs_result.get('message')}"
        )
        identifiers = {
            d.get("documentIdentifier") for d in docs_result.get("documentBag", [])
        }
        assert _DOC_IDENTIFIER in identifiers, (
            f"{_DOC_IDENTIFIER} missing from the documentBag of {_APP_NUMBER}"
        )

    async def test_the_proxy_serves_a_pdf_end_to_end(self):
        import uvicorn

        proxy_port = 8082
        server = uvicorn.Server(
            uvicorn.Config(
                create_proxy_app(),
                host="127.0.0.1",
                port=proxy_port,
                log_level="warning",
            )
        )
        server_task = asyncio.create_task(server.serve())
        await asyncio.sleep(2)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                health = await client.get(f"http://127.0.0.1:{proxy_port}/")
                assert health.status_code == 200, "proxy health check failed"

                download = await client.get(
                    f"http://127.0.0.1:{proxy_port}/download/"
                    f"{_APP_NUMBER}/{_DOC_IDENTIFIER}"
                )
                assert download.status_code == 200, (
                    f"download returned {download.status_code}"
                )
                assert download.headers.get("content-type") == "application/pdf"
                # Nothing is written to disk: the old version saved
                # test_download.pdf into the repo root on every run.
                assert len(download.content) > 1000, "PDF body implausibly small"
        finally:
            server.should_exit = True
            await server_task
