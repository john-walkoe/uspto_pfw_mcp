"""pypdf parses applicant-filed PDFs; since audit 2026-10-12 M3 every parse
runs in a worker thread under PFW_PDF_PARSE_TIMEOUT_S, never on the event loop."""

import asyncio
import threading
import time

import pytest

from patent_filewrapper_mcp.api import enhanced_client as ec


def _pdf(pages: int) -> bytes:
    import io

    import pypdf

    writer = pypdf.PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


async def test_the_text_tier_parses_in_a_worker_thread(monkeypatch):
    seen = []
    real = ec._pypdf_extract_sync

    def spy(*args):
        seen.append(threading.current_thread() is threading.main_thread())
        return real(*args)

    monkeypatch.setattr(ec, "_pypdf_extract_sync", spy)
    client = ec.EnhancedPatentClient.__new__(ec.EnhancedPatentClient)
    status = {}
    text = await client.extract_with_pypdf2(_pdf(3), status)
    assert seen == [False]
    assert status["page_count"] == 3 and text.startswith("=== PAGE 1 ===")


async def test_a_slow_parse_times_out_without_blocking_the_loop(monkeypatch):
    monkeypatch.setenv("PFW_PDF_PARSE_TIMEOUT_S", "0.2")
    ticks = []

    async def ticker():
        for _ in range(5):
            ticks.append(time.monotonic())
            await asyncio.sleep(0.02)

    def slow():
        time.sleep(1.0)

    began = time.monotonic()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.gather(ec.run_pdf_parse(slow), ticker())
    assert time.monotonic() - began < 0.9
    assert len(ticks) == 5  # the loop kept running while the parse ran


@pytest.mark.parametrize("value", ["nan", "inf", "-1", "soon", "0"])
def test_a_bad_timeout_setting_uses_the_default(monkeypatch, value):
    monkeypatch.setenv("PFW_PDF_PARSE_TIMEOUT_S", value)
    assert ec.pdf_parse_timeout() == ec._DEFAULT_PDF_PARSE_TIMEOUT_S


async def test_page_count_parse_off_loop_and_unknown_on_timeout(monkeypatch):
    assert await ec._resolve_page_count_async({}, _pdf(4)) == (4, "pdf")
    assert await ec._resolve_page_count_async({"pageTotalQuantity": 9}, _pdf(4)) == (9, "downloadOptionBag")

    async def timed_out(*args):
        raise asyncio.TimeoutError

    monkeypatch.setattr(ec, "run_pdf_parse", timed_out)
    assert await ec._resolve_page_count_async({}, _pdf(4)) == (None, "unknown")
