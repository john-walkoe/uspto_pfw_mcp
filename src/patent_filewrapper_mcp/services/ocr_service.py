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

    def _validate_mistral_api_key(self, raw_key: Optional[str]) -> Optional[str]:
        """
        Validate Mistral API key and detect common placeholder patterns.

        Args:
            raw_key: Raw API key from environment variable

        Returns:
            Valid API key or None if invalid/placeholder
        """
        if not raw_key:
            return None

        # Common placeholder patterns that should be treated as missing.
        # Allow override via MISTRAL_PLACEHOLDER_PATTERNS env var (comma-separated).
        # The default covers common mistake patterns; additional patterns can be added
        # without a code change.
        env_patterns = os.getenv("MISTRAL_PLACEHOLDER_PATTERNS", "")
        placeholder_patterns = [
            "your_mistral_api_key_here",
            "your_key_here",
            "your_api_key_here",
            "placeholder",
            "optional",
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
        ]
        if env_patterns:
            placeholder_patterns.extend([p.strip() for p in env_patterns.split(",") if p.strip()])

        normalized_key = raw_key.lower().strip()

        # Check against placeholder patterns
        for pattern in placeholder_patterns:
            if pattern in normalized_key:
                logger.info(f"Detected placeholder pattern '{pattern}' in MISTRAL_API_KEY. Treating as missing key.")
                return None

        # Additional check for very short keys that are likely placeholders
        if len(raw_key.strip()) < 10:
            logger.info(f"Detected suspiciously short API key ({len(raw_key)} chars). Treating as missing key.")
            return None

        return raw_key.strip()

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
                                     app_number: str, document_identifier: str) -> Dict[str, Any]:
        """
        Extract document content using Mistral OCR API

        Args:
            pdf_content: PDF content as bytes
            page_count: Number of pages in the document
            app_number: Patent application number
            document_identifier: Document identifier

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

            # Check OCR rate limit before proceeding
            self._check_ocr_rate_limit(request_id)

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

            client_kwargs = {"timeout": self.ocr_timeout}
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
                estimated_cost = pages_processed * 0.001  # $1 per 1000 pages

                # Combine all page content
                extracted_content = []
                for page in ocr_data.get("pages", []):
                    page_markdown = page.get("markdown", "")
                    if page_markdown.strip():
                        extracted_content.append(f"=== PAGE {page.get('index', 0) + 1} ===\n{page_markdown}")

                full_content = "\n\n".join(extracted_content)

                result = {
                    "success": True,
                    "application_number": app_number,
                    "document_identifier": document_identifier,
                    "page_count": page_count,
                    "pages_processed": pages_processed,
                    "extracted_content": full_content,
                    "structured_output": "markdown",
                    "processing_cost_usd": round(estimated_cost, 4),
                    "cost_breakdown": f"${estimated_cost:.4f} for {pages_processed} pages at $0.001/page",
                    "ocr_model": ocr_data.get("model", self.mistral_ocr_model),
                    "file_size_bytes": len(pdf_content),
                    "document_annotation": ocr_data.get("document_annotation", ""),
                    "usage_info": ocr_data.get("usage_info", {}),
                    "note": "Content extracted using Mistral OCR - supports scanned documents, formulas, and complex layouts"
                }
                # Surface silent truncation from the cost-control cap (audit F48)
                pages_truncated = max(0, page_count - self.ocr_max_pages)
                if pages_truncated > 0:
                    result["pages_truncated"] = pages_truncated
                    result["truncation_note"] = (
                        f"Only the first {self.ocr_max_pages} of {page_count} pages were "
                        f"OCR'd (cost-control cap; raise MISTRAL_OCR_MAX_PAGES to change)."
                    )
                return result

        except OCRRateLimitError as e:
            logger.warning(f"[{request_id}] OCR rate limit exceeded: {e.message}")
            return format_error_response(e.message, e.status_code, e.request_id)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return format_error_response("Mistral API authentication failed - check MISTRAL_API_KEY")
            elif e.response.status_code == 402:
                return format_error_response("Mistral API payment required - insufficient credits")
            else:
                return format_error_response(f"Mistral API error {e.response.status_code}: {e.response.text}")
        except Exception as e:
            return format_error_response(f"Failed to extract document content with Mistral OCR: {str(e)}")
