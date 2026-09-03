"""
OCR Service for extracting content from patent documents using Mistral API

Single owner of the Mistral OCR call path (audit F1): EnhancedPatentClient
delegates here instead of carrying its own copy, so the model slug, timeout,
rate limiting, and cost-control page cap live in exactly one place.
"""
import httpx
import os
import time
from typing import Dict, Any, Optional

from ..api.helpers import format_error_response, generate_request_id
from ..exceptions import OCRRateLimitError
from ..shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)


#: Placeholder strings that should be treated as "no key set" rather than
#: passed to Mistral as a credential. Overridable/extendable via
#: MISTRAL_PLACEHOLDER_PATTERNS (comma-separated).
#:
#: This list is the UNION of two that had already drifted apart (audit D-2):
#: api/enhanced_client.py carried its own copy with `change_me`/`replace_me`
#: and OCRService's carried `temp_key`/`test_key`/`example_key` and four more.
#: EnhancedPatentClient.__init__ validated with its list and handed the
#: survivor to OCRService, which took the `api_key is not None` branch, so six
#: of the service's patterns never ran in the server path. One owner now.
_PLACEHOLDER_PATTERNS = (
    "your_mistral_api_key_here",
    "your_key_here",
    "your_api_key_here",
    "placeholder",
    "optional",
    "change_me",
    "replace_me",
    "mistral_api_key",
    "enter_your_key",
    "add_your_key",
    "your_mistral_key",
    "api_key_here",
    "replace_with_your_key",
    "insert_key_here",
    "temp_key",
    "test_key",
    "example_key",
)

#: Anything shorter than this is a placeholder, not a credential.
_MIN_KEY_LENGTH = 10


def validate_mistral_api_key(raw_key: Optional[str]) -> Optional[str]:
    """Return the key, or None when it is absent or a known placeholder.

    Prevents placeholder text being used as a real API key, which would
    produce an authentication error instead of the "no OCR configured"
    guidance the tier waterfall is written to give.
    """
    if not raw_key:
        return None

    env_patterns = os.getenv("MISTRAL_PLACEHOLDER_PATTERNS", "")
    patterns = list(_PLACEHOLDER_PATTERNS)
    if env_patterns:
        patterns.extend(p.strip() for p in env_patterns.split(",") if p.strip())

    normalized_key = raw_key.lower().strip()
    for pattern in patterns:
        if pattern in normalized_key:
            logger.info(
                f"Detected placeholder pattern '{pattern}' in MISTRAL_API_KEY. "
                "Treating as missing key."
            )
            return None

    if len(raw_key.strip()) < _MIN_KEY_LENGTH:
        logger.info(
            f"Detected suspiciously short API key ({len(raw_key)} chars). "
            "Treating as missing key."
        )
        return None

    return raw_key.strip()


class OCRService:
    """Service for handling OCR operations with Mistral API"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        limits: Optional[httpx.Limits] = None,
    ):
        """Initialize OCR service with rate limiting.

        Args:
            api_key: Pre-validated Mistral key; when None, loaded from secure
                storage / MISTRAL_API_KEY and validated here.
            model: OCR model slug; default env MISTRAL_OCR_MODEL or
                mistral-ocr-latest.
            timeout: httpx timeout; default env MISTRAL_OCR_TIMEOUT or 30s.
            limits: optional httpx.Limits for connection pooling.
        """
        if api_key is not None:
            self.mistral_api_key = api_key
        else:
            # Check secure storage first, then environment
            raw_mistral_key = None
            try:
                from ..shared_secure_storage import get_mistral_api_key
                raw_mistral_key = get_mistral_api_key()
            except Exception:
                # Fall back to environment variable if secure storage fails
                pass
            if not raw_mistral_key:
                raw_mistral_key = os.getenv("MISTRAL_API_KEY")
            self.mistral_api_key = self._validate_mistral_api_key(raw_mistral_key)

        self.mistral_base_url = "https://api.mistral.ai/v1"
        # Model slug: `mistral-ocr-latest` tracks Mistral's current GA model;
        # pin a dated slug (e.g. mistral-ocr-2503) via MISTRAL_OCR_MODEL.
        self.mistral_ocr_model = model or os.getenv("MISTRAL_OCR_MODEL", "mistral-ocr-latest")
        self.ocr_timeout = timeout if timeout is not None else float(os.getenv("MISTRAL_OCR_TIMEOUT", "30.0"))
        self.ocr_http_limits = limits
        # Cost-control page cap per document
        self.ocr_max_pages = int(os.getenv("MISTRAL_OCR_MAX_PAGES", "50"))

        # OCR rate limiting configuration
        self.ocr_calls = []  # List of timestamps for OCR calls
        self.ocr_rate_limit = 10  # Max OCR calls per minute
        self.ocr_window = 60  # Time window in seconds

        # Cumulative daily PAGE budget. The per-minute call limit caps the
        # burst RATE but not the total: 10 calls/minute at 50 pages each is
        # 720,000 pages a day, and this is metered spend (audit M-14). Pages
        # are the billed unit, so the budget is in pages, not calls.
        self.ocr_daily_page_budget = int(
            os.getenv("MISTRAL_OCR_DAILY_PAGE_BUDGET", "2000")
        )
        self._ocr_pages_today = 0
        self._ocr_budget_day = None

    def _validate_mistral_api_key(self, raw_key: Optional[str]) -> Optional[str]:
        """Bound alias for `validate_mistral_api_key` (audit D-2)."""
        return validate_mistral_api_key(raw_key)

    def _check_ocr_daily_budget(self, request_id: str, pages: int) -> None:
        """Refuse an OCR call that would exceed today's page budget.

        Checked BEFORE the upload, so a refusal costs nothing. Set
        MISTRAL_OCR_DAILY_PAGE_BUDGET to 0 or below to disable.

        Raises:
            OCRRateLimitError: carrying seconds until the budget resets.
        """
        if self.ocr_daily_page_budget <= 0:
            return

        self._roll_budget_day()

        if self._ocr_pages_today + pages > self.ocr_daily_page_budget:
            seconds_left = 86400 - (int(time.time()) % 86400)
            logger.warning(
                f"[{request_id}] OCR daily page budget reached: "
                f"{self._ocr_pages_today}/{self.ocr_daily_page_budget} pages"
            )
            raise OCRRateLimitError(
                f"Daily OCR page budget reached "
                f"({self._ocr_pages_today}/{self.ocr_daily_page_budget} pages). "
                f"Resets in {seconds_left // 3600}h. Raise "
                f"MISTRAL_OCR_DAILY_PAGE_BUDGET to change it.",
                retry_after_seconds=seconds_left,
                request_id=request_id,
            )

    def _roll_budget_day(self) -> None:
        """Reset the counter when the UTC day has turned over."""
        today = time.strftime("%Y-%m-%d", time.gmtime())
        if self._ocr_budget_day != today:
            self._ocr_budget_day = today
            self._ocr_pages_today = 0

    def _record_ocr_pages(self, pages: int) -> None:
        """Charge pages against today's budget once they have been billed.

        Rolls the day FIRST: otherwise a charge recorded before the day was
        established was wiped by the next check's roll, so pages billed by the
        first call of a process went uncounted.
        """
        self._roll_budget_day()
        self._ocr_pages_today += max(0, pages)

    async def _delete_uploaded_file(self, client, headers, file_id, request_id) -> None:
        """Delete the PDF we uploaded to Mistral.

        Every OCR'd document used to accumulate in the account forever: an
        uncontrolled retention surface for client work product and a cost that
        grows with usage (audit resilience F-8). Best effort — a cleanup
        failure must not fail an extraction that already succeeded.
        """
        try:
            await client.delete(
                f"{self.mistral_base_url}/files/{file_id}", headers=headers
            )
        except Exception as e:
            logger.warning(
                f"[{request_id}] Uploaded-file cleanup failed "
                f"({type(e).__name__}); the file remains in the account"
            )

    def _check_ocr_rate_limit(self, request_id: str) -> None:
        """
        Check if OCR rate limit is exceeded and raise exception if so.

        Args:
            request_id: Request ID for logging

        Raises:
            OCRRateLimitError: If rate limit is exceeded
        """
        now = time.time()

        # Clean old calls outside the time window
        self.ocr_calls = [ts for ts in self.ocr_calls if now - ts < self.ocr_window]

        if len(self.ocr_calls) >= self.ocr_rate_limit:
            oldest_call = min(self.ocr_calls)
            wait_time = self.ocr_window - (now - oldest_call)
            logger.warning(f"[{request_id}] OCR rate limit exceeded. {len(self.ocr_calls)} calls in last {self.ocr_window}s")
            raise OCRRateLimitError(
                f"OCR rate limit exceeded. Maximum {self.ocr_rate_limit} calls per {self.ocr_window} seconds. "
                f"Try again in {wait_time:.0f} seconds.",
                retry_after_seconds=int(wait_time) + 1,
                request_id=request_id
            )

        # Record this call
        self.ocr_calls.append(now)
        logger.info(f"[{request_id}] OCR rate limit check passed. {len(self.ocr_calls)}/{self.ocr_rate_limit} calls in window")

    async def extract_document_content(self, pdf_content: bytes, page_count: int,
                                     app_number: str, document_identifier: str,
                                     page_offset: int = 0) -> Dict[str, Any]:
        """
        Extract document content using Mistral OCR API

        Args:
            pdf_content: PDF content as bytes
            page_count: Number of pages in the document
            app_number: Patent application number
            document_identifier: Document identifier
            page_offset: Number of document pages that precede this slice.
                `pdf_content` is the WINDOW when page_from/page_to were used,
                so Mistral's own page index restarts at 0 and the headers would
                read `=== PAGE 1 ===` for document page 51 while `page_window`
                said 51-53. The offset makes `=== PAGE N ===` the true document
                page on this branch, as it already is on the pypdf branch
                (api/enhanced_client.py::extract_with_pypdf2).

        Returns:
            Dictionary containing OCR-extracted content and metadata
        """
        request_id = generate_request_id()

        try:
            # Check if Mistral API key is available
            if not self.mistral_api_key:
                return format_error_response(
                    "MISTRAL_API_KEY environment variable is required for OCR content extraction. "
                    "Set it with: set MISTRAL_API_KEY=your_key_here (Windows) or export MISTRAL_API_KEY=your_key_here (Linux/Mac)"
                )

            # Rate limit AND cumulative budget, both before anything is
            # uploaded, so a refusal costs nothing.
            self._check_ocr_rate_limit(request_id)
            self._check_ocr_daily_budget(
                request_id, min(page_count, self.ocr_max_pages)
            )

            logger.info(f"[{request_id}] Starting OCR extraction for {app_number}/{document_identifier} ({page_count} pages)")

            # Step 1: Upload file to Mistral
            mistral_headers = {
                "Authorization": f"Bearer {self.mistral_api_key}",
            }

            files = {
                "file": ("document.pdf", pdf_content, "application/pdf")
            }

            data = {
                "purpose": "ocr"
            }

            # Split budgets. One shared 30s timeout covered both the multipart
            # upload (size-bound) and the OCR of up to MISTRAL_OCR_MAX_PAGES
            # pages (page-bound), and a 50-page OCR does not reliably finish in
            # 30s. When it did not, the upload had happened and Mistral had
            # already done and BILLED the work, and the timeout fell into a
            # catch-all that reported "appears to be a scanned image"
            # (audit resilience F-1).
            pages_to_ocr = min(page_count, self.ocr_max_pages)
            effective_timeout = max(
                self.ocr_timeout,
                float(os.getenv("MISTRAL_OCR_SECONDS_PER_PAGE", "6")) * pages_to_ocr,
            )
            client_kwargs = {"timeout": httpx.Timeout(effective_timeout, connect=10.0)}
            if self.ocr_http_limits is not None:
                client_kwargs["limits"] = self.ocr_http_limits
            async with httpx.AsyncClient(**client_kwargs) as client:
                upload_response = await client.post(
                    f"{self.mistral_base_url}/files",
                    headers=mistral_headers,
                    files=files,
                    data=data
                )
                upload_response.raise_for_status()
                upload_data = upload_response.json()
                file_id = upload_data.get("id")

                if not file_id:
                    return format_error_response("Failed to upload file to Mistral OCR service")

                try:
                    return await self._run_ocr(
                        client=client,
                        file_id=file_id,
                        pdf_content=pdf_content,
                        page_count=page_count,
                        page_offset=page_offset,
                        app_number=app_number,
                        document_identifier=document_identifier,
                        request_id=request_id,
                    )
                finally:
                    await self._delete_uploaded_file(
                        client, mistral_headers, file_id, request_id
                    )

        except OCRRateLimitError as e:
            logger.warning(f"[{request_id}] OCR rate limit exceeded: {e.message}")
            return format_error_response(e.message, e.status_code, e.request_id)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return format_error_response("Mistral API authentication failed - check MISTRAL_API_KEY")
            elif e.response.status_code == 402:
                logger.warning(f"Mistral API returned 402 (payment required) for {app_number}/{document_identifier}")
                return format_error_response("OCR capacity limit reached; try again later")
            else:
                return format_error_response(f"Mistral API error {e.response.status_code}: {e.response.text}")
        except Exception as e:
            # Log server-side; the caller gets a sanitized message. The
            # exception text used to be returned verbatim with no log line,
            # so the operator saw nothing and the caller saw whatever the
            # exception embedded (URLs, paths, provider text).
            logger.exception(f"OCR extraction failed ({type(e).__name__})")
            return format_error_response(
                "Failed to extract document content", exception=e
            )

    async def _run_ocr(
        self, *, client, file_id, pdf_content, page_count, page_offset,
        app_number, document_identifier, request_id,
    ) -> Dict[str, Any]:
        """OCR an already-uploaded file and build the result envelope.

        Split out of extract_document_content so the upload has a `finally`
        that deletes the file on every path, including the error and
        cancellation ones (audit resilience F-8).
        """
        # Step 2: Process with OCR
        ocr_payload = {
            "model": self.mistral_ocr_model,
            "document": {
                "type": "file",
                "file_id": file_id
            },
            # Cost-control page cap (truncation surfaced in the result)
            "pages": list(range(min(page_count, self.ocr_max_pages))),
            "include_image_base64": False  # Save tokens
        }

        ocr_response = await client.post(
            f"{self.mistral_base_url}/ocr",
            headers={
                "Authorization": f"Bearer {self.mistral_api_key}",
                "Content-Type": "application/json"
            },
            json=ocr_payload
        )
        ocr_response.raise_for_status()
        ocr_data = ocr_response.json()

        # Extract content from OCR response
        pages_processed = ocr_data.get("usage_info", {}).get("pages_processed", 0)
        # Internal cost accounting (operator-facing log only — never
        # surfaced in tool responses)
        estimated_cost = pages_processed * 0.001  # $1 per 1000 pages
        self._record_ocr_pages(pages_processed)
        logger.info(
            f"[{request_id}] OCR spend: ${estimated_cost:.4f} for {pages_processed} pages "
            f"({self._ocr_pages_today}/{self.ocr_daily_page_budget} today)"
        )

        # Combine all page content
        extracted_content = []
        for page in ocr_data.get("pages", []):
            page_markdown = page.get("markdown", "")
            if page_markdown.strip():
                page_number = page.get('index', 0) + 1 + page_offset
                extracted_content.append(f"=== PAGE {page_number} ===\n{page_markdown}")

        full_content = "\n\n".join(extracted_content)

        result = {
            "success": True,
            "application_number": app_number,
            "document_identifier": document_identifier,
            "page_count": page_count,
            "page_offset": page_offset,
            "pages_processed": pages_processed,
            "extracted_content": full_content,
            "structured_output": "markdown",
            "ocr_model": ocr_data.get("model", self.mistral_ocr_model),
            "file_size_bytes": len(pdf_content),
            "document_annotation": ocr_data.get("document_annotation", ""),
            "usage_info": ocr_data.get("usage_info", {}),
            "note": "Content extracted using Mistral OCR - supports scanned documents, formulas, and complex layouts"
        }
        # Surface silent truncation from the page cap (audit F48)
        pages_truncated = max(0, page_count - self.ocr_max_pages)
        if pages_truncated > 0:
            result["pages_truncated"] = pages_truncated
            result["truncation_note"] = (
                f"Only the first {self.ocr_max_pages} of {page_count} pages were "
                f"OCR'd (server page limit)."
            )
        return result

