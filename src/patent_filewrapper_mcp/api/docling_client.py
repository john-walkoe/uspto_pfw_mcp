"""Docling-serve REST client for patent PDF OCR extraction.

Posts PDF bytes to a running docling-serve instance via /v1/convert/file.
Supports local Docker (default: http://localhost:5001) or remote instances
(e.g. https://docling.[yourdomain].com).

Scanned USPTO documents can be large (20-50 pages). EasyOCR processing time
scales with page count — allow 10-30 seconds per page on CPU hardware.
The default read timeout is 300 seconds (5 minutes); tune with DOCLING_TIMEOUT.

Env vars:
    DOCLING_SERVE_URL   – Base URL of the docling-serve instance.
    DOCLING_TIMEOUT     – Read timeout in seconds for OCR processing (default: 300).
                          Increase for very large documents, e.g. DOCLING_TIMEOUT=600.
    DOCLING_MAX_PAGES   – Skip Docling for documents exceeding this page count (default: 25).
                          Prevents tool call timeouts on large scanned documents.
                          EasyOCR on CPU takes ~10-30s/page — a 60-page PTAB petition
                          would exceed Claude Desktop's ~5-10 min tool call timeout.
"""

import os
import httpx
from typing import Optional

from ..shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)

_DEFAULT_URL = "http://localhost:5001"
_DEFAULT_TIMEOUT = 300.0   # 5 minutes — EasyOCR scales ~10-30s/page on CPU
_DEFAULT_MAX_PAGES = 25    # skip Docling above this — prevents MCP tool call timeouts


class DoclingClient:
    """REST client for docling-serve PDF extraction.

    Accepts raw PDF bytes and posts them to the docling-serve
    /v1/convert/file endpoint, returning plain text.
    """

    def __init__(self) -> None:
        self.url: Optional[str] = os.getenv("DOCLING_SERVE_URL", "").strip() or None
        self.timeout = float(os.getenv("DOCLING_TIMEOUT", str(_DEFAULT_TIMEOUT)))
        self.max_pages = int(os.getenv("DOCLING_MAX_PAGES", str(_DEFAULT_MAX_PAGES)))

    def is_available(self) -> bool:
        """Return True if DOCLING_SERVE_URL is configured."""
        return bool(self.url)

    def within_page_limit(self, page_count: int) -> bool:
        """Return True if page_count is within the DOCLING_MAX_PAGES threshold."""
        return page_count <= self.max_pages

    async def extract(self, pdf_content: bytes, filename: str = "document.pdf") -> str:
        """Send PDF bytes to docling-serve and return extracted plain text.

        Args:
            pdf_content: Raw PDF bytes.
            filename: Filename hint sent to the server (default: document.pdf).

        Returns:
            Extracted plain text (non-empty).

        Raises:
            ValueError: If Docling is not configured, the server returns an
                        error, or the extracted text is empty.
            httpx.HTTPError: On network errors.
        """
        if not self.is_available():
            raise ValueError(
                "Docling extraction is not configured. "
                "Set DOCLING_SERVE_URL to enable (e.g. http://localhost:5001 "
                "or https://docling.[yourdomain].com)."
            )

        url = f"{self.url.rstrip('/')}/v1/convert/file"
        logger.info(f"Sending {filename} ({len(pdf_content)} bytes) to docling-serve: {url}")

        # Use split timeouts: short connect (10s), long read (DOCLING_TIMEOUT) for OCR processing.
        # Write timeout is generous (60s) for large PDF uploads over slower connections.
        timeout = httpx.Timeout(connect=10.0, read=self.timeout, write=60.0, pool=5.0)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    url,
                    files={"files": (filename, pdf_content, "application/pdf")},
                    data={"to_formats": "text", "abort_on_error": "false"},
                )
                response.raise_for_status()

            data = response.json()
            status = data.get("status", "unknown")

            if status == "failure":
                errors = data.get("errors", [])
                raise ValueError(f"Docling conversion failed: {errors}")

            text = (data.get("document") or {}).get("text_content") or ""

            if not text.strip():
                raise ValueError(
                    f"Docling returned empty text for {filename} (status={status}). "
                    "The document may be encrypted, corrupted, or an unsupported format."
                )

            logger.info(f"Docling extracted {len(text)} chars from {filename} (status={status})")
            return text.strip()

        except httpx.ConnectError:
            raise ValueError(
                f"Could not connect to docling-serve at {self.url}. "
                "Check that the server is running and DOCLING_SERVE_URL is correct "
                "(e.g. http://localhost:5001 or https://docling.[yourdomain].com)."
            )
        except httpx.TimeoutException:
            raise ValueError(
                f"Docling timed out processing {filename} after {self.timeout:.0f}s. "
                "Large scanned documents take longer with EasyOCR (~10-30s/page on CPU). "
                f"Increase the limit by setting DOCLING_TIMEOUT=600 (or higher) in your MCP config."
            )
        except httpx.HTTPStatusError as exc:
            raise ValueError(
                f"Docling server returned HTTP {exc.response.status_code}: "
                f"{exc.response.text[:200]}"
            ) from exc

    async def health_check(self) -> bool:
        """Return True if the docling server is reachable and healthy."""
        if not self.is_available():
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.url.rstrip('/')}/health")
                return resp.status_code == 200
        except Exception:
            return False
