"""
Enhanced USPTO Patent File Wrapper API client

This client provides access to the USPTO Patent File Wrapper API for searching
applications, getting detailed application data, retrieving documents, and
downloading PDFs.
"""
import asyncio
import httpx
import logging
import json
import pathlib
import aiofiles
import os
import re
import random
import base64
import time
import hashlib
import xml.etree.ElementTree as ET
from enum import Enum
from typing import Dict, Any, List, Optional, Union, Tuple
from urllib.parse import quote
from .helpers import validate_app_number, format_error_response, generate_request_id, create_inventor_queries, map_user_fields_to_api_fields, escape_lucene_query_term, create_error_response
from ..exceptions import AuthenticationError, USPTOAPIError, TimeoutError, ValidationError, OCRRateLimitError, NotFoundError

try:
    import PyPDF2
    from io import BytesIO
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """
    Circuit breaker pattern implementation to prevent cascading failures
    when the USPTO API is down or experiencing issues.
    """

    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        """
        Initialize circuit breaker

        Args:
            failure_threshold: Number of failures before opening circuit
            timeout: Time in seconds before trying to close circuit again
        """
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = CircuitState.CLOSED

    def can_execute(self) -> bool:
        """Check if requests can be executed"""
        if self.state == CircuitState.CLOSED:
            return True
        elif self.state == CircuitState.OPEN:
            # Check if timeout has passed
            if time.time() - self.last_failure_time > self.timeout:
                self.state = CircuitState.HALF_OPEN
                logger.info("Circuit breaker transitioning to HALF_OPEN state")
                return True
            return False
        else:  # HALF_OPEN
            return True

    def record_success(self):
        """Record a successful operation"""
        if self.state == CircuitState.HALF_OPEN:
            logger.info("Circuit breaker transitioning to CLOSED state after successful request")
        self.failure_count = 0
        self.state = CircuitState.CLOSED

    def record_failure(self):
        """Record a failed operation"""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            if self.state != CircuitState.OPEN:
                logger.warning(f"Circuit breaker OPENING after {self.failure_count} failures")
            self.state = CircuitState.OPEN

    def is_open(self) -> bool:
        """Check if circuit is open"""
        return self.state == CircuitState.OPEN


class ResponseCache:
    """
    Cache successful API responses for fallback during outages.

    Provides resilience by serving cached data when the circuit breaker
    is open, improving user experience during API failures.
    """

    def __init__(self, ttl_seconds: int = 300, max_size: int = 100):
        """
        Initialize response cache

        Args:
            ttl_seconds: Time-to-live for cached responses (default: 5 minutes)
            max_size: Maximum number of cached responses (default: 100)
        """
        self.cache: Dict[str, Tuple[Dict[str, Any], float]] = {}
        self.ttl = ttl_seconds
        self.max_size = max_size
        logger.info(f"Response cache initialized: TTL={ttl_seconds}s, max_size={max_size}")

    def _make_key(self, endpoint: str, **kwargs) -> str:
        """
        Generate cache key from request parameters

        Args:
            endpoint: API endpoint path
            **kwargs: Request parameters

        Returns:
            SHA256 hash of endpoint and parameters (first 16 chars)
        """
        # Sort kwargs to ensure consistent key generation
        key_data = f"{endpoint}:{str(sorted(kwargs.items()))}"
        return hashlib.sha256(key_data.encode()).hexdigest()[:16]

    def get(self, endpoint: str, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Retrieve cached response if still valid

        Args:
            endpoint: API endpoint path
            **kwargs: Request parameters

        Returns:
            Cached response dict or None if not found/expired
        """
        key = self._make_key(endpoint, **kwargs)
        if key in self.cache:
            value, timestamp = self.cache[key]
            age = time.time() - timestamp

            if age < self.ttl:
                logger.info(f"Cache HIT for {endpoint} (age={age:.1f}s)")
                return value
            else:
                # Expired - remove from cache
                logger.debug(f"Cache entry expired for {endpoint} (age={age:.1f}s)")
                del self.cache[key]

        logger.debug(f"Cache MISS for {endpoint}")
        return None

    def set(self, endpoint: str, value: Dict[str, Any], **kwargs) -> None:
        """
        Cache successful response

        Args:
            endpoint: API endpoint path
            value: Response data to cache
            **kwargs: Request parameters
        """
        # Enforce max cache size - remove oldest entry if needed
        if len(self.cache) >= self.max_size:
            oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k][1])
            logger.debug(f"Cache full, removing oldest entry: {oldest_key}")
            del self.cache[oldest_key]

        key = self._make_key(endpoint, **kwargs)
        self.cache[key] = (value, time.time())
        logger.debug(f"Cached response for {endpoint} (cache size: {len(self.cache)}/{self.max_size})")

    def clear(self) -> None:
        """Clear all cached responses"""
        count = len(self.cache)
        self.cache.clear()
        logger.info(f"Response cache cleared ({count} entries removed)")

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "ttl_seconds": self.ttl,
            "entries": [
                {
                    "key": key,
                    "age_seconds": time.time() - timestamp
                }
                for key, (_, timestamp) in self.cache.items()
            ]
        }


class RetryBudget:
    """
    Track retry budget to prevent API quota exhaustion during persistent failures.

    Implements a sliding window counter to limit total retries per hour,
    preventing cascading failures and quota exhaustion.
    """

    def __init__(self, max_retries_per_hour: int = 100):
        """
        Initialize retry budget tracker.

        Args:
            max_retries_per_hour: Maximum retry attempts allowed per hour
        """
        self.max_retries = max_retries_per_hour
        self.retry_timestamps: List[float] = []
        logger.info(f"Retry budget initialized: max_retries_per_hour={max_retries_per_hour}")

    def can_retry(self) -> bool:
        """
        Check if we have retry budget available.

        Returns:
            True if retry is allowed, False if budget exhausted
        """
        now = time.time()

        # Remove retries older than 1 hour (sliding window)
        self.retry_timestamps = [ts for ts in self.retry_timestamps if now - ts < 3600]

        if len(self.retry_timestamps) >= self.max_retries:
            logger.warning(
                f"Retry budget exhausted: {len(self.retry_timestamps)}/{self.max_retries} "
                f"retries in last hour"
            )
            return False

        return True

    def record_retry(self) -> None:
        """Record a retry attempt in the budget."""
        self.retry_timestamps.append(time.time())
        logger.debug(
            f"Retry recorded: {len(self.retry_timestamps)}/{self.max_retries} "
            f"used in last hour"
        )

    def get_remaining_budget(self) -> int:
        """
        Get remaining retry budget.

        Returns:
            Number of retries remaining in current window
        """
        now = time.time()
        self.retry_timestamps = [ts for ts in self.retry_timestamps if now - ts < 3600]
        return max(0, self.max_retries - len(self.retry_timestamps))

    def get_stats(self) -> Dict[str, Any]:
        """
        Get retry budget statistics.

        Returns:
            Dictionary with budget usage statistics
        """
        now = time.time()
        self.retry_timestamps = [ts for ts in self.retry_timestamps if now - ts < 3600]

        return {
            "max_retries_per_hour": self.max_retries,
            "retries_used": len(self.retry_timestamps),
            "retries_remaining": self.max_retries - len(self.retry_timestamps),
            "utilization_percent": (len(self.retry_timestamps) / self.max_retries * 100) if self.max_retries > 0 else 0
        }


class EnhancedPatentClient:
    """Enhanced client for USPTO Patent File Wrapper API"""

    # Constants for better readability and maintainability
    DEFAULT_LIMIT = 10
    MAX_SEARCH_LIMIT = 1000
    MAX_CONCURRENT_REQUESTS = 10
    MAX_QUERY_LENGTH = 1000
    MAX_NAME_LENGTH = 200

    # Retry configuration
    RETRY_ATTEMPTS = 3
    RETRY_DELAY = 1.0  # Base delay in seconds
    RETRY_BACKOFF = 2  # Exponential backoff multiplier

    def __init__(self, api_key: Optional[str] = None):
        self.base_url = "https://api.uspto.gov/api/v1/patent/applications"

        # Load API key with unified secure storage support
        if api_key:
            self.api_key = api_key
        else:
            # Try to load from unified secure storage first, then fall back to environment
            try:
                from ..shared_secure_storage import get_uspto_api_key
                self.api_key = get_uspto_api_key()
            except Exception:
                # Fall back to environment variable if secure storage fails
                pass

            # If still no key, try environment variable
            if not self.api_key:
                self.api_key = os.getenv("USPTO_API_KEY")

            # Final validation
            if not self.api_key:
                raise AuthenticationError("USPTO_API_KEY is required. Set environment variable or use unified secure storage.")
        self.headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        # Configurable timeouts from environment variables (with fallbacks)
        self.default_timeout = float(os.getenv("USPTO_TIMEOUT", "30.0"))
        self.download_timeout = float(os.getenv("USPTO_DOWNLOAD_TIMEOUT", "60.0"))
        self.ocr_timeout = float(os.getenv("MISTRAL_OCR_TIMEOUT", "120.0"))
        logger.info(f"Timeout configuration: default={self.default_timeout}s, download={self.download_timeout}s, ocr={self.ocr_timeout}s")

        # Rate limiting to prevent DoS - limit concurrent requests
        self.semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_REQUESTS)

        # OCR rate limiting configuration
        self.ocr_calls = []  # List of timestamps for OCR calls
        self.ocr_rate_limit = 10  # Max OCR calls per minute
        self.ocr_window = 60  # Time window in seconds

        # Circuit breaker for API resilience
        self.circuit_breaker = CircuitBreaker(failure_threshold=3, timeout=30)

        # Response cache for resilience during circuit breaker open state
        self.response_cache = ResponseCache(ttl_seconds=300, max_size=100)

        # Separate connection pools for bulkhead pattern (resource isolation)
        self.api_limits = httpx.Limits(
            max_keepalive_connections=5,
            max_connections=10
        )
        self.download_limits = httpx.Limits(
            max_keepalive_connections=2,
            max_connections=5
        )
        self.ocr_limits = httpx.Limits(
            max_keepalive_connections=1,
            max_connections=3
        )
        logger.info("Connection pools configured: API=10, Download=5, OCR=3")

        # Retry budget for quota protection (prevent API quota exhaustion)
        max_retries_per_hour = int(os.getenv("USPTO_MAX_RETRIES_PER_HOUR", "100"))
        self.retry_budget = RetryBudget(max_retries_per_hour=max_retries_per_hour)

        # Mistral OCR configuration - check unified secure storage first, then environment
        raw_mistral_key = None
        try:
            from ..shared_secure_storage import get_mistral_api_key
            raw_mistral_key = get_mistral_api_key()
        except Exception:
            # Fall back to environment variable if secure storage fails
            pass

        # If still no key, try environment variable
        if not raw_mistral_key:
            raw_mistral_key = os.getenv("MISTRAL_API_KEY")

        self.mistral_api_key = self._validate_mistral_api_key(raw_mistral_key)
        self.mistral_base_url = "https://api.mistral.ai/v1"

    def _validate_mistral_api_key(self, raw_key: Optional[str]) -> Optional[str]:
        """
        Validate Mistral API key and detect common placeholder patterns.

        This prevents users from accidentally using placeholder text as a real API key,
        which would result in authentication errors instead of helpful guidance.

        Args:
            raw_key: Raw API key from environment variable

        Returns:
            Valid API key or None if invalid/placeholder
        """
        if not raw_key:
            return None

        # Common placeholder patterns that should be treated as missing
        placeholder_patterns = [
            "your_mistral_api_key_here",
            "your_key_here",
            "your_api_key_here",
            "placeholder",
            "optional",
            "change_me",
            "replace_me",
            "insert_key_here",
            "api_key_here"
        ]

        # Check if the key matches any placeholder pattern (case-insensitive)
        key_lower = raw_key.lower().strip()
        for pattern in placeholder_patterns:
            if pattern in key_lower:
                logger.info(f"Detected placeholder API key pattern: {pattern}. Treating as missing key.")
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

    async def _make_request(self, endpoint: str, method: str = "GET", **kwargs) -> Dict[str, Any]:
        """Make HTTP request to Patent File Wrapper API with rate limiting and retry logic"""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        request_id = generate_request_id()

        # Check circuit breaker first
        if not self.circuit_breaker.can_execute():
            logger.warning(f"[{request_id}] Request blocked by circuit breaker (state: {self.circuit_breaker.state.value})")

            # Try to serve from cache when circuit breaker is open
            cached = self.response_cache.get(endpoint, **kwargs)
            if cached:
                logger.info(f"[{request_id}] Serving cached response (circuit breaker open)")
                # Mark response as coming from cache
                cached_response = cached.copy()
                cached_response["_cache_hit"] = True
                cached_response["_cached_at"] = "Circuit breaker active - serving stale data"
                cached_response["_circuit_breaker_state"] = self.circuit_breaker.state.value
                return cached_response

            logger.warning(f"[{request_id}] No cached response available for failover")
            return format_error_response(
                "USPTO API is temporarily unavailable. No cached data available.",
                503,  # Service Unavailable
                request_id
            )

        logger.info(f"[{request_id}] Starting {method} request to {endpoint}")

        # Rate limiting: acquire semaphore before making request
        async with self.semaphore:
            last_exception = None

            for attempt in range(self.RETRY_ATTEMPTS):
                try:
                    async with httpx.AsyncClient(timeout=self.default_timeout, limits=self.api_limits, verify=True) as client:
                        if method.upper() == "POST":
                            response = await client.post(url, headers=self.headers, **kwargs)
                        else:
                            response = await client.get(url, headers=self.headers, **kwargs)

                        response.raise_for_status()
                        logger.info(f"[{request_id}] Request successful on attempt {attempt + 1}")

                        # Record success for circuit breaker
                        self.circuit_breaker.record_success()

                        # Cache successful response for resilience
                        response_data = response.json()
                        self.response_cache.set(endpoint, response_data, **kwargs)

                        return response_data

                except httpx.HTTPStatusError as e:
                    # Don't retry authentication errors or client errors (4xx)
                    if e.response.status_code < 500:
                        # Sanitize and truncate error response for logging
                        sanitized_text = e.response.text[:500] + "..." if len(e.response.text) > 500 else e.response.text
                        logger.error(f"[{request_id}] API error {e.response.status_code}: {sanitized_text}")
                        # DO NOT record 4xx as circuit breaker failures - they are valid client error responses
                        # Circuit breaker should only open for 5xx errors (server failures) and timeouts
                        # 4xx errors (404 Not Found, 400 Bad Request, etc.) are expected responses, not API failures
                        return format_error_response(f"API error: {e.response.text}", e.response.status_code, request_id)
                    last_exception = e

                except httpx.TimeoutException as e:
                    last_exception = e

                except Exception as e:
                    # Don't retry unexpected errors on final attempt
                    if attempt == self.RETRY_ATTEMPTS - 1:
                        logger.error(f"[{request_id}] Request failed: {str(e)}")
                        return format_error_response(f"Request failed: {str(e)}", 500, request_id)
                    last_exception = e

                # Calculate delay with exponential backoff and jitter
                if attempt < self.RETRY_ATTEMPTS - 1:
                    # Check retry budget before retrying
                    if not self.retry_budget.can_retry():
                        logger.error(
                            f"[{request_id}] Retry budget exhausted after attempt {attempt + 1}. "
                            f"Aborting further retries to prevent quota exhaustion."
                        )
                        # Break out of retry loop - budget exhausted
                        break

                    # Record this retry in the budget
                    self.retry_budget.record_retry()

                    delay = self.RETRY_DELAY * (self.RETRY_BACKOFF ** attempt)
                    # Add jitter to prevent thundering herd
                    jitter = random.uniform(0.1, 0.5)
                    total_delay = delay + jitter

                    logger.warning(f"[{request_id}] Request failed on attempt {attempt + 1}/{self.RETRY_ATTEMPTS}, "
                                 f"retrying in {total_delay:.2f}s: {str(last_exception)}")
                    await asyncio.sleep(total_delay)

            # All retries failed - record failure for circuit breaker
            self.circuit_breaker.record_failure()

            if isinstance(last_exception, httpx.TimeoutException):
                logger.error(f"[{request_id}] Request timeout after {self.RETRY_ATTEMPTS} attempts")
                return create_error_response("api_timeout", request_id=request_id)
            elif isinstance(last_exception, httpx.HTTPStatusError):
                logger.error(f"[{request_id}] API error {last_exception.response.status_code} after {self.RETRY_ATTEMPTS} attempts")
                if last_exception.response.status_code in [401, 403]:
                    return create_error_response("api_auth_failed", request_id=request_id, status_code=last_exception.response.status_code)
                else:
                    return format_error_response(f"API error: {last_exception.response.text}", last_exception.response.status_code, request_id)
            else:
                logger.error(f"[{request_id}] Request failed after {self.RETRY_ATTEMPTS} attempts: {str(last_exception)}")
                return format_error_response(f"Request failed: {str(last_exception)}", 500, request_id)

    async def search_applications(self, query: str, limit: int = 10, offset: int = 0, fields: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Search applications using Patent File Wrapper API with optional field filtering

        Args:
            query: Search query using Patent File Wrapper syntax
            limit: Maximum number of results
            offset: Starting position
            fields: Optional list of fields to retrieve for context reduction
        """
        try:
            # Always use POST for the search endpoint as per USPTO API spec
            body = {
                "q": query,
                "pagination": {
                    "limit": min(limit, 100),
                    "offset": offset
                },
                "sort": [
                    {
                        "field": "applicationMetaData.filingDate",
                        "order": "desc"
                    }
                ]
            }

            # Add fields array if specified, with mapping to API field names
            if fields:
                api_fields = map_user_fields_to_api_fields(fields)
                body["fields"] = api_fields
                logger.debug(f"Mapped user fields {fields} to API fields {api_fields}")

            result = await self._make_request("search", method="POST", json=body)

            if result.get('error'):
                return result

            # Extract applications from patentFileWrapperDataBag
            applications = result.get('patentFileWrapperDataBag', [])

            # Add application numbers at the top level for easier access
            for app in applications:
                if not app.get('applicationNumberText'):
                    # Try to extract from metadata
                    metadata = app.get('applicationMetaData', {})
                    app_number = None
                    # The app number might be in different places, try to find it
                    if 'applicationNumberText' in metadata:
                        app_number = metadata['applicationNumberText']
                    # Add it to the top level if found
                    if app_number:
                        app['applicationNumberText'] = app_number

            return {
                "success": True,
                "count": len(applications),
                "total": result.get('count', len(applications)),
                "query": query,
                "applications": applications,
                "limit": limit,
                "offset": offset,
                "request_id": result.get('requestIdentifier')
            }

        except Exception as e:
            return format_error_response(f"Application search failed: {str(e)}")

    async def search_inventor(self, name: str, strategy: str = "comprehensive", limit: int = 10, fields: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Enhanced inventor search using multiple strategies with optional field filtering

        Args:
            name: Inventor name to search for
            strategy: Search strategy - 'exact', 'fuzzy', or 'comprehensive'
            limit: Maximum number of results to return
            fields: Optional list of fields to retrieve for context reduction
        """
        try:
            queries = create_inventor_queries(name, strategy)
            all_results = []
            seen_apps = set()

            for query in queries:
                try:
                    result = await self.search_applications(query, min(limit, 50), 0, fields)

                    if not result.get('error') and result.get('applications'):
                        for app in result['applications']:
                            app_id = app.get('applicationNumberText')
                            if app_id and app_id not in seen_apps:
                                seen_apps.add(app_id)
                                all_results.append(app)

                            if len(all_results) >= limit:
                                break

                    if len(all_results) >= limit:
                        break

                except Exception as e:
                    logger.warning(f"Query '{query}' failed: {e}")
                    continue

            return {
                "success": True,
                "inventor_name": name,
                "strategy": strategy,
                "total_unique_applications": len(all_results),
                "unique_applications": all_results[:limit],
                "queries_used": queries[:5]  # Show first 5 queries used
            }

        except Exception as e:
            return format_error_response(f"Inventor search failed: {str(e)}")

    async def enhance_search_results_with_associated_docs(self, search_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enhance search results by adding associated documents metadata for each application

        Args:
            search_results: Results from search_applications or search_inventor

        Returns:
            Enhanced results with associated documents metadata
        """
        try:
            if not search_results.get("success") or not search_results.get("applications"):
                return search_results

            enhanced_applications = []

            for app in search_results["applications"]:
                # Get application number
                app_number = app.get("applicationNumberText")
                if not app_number:
                    # Try to get from metadata
                    app_number = app.get("applicationMetaData", {}).get("applicationNumberText")

                if app_number:
                    # Get associated documents for this application
                    assoc_docs_result = await self.get_associated_documents(app_number)

                    if assoc_docs_result.get("success"):
                        app["associatedDocuments"] = {
                            "count": assoc_docs_result.get("count", 0),
                            "documents": assoc_docs_result.get("associated_documents", []),
                            "xmlContentAvailable": assoc_docs_result.get("count", 0) > 0
                        }

                        # Add convenience flags for XML availability
                        docs = assoc_docs_result.get("associated_documents", [])
                        if docs:
                            for doc in docs:
                                if doc.get("grantDocumentMetaData"):
                                    app["associatedDocuments"]["ptgrXmlAvailable"] = True
                                if doc.get("pgpubDocumentMetaData"):
                                    app["associatedDocuments"]["appXmlAvailable"] = True
                    else:
                        app["associatedDocuments"] = {
                            "count": 0,
                            "documents": [],
                            "xmlContentAvailable": False,
                            "error": "Failed to retrieve associated documents"
                        }
                else:
                    app["associatedDocuments"] = {
                        "count": 0,
                        "documents": [],
                        "xmlContentAvailable": False,
                        "error": "No application number found"
                    }

                enhanced_applications.append(app)

            # Update the search results
            enhanced_results = search_results.copy()
            enhanced_results["applications"] = enhanced_applications
            enhanced_results["associatedDocumentsIncluded"] = True
            enhanced_results["llmGuidance"] = {
                "workflowPattern": {
                    "discovery": "Use pfw_search_applications_balanced for comprehensive discovery WITHOUT prosecution docs",
                    "quickPatentLookup": "Use pfw_search_applications_minimal for optimized patent-to-app mapping + XML metadata",
                    "xmlAnalysis": "Use pfw_get_patent_or_application_xml for structured content analysis",
                    "prosecutionDocs": "Use pfw_get_application_documents for targeted document access",
                    "pdfDownloads": "Use applicationNumberText + document_identifier with pfw_get_document_*",
                    "inventorAnalysis": "Use pfw_search_inventor_minimal for portfolio analysis with XML metadata"
                },
                "criticalApplicationCentricRules": {
                    "xmlAccess": "pfw_get_patent_or_application_xml requires applicationNumberText (now via minimal search)",
                    "documentAccess": "pfw_get_application_documents requires applicationNumberText for prosecution docs",
                    "documentDownload": "pfw_get_document requires applicationNumberText + document_identifier from pfw_get_application_documents",
                    "ocrExtraction": "pfw_get_document_content requires applicationNumberText + document_identifier from pfw_get_application_documents",
                    "proxyDownload": "pfw_get_document_download requires applicationNumberText + document_identifier from pfw_get_application_documents",
                    "patentNumbers": "Patent numbers mapped to applicationNumberText via enhanced minimal search (single call)"
                },
                "optimizedWorkflowSequence": {
                    "discovery_workflow": [
                        "1. Use balanced search for discovery (20-50 applications)",
                        "2. Review results and select applications of interest",
                        "3. Use XML tool for content analysis",
                        "4. Use document tool only if prosecution docs needed"
                    ],
                    "patent_analysis_workflow": [
                        "1. Patent number → Minimal search → applicationNumberText + XML metadata",
                        "2. Use pfw_get_patent_or_application_xml for structured analysis",
                        "3. Use pfw_get_application_documents if prosecution history needed"
                    ]
                },
                "session_4_optimization": {
                    "problem_solved": "Token explosion from documentBag in discovery searches",
                    "solution": "Dedicated document tool for targeted prosecution access",
                    "efficiency_gain": "20-50x more applications can fit in discovery context",
                    "workflow_clarity": "Clear separation: discovery → analysis → documents"
                },
                "tool_selection_guidance": {
                    "for_discovery": "Use balanced search - comprehensive metadata without document noise",
                    "for_content": "Use XML tool - structured patent content for AI analysis",
                    "for_documents": "Use document tool - prosecution history when legal workflow needed"
                },
                "dataLimitation": "XML content only available for patents/applications filed after January 1, 2001"
            }

            return enhanced_results

        except Exception as e:
            logger.error(f"Failed to enhance search results with associated docs: {str(e)}")
            # Return original results if enhancement fails
            search_results["associatedDocumentsError"] = str(e)
            return search_results

    async def enhance_search_results_with_document_bags(self, search_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enhance search results by adding document bag metadata for each application

        Args:
            search_results: Results from search_applications or search_inventor

        Returns:
            Enhanced results with document bag metadata
        """
        try:
            if not search_results.get("success") or not search_results.get("applications"):
                return search_results

            enhanced_applications = []

            for app in search_results["applications"]:
                # Get application number
                app_number = app.get("applicationNumberText")
                if not app_number:
                    # Try to get from metadata
                    app_number = app.get("applicationMetaData", {}).get("applicationNumberText")

                if app_number:
                    # Get document bag for this application
                    doc_bag_result = await self.get_document_bag(app_number)

                    if doc_bag_result.get("success"):
                        app["documentBag"] = doc_bag_result.get("documentBag", [])
                        app["documentSummary"] = doc_bag_result.get("summary", {})
                    else:
                        app["documentBag"] = []
                        app["documentSummary"] = {}
                        app["documentBagError"] = doc_bag_result.get("message", "Failed to retrieve document bag")
                else:
                    app["documentBag"] = []
                    app["documentSummary"] = {}
                    app["documentBagError"] = "No application number found"

                enhanced_applications.append(app)

            # Update the search results
            enhanced_results = search_results.copy()
            enhanced_results["applications"] = enhanced_applications
            enhanced_results["documentBagsIncluded"] = True
            enhanced_results["prosecutionDocsGuidance"] = {
                "applicationCentricWorkflow": "ALL document downloads require applicationNumberText + document_identifier",
                "noSinglePatentPDF": "USPTO provides individual prosecution documents, not complete patent PDFs",
                "keyDocumentTypes": {
                    "ABST": "Abstract (1 page) - perfect for quick review",
                    "CLM": "Claims - key for understanding scope",
                    "SPEC": "Specification - full technical description (often 20+ pages)",
                    "NOA": "Notice of Allowance - examiner's reasoning for approval",
                    "CTFR/CTNF": "Rejections - examination history and objections",
                    "DRW": "Drawings - technical diagrams"
                },
                "downloadWorkflow": [
                    "1. Use documentBag to get document_identifier for desired documents",
                    "2. Use pfw_get_document_download for browser-accessible URLs",
                    "3. Use pfw_get_document for basic extraction + metadata",
                    "4. Use pfw_get_document_content for advanced OCR (Mistral API required)"
                ],
                "expectationManagement": {
                    "whenUserSays": "Download the patent PDF",
                    "reality": "Must download separate PDFs: Abstract (1p), Final Claims (8p), Specification (21p), Drawings (2p)",
                    "alternative": "For AI analysis, use pfw_get_patent_or_application_xml for complete structured content"
                }
            }

            return enhanced_results

        except Exception as e:
            logger.error(f"Failed to enhance search results with document bags: {str(e)}")
            # Return original results if enhancement fails
            search_results["documentBagError"] = str(e)
            return search_results

    async def get_application_data(self, app_number: str) -> Dict[str, Any]:
        """
        Get complete application data including metadata

        Args:
            app_number: Patent application number
        """
        try:
            app_number = validate_app_number(app_number)

            # Get application data
            result = await self._make_request(app_number)

            if result.get('error'):
                return result

            # Extract the first (and should be only) application from the response
            applications = result.get('patentFileWrapperDataBag', [])
            if not applications:
                return format_error_response(f"No data found for application {app_number}")

            app_data = applications[0]

            # Also get documents summary
            docs_result = await self.get_documents(app_number)

            return {
                "success": True,
                "application_number": app_number,
                "application_data": app_data,
                "documents_summary": docs_result.get('summary', {}) if not docs_result.get('error') else None,
                "request_id": result.get('requestIdentifier')
            }

        except Exception as e:
            return format_error_response(f"Failed to get application data: {str(e)}")

    async def get_document_bag(self, app_number: str) -> Dict[str, Any]:
        """
        Get document bag for an application (prosecution documents with download links)

        Args:
            app_number: Patent application number

        Returns:
            Dict containing prosecution documents with download identifiers
        """
        try:
            app_number = validate_app_number(app_number)

            # Use the documents endpoint (this was working before)
            result = await self.get_documents(app_number)

            if result.get('error'):
                return result

            return {
                "success": True,
                "application_number": app_number,
                "count": result.get('count', 0),
                "documentBag": result.get('documentBag', []),
                "summary": result.get('summary', {}),
                "request_id": result.get('request_id')
            }

        except Exception as e:
            return format_error_response(f"Failed to get document bag: {str(e)}")

    async def get_associated_documents(self, app_number: str) -> Dict[str, Any]:
        """
        Get associated documents metadata for an application (XML files)

        Args:
            app_number: Patent application number

        Returns:
            Dict containing APPXML and PTGRXML metadata with file locations
        """
        try:
            app_number = validate_app_number(app_number)

            # Use the associated-documents endpoint
            endpoint = f"{app_number}/associated-documents"
            result = await self._make_request(endpoint)

            if result.get('error'):
                return result

            return {
                "success": True,
                "application_number": app_number,
                "count": result.get('count', 0),
                "associated_documents": result.get('patentFileWrapperDataBag', []),
                "request_id": result.get('requestIdentifier')
            }

        except Exception as e:
            return format_error_response(f"Failed to get associated documents: {str(e)}")

    async def get_documents(
        self,
        app_number: str,
        limit: Optional[int] = None,
        document_code: Optional[str] = None,
        direction_category: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get documents list for an application with optional filtering

        Args:
            app_number: Patent application number
            limit: Maximum number of documents to return (applied AFTER filtering)
            document_code: Filter by specific document code (e.g., 'NOA', 'FWCLM', 'CTFR')
                          Case-insensitive exact match
            direction_category: Filter by document direction: 'INCOMING', 'OUTGOING', or 'INTERNAL'
                               Case-insensitive exact match
        """
        try:
            app_number = validate_app_number(app_number)

            # Fetch ALL documents from USPTO API (no server-side filtering available)
            result = await self._make_request(f"{app_number}/documents")

            if result.get('error'):
                return result

            documents = result.get('documentBag', [])

            # Track filtering for summary
            filtering_applied = []
            original_count = len(documents)

            # Apply document_code filter (client-side)
            if document_code:
                filtered_docs = [
                    doc for doc in documents
                    if doc.get('documentCode', '').upper() == document_code.upper()
                ]
                documents = filtered_docs
                filtering_applied.append(f"document_code='{document_code}'")

            # Apply direction_category filter (client-side)
            if direction_category:
                filtered_docs = [
                    doc for doc in documents
                    if doc.get('directionCategory', '').upper() == direction_category.upper()
                ]
                documents = filtered_docs
                filtering_applied.append(f"direction_category='{direction_category}'")

            # Apply limit AFTER filtering
            if limit and len(documents) > limit:
                documents = documents[:limit]
                filtering_applied.append(f"limit={limit}")

            # Create summary
            doc_types = {}
            download_options = 0
            pdf_docs = []

            for doc in documents:
                doc_code = doc.get('documentCode', 'Unknown')
                doc_types[doc_code] = doc_types.get(doc_code, 0) + 1

                # Count download options and track PDF availability
                for option in doc.get('downloadOptionBag', []):
                    download_options += 1
                    if option.get('mimeTypeIdentifier') == 'PDF':
                        pdf_docs.append({
                            'document_code': doc_code,
                            'document_description': doc.get('documentCodeDescriptionText', ''),
                            'official_date': doc.get('officialDate', ''),
                            'document_identifier': doc.get('documentIdentifier', ''),
                            'page_count': option.get('pageTotalQuantity', 0),
                            'download_url': option.get('downloadUrl', '')
                        })

            # Build filtering summary message
            filter_summary = None
            if filtering_applied:
                filter_summary = {
                    "filters_applied": filtering_applied,
                    "original_document_count": original_count,
                    "filtered_document_count": len(documents),
                    "reduction_percentage": round((1 - len(documents)/original_count) * 100, 1) if original_count > 0 else 0
                }

            return {
                "success": True,
                "application_number": app_number,
                "count": len(documents),
                "documentBag": documents,
                "summary": {
                    "total_documents": len(documents),
                    "document_types": doc_types,
                    "total_download_options": download_options,
                    "pdf_documents_count": len(pdf_docs),
                    "key_documents": [doc for doc in pdf_docs if doc['document_code'] in ['SPEC', 'CLM', 'DRW', 'ABST', 'NOA']],
                    "filtering": filter_summary  # NEW: Filtering summary
                }
            }

        except Exception as e:
            return format_error_response(f"Failed to get documents: {str(e)}")

    async def download_application_pdf(self, app_number: str, download_dir: str = "/tmp") -> Dict[str, Any]:
        """
        Download key PDF documents for an application

        Args:
            app_number: Patent application number
            download_dir: Directory to save files
        """
        try:
            app_number = validate_app_number(app_number)

            # Get documents first
            docs_result = await self.get_documents(app_number)

            if docs_result.get('error'):
                return docs_result

            documents = docs_result.get('documentBag', [])

            # Get invention title and patent number for better filenames
            invention_title = None
            patent_number = None
            try:
                # Search for the application to get the title and patent number info
                search_result = await self.search_applications(
                    f"applicationNumberText:{app_number}",
                    limit=1,
                    offset=0,
                    fields=["applicationMetaData.inventionTitle", "applicationMetaData.patentNumber"]
                )
                if search_result.get('success'):
                    apps = search_result.get('patentFileWrapperDataBag') or search_result.get('applications')
                    if apps:
                        app_data = apps[0]
                        invention_title = app_data.get('applicationMetaData', {}).get('inventionTitle')
                        # Extract patent number using helper function
                        from .helpers import extract_patent_number
                        patent_number = extract_patent_number(app_data)
            except Exception as e:
                logger.warning(f"Could not fetch application metadata for {app_number}: {e}")

            # Priority document types to download
            priority_types = ['SPEC', 'CLM', 'ABST', 'DRW', 'NOA', 'CTFR', 'CTNF']

            downloaded_files = []

            for doc in documents:
                doc_code = doc.get('documentCode', '')

                if doc_code in priority_types:
                    download_options = doc.get('downloadOptionBag', [])

                    for option in download_options:
                        if option.get('mimeTypeIdentifier') == 'PDF':
                            try:
                                result = await self._download_document_from_url(
                                    app_number, doc, option, download_dir, invention_title, patent_number
                                )
                                if result.get('success'):
                                    downloaded_files.append(result)
                                    break  # Download first available PDF option
                            except Exception as e:
                                logger.warning(f"Failed to download {doc_code}: {e}")
                                continue

            return {
                "success": True,
                "application_number": app_number,
                "download_directory": download_dir,
                "downloaded_files": downloaded_files,
                "total_downloaded": len(downloaded_files)
            }

        except Exception as e:
            return format_error_response(f"Failed to download PDFs: {str(e)}")

    async def download_document_pdf(self, app_number: str, document_code: str, download_dir: str = "/tmp") -> Dict[str, Any]:
        """
        Download a specific document PDF

        Args:
            app_number: Patent application number
            document_code: Document code to download
            download_dir: Directory to save file
        """
        try:
            app_number = validate_app_number(app_number)

            # Get documents
            docs_result = await self.get_documents(app_number)

            if docs_result.get('error'):
                return docs_result

            documents = docs_result.get('documentBag', [])

            # Find the specific document
            target_doc = None
            for doc in documents:
                if doc.get('documentCode', '').upper() == document_code.upper():
                    target_doc = doc
                    break

            if not target_doc:
                raise NotFoundError(
                    f"Document code '{document_code}' not found in application {app_number}",
                    request_id=request_id
                )

            # Find PDF download option
            download_options = target_doc.get('downloadOptionBag', [])
            pdf_option = None

            for option in download_options:
                if option.get('mimeTypeIdentifier') == 'PDF':
                    pdf_option = option
                    break

            if not pdf_option:
                return format_error_response(f"PDF not available for document '{document_code}'")

            # Get invention title and patent number for better filename
            invention_title = None
            patent_number = None
            try:
                # Search for the application to get the title and patent number info
                search_result = await self.search_applications(
                    f"applicationNumberText:{app_number}",
                    limit=1,
                    offset=0,
                    fields=["applicationMetaData.inventionTitle", "applicationMetaData.patentNumber"]
                )
                if search_result.get('success'):
                    apps = search_result.get('patentFileWrapperDataBag') or search_result.get('applications')
                    if apps:
                        app_data = apps[0]
                        invention_title = app_data.get('applicationMetaData', {}).get('inventionTitle')
                        # Extract patent number using helper function
                        from .helpers import extract_patent_number
                        patent_number = extract_patent_number(app_data)
            except Exception as e:
                logger.warning(f"Could not fetch application metadata for {app_number}: {e}")

            # Download the document
            result = await self._download_document_from_url(app_number, target_doc, pdf_option, download_dir, invention_title, patent_number)

            return result

        except NotFoundError as e:
            return create_error_response(
                "document_not_found",
                custom_message=e.message,
                status_code=404,
                request_id=e.request_id
            )
        except ValidationError as e:
            return format_error_response(e.message, e.status_code, e.request_id)
        except Exception as e:
            logger.exception(f"Failed to download document: {e}")
            return format_error_response(f"Failed to download document: {str(e)}")

    async def _download_document_from_url(self, app_number: str, document: Dict, download_option: Dict, download_dir: str, invention_title: str = None, patent_number: str = None) -> Dict[str, Any]:
        """Download a single document from its URL"""
        try:
            from .helpers import generate_safe_filename

            doc_code = document.get('documentCode', 'Unknown')
            doc_date = document.get('officialDate', 'NoDate')[:10]  # Just the date part
            doc_identifier = document.get('documentIdentifier', 'Unknown')

            # Construct filename using invention title and patent number if available
            if invention_title:
                filename = generate_safe_filename(app_number, invention_title, doc_code, patent_number)
            else:
                # Fallback to old format if no title available
                filename = f"{app_number}_{doc_code}_{doc_date}_{doc_identifier}.pdf"
                # Clean filename
                filename = re.sub(r'[<>:"/\\|?*]', '_', filename)

            filepath = os.path.join(download_dir, filename)

            # Get download URL
            download_url = download_option.get('downloadUrl')

            if not download_url:
                return format_error_response("Download URL not available")

            # Download the file, following redirects
            async with httpx.AsyncClient(timeout=self.download_timeout, limits=self.download_limits, follow_redirects=True) as client:
                response = await client.get(download_url, headers=self.headers)
                response.raise_for_status()

                # Ensure directory exists
                os.makedirs(download_dir, exist_ok=True)

                # Save file
                async with aiofiles.open(filepath, 'wb') as f:
                    await f.write(response.content)

                return {
                    "success": True,
                    "filename": filename,
                    "filepath": filepath,
                    "file_size": len(response.content),
                    "document_code": doc_code,
                    "document_description": document.get('documentCodeDescriptionText', ''),
                    "official_date": document.get('officialDate', ''),
                    "page_count": download_option.get('pageTotalQuantity', 0),
                    "application_number": app_number,
                    "download_url": download_url
                }

        except Exception as e:
            return format_error_response(f"Download failed: {str(e)}")

    async def download_document_content(self, app_number: str, document_identifier: str) -> Dict[str, Any]:
        """
        Download and extract content from a specific USPTO document

        Args:
            app_number: Patent application number
            document_identifier: Document identifier from documentBag

        Returns:
            Dictionary containing extracted text, base64 PDF data, and metadata
        """
        try:
            app_number = validate_app_number(app_number)

            # First get documents to find the specific document
            docs_result = await self.get_documents(app_number)
            if docs_result.get('error'):
                return docs_result

            documents = docs_result.get('documentBag', [])

            # Find the target document
            target_doc = None
            for doc in documents:
                if doc.get('documentIdentifier') == document_identifier:
                    target_doc = doc
                    break

            if not target_doc:
                raise NotFoundError(
                    f"Document with identifier '{document_identifier}' not found in application {app_number}",
                    request_id=request_id
                )

            # Find PDF download option
            download_options = target_doc.get('downloadOptionBag', [])
            pdf_option = None

            for option in download_options:
                if option.get('mimeTypeIdentifier') == 'PDF':
                    pdf_option = option
                    break

            if not pdf_option:
                return format_error_response("PDF not available for this document")

            download_url = pdf_option.get('downloadUrl')
            if not download_url:
                return format_error_response("Download URL not available")

            page_count = pdf_option.get('pageTotalQuantity', 0)

            # Check page count and warn for large documents
            if page_count > 25:
                logger.warning(f"Large document warning: {page_count} pages for document {document_identifier}")

            # Download the PDF with authentication, following redirects
            async with httpx.AsyncClient(timeout=self.download_timeout, limits=self.download_limits, follow_redirects=True) as client:
                response = await client.get(download_url, headers=self.headers)
                response.raise_for_status()

                pdf_content = response.content

                # Extract text using PyPDF2 if available
                extracted_text = ""
                if PDF_AVAILABLE:
                    try:
                        pdf_reader = PyPDF2.PdfReader(BytesIO(pdf_content))
                        text_parts = []

                        for page_num, page in enumerate(pdf_reader.pages):
                            try:
                                page_text = page.extract_text()
                                if page_text.strip():
                                    text_parts.append(f"=== PAGE {page_num + 1} ===\n{page_text}")
                            except Exception as e:
                                logger.warning(f"Failed to extract text from page {page_num + 1}: {e}")
                                text_parts.append(f"=== PAGE {page_num + 1} ===\n[Text extraction failed]")

                        extracted_text = "\n\n".join(text_parts)

                    except Exception as e:
                        logger.warning(f"PDF text extraction failed: {e}")
                        extracted_text = "[PDF text extraction failed - document may contain only images or be corrupted]"
                else:
                    extracted_text = "[PyPDF2 not available - install with: pip install PyPDF2]"

                # Create an obfuscated download link that hides the API key
                # Include the redirect URL from the response if available
                final_download_url = str(response.url) if hasattr(response, 'url') else download_url

                # Create a clean download link without exposing the API key
                obfuscated_link = final_download_url
                if 'redirect_request_id=' in obfuscated_link:
                    # Remove any sensitive parameters but keep the redirect functionality
                    base_url = obfuscated_link.split('?')[0]
                    obfuscated_link = f"{base_url}?source=mcp-tool"

                return {
                    "success": True,
                    "application_number": app_number,
                    "document_identifier": document_identifier,
                    "document_code": target_doc.get('documentCode', ''),
                    "document_description": target_doc.get('documentCodeDescriptionText', ''),
                    "official_date": target_doc.get('officialDate', ''),
                    "page_count": page_count,
                    "large_document_warning": page_count > 25,
                    "extracted_text": extracted_text,
                    "file_size_bytes": len(pdf_content),
                    "download_url_for_llm": obfuscated_link,
                    "download_instructions": "Use web tools to fetch this URL for PDF analysis, or provide to user for manual download",
                    "text_extraction_available": PDF_AVAILABLE,
                    "note": "PDF content available via download_url_for_llm - text extracted above for immediate analysis"
                }

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                return format_error_response("Authentication failed - check USPTO_API_KEY")
            else:
                return format_error_response(f"HTTP error {e.response.status_code}: {e.response.text}")
        except Exception as e:
            return format_error_response(f"Failed to download document content: {str(e)}")

    async def extract_document_content_with_mistral(self, app_number: str, document_identifier: str) -> Dict[str, Any]:
        """
        Extract document content using Mistral OCR API

        Args:
            app_number: Patent application number
            document_identifier: Document identifier from documentBag

        Returns:
            Dictionary containing OCR-extracted content, structured data, and processing metadata
        """
        try:
            # Check if Mistral API key is available
            if not self.mistral_api_key:
                return format_error_response(
                    "MISTRAL_API_KEY environment variable is required for OCR content extraction. "
                    "Set it with: set MISTRAL_API_KEY=your_key_here (Windows) or export MISTRAL_API_KEY=your_key_here (Linux/Mac)"
                )

            app_number = validate_app_number(app_number)
            request_id = generate_request_id()

            # Check OCR rate limit before proceeding
            self._check_ocr_rate_limit(request_id)

            # First download the PDF (reuse existing logic)
            download_result = await self.download_document_content(app_number, document_identifier)
            if download_result.get('error'):
                return download_result

            # Get the PDF content by re-downloading with our internal method
            docs_result = await self.get_documents(app_number)
            if docs_result.get('error'):
                return docs_result

            documents = docs_result.get('documentBag', [])
            target_doc = None
            for doc in documents:
                if doc.get('documentIdentifier') == document_identifier:
                    target_doc = doc
                    break

            if not target_doc:
                raise NotFoundError(
                    f"Document with identifier '{document_identifier}' not found in application {app_number}",
                    request_id=request_id
                )

            # Find PDF download option
            download_options = target_doc.get('downloadOptionBag', [])
            pdf_option = None
            for option in download_options:
                if option.get('mimeTypeIdentifier') == 'PDF':
                    pdf_option = option
                    break

            if not pdf_option:
                return format_error_response("PDF not available for this document")

            download_url = pdf_option.get('downloadUrl')
            page_count = pdf_option.get('pageTotalQuantity', 0)

            # Download PDF content for Mistral processing
            async with httpx.AsyncClient(timeout=self.download_timeout, limits=self.download_limits, follow_redirects=True) as client:
                response = await client.get(download_url, headers=self.headers)
                response.raise_for_status()
                pdf_content = response.content

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

            async with httpx.AsyncClient(timeout=self.ocr_timeout, limits=self.ocr_limits) as client:
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
                    "model": "mistral-ocr-latest",
                    "document": {
                        "type": "file",
                        "file_id": file_id
                    },
                    "pages": list(range(min(page_count, 50))),  # Limit to first 50 pages for cost control
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

                return {
                    "success": True,
                    "application_number": app_number,
                    "document_identifier": document_identifier,
                    "document_code": target_doc.get('documentCode', ''),
                    "document_description": target_doc.get('documentCodeDescriptionText', ''),
                    "official_date": target_doc.get('officialDate', ''),
                    "page_count": page_count,
                    "pages_processed": pages_processed,
                    "extracted_content": full_content,
                    "structured_output": "markdown",
                    "processing_cost_usd": round(estimated_cost, 4),
                    "cost_breakdown": f"${estimated_cost:.4f} for {pages_processed} pages at $0.001/page",
                    "ocr_model": "mistral-ocr-latest",
                    "file_size_bytes": len(pdf_content),
                    "document_annotation": ocr_data.get("document_annotation", ""),
                    "usage_info": ocr_data.get("usage_info", {}),
                    "note": "Content extracted using Mistral OCR - supports scanned documents, formulas, and complex layouts"
                }

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

    async def find_application_for_patent(self, patent_number: str) -> tuple[str, dict]:
        """
        Find the application number that led to a granted patent using direct API calls.

        Args:
            patent_number: Patent number (e.g., '7971071')

        Returns:
            Tuple of (application_number, associated_documents)
        """
        try:
            # Use direct API search to avoid circular imports
            queries = [
                f"applicationMetaData.patentNumber:{patent_number}",
                f"parentPatentNumber:{patent_number}",
                f"applicationMetaData.applicationStatusCode:Patent"
            ]

            for i, query in enumerate(queries):
                limit = 10 if i < 2 else 100  # Use higher limit for broader search

                # Direct API call using the same pattern as search_applications
                body = {
                    "q": query,
                    "pagination": {
                        "limit": limit,
                        "offset": 0
                    },
                    "fields": [
                        "applicationNumberText",
                        "applicationMetaData.patentNumber",
                        "parentPatentNumber",
                        "parentContinuityBag",
                        "associatedDocuments"  # Try to get this directly
                    ]
                }

                result = await self._make_request("search", method="POST", json=body)

                if result.get('error'):
                    continue

                applications = result.get('patentFileWrapperDataBag', [])

                if i < 2:  # Direct searches
                    if applications:
                        app = applications[0]
                        return app["applicationNumberText"], app.get("associatedDocuments")
                else:  # Broader search - need to scan
                    for app in applications:
                        app_meta = app.get("applicationMetaData", {})
                        if (app_meta.get("patentNumber") == patent_number or
                            any(parent.get("parentPatentNumber") == patent_number
                                for parent in app.get("parentContinuityBag", []))):
                            return app["applicationNumberText"], app.get("associatedDocuments")

            raise ValueError(f"No application found for patent {patent_number}")

        except Exception as e:
            raise ValueError(f"Failed to find application for patent {patent_number}: {str(e)}")

    def detect_content_type(self, identifier: str) -> str:
        """
        Auto-detect patent vs application based on identifier format.

        Uses the comprehensive identifier normalization logic that handles:
        - Patent kind codes (B2, A1, etc.)
        - 8M threshold for ambiguous 8-digit numbers
        - Publication numbers

        Rules:
        - Patent numbers: Usually 7 digits (e.g., 7971071) or with suffixes (US7971071B2)
        - Application numbers: Usually 8+ digits >= 8M (e.g., 11752072, 16/123456)
        """
        from ..util.identifier_normalization import normalize_identifier

        # Use the comprehensive identifier normalization
        identifier_info = normalize_identifier(identifier)

        # Map identifier types to content types
        if identifier_info.identifier_type == "patent":
            return "patent"
        elif identifier_info.identifier_type in ["application", "publication"]:
            return "application"
        else:
            # Unknown type - use old simple heuristic as fallback
            clean_id = identifier.replace("/", "").replace("-", "").replace(",", "")
            if len(clean_id) <= 7 and clean_id.isdigit():
                return "patent"
            else:
                return "application"

    def extract_xml_url(self, associated_docs: dict, target_xml: str) -> str:
        """
        Extract the correct XML URL from Associated Documents.

        Args:
            associated_docs: Associated documents data from API
            target_xml: "PTGRXML" for granted patents, "APPXML" for applications
        """
        if not associated_docs or not associated_docs.get("documents"):
            raise ValueError("No associated documents available")

        documents = associated_docs["documents"]
        if not documents:
            raise ValueError("No documents found in associated documents")

        doc = documents[0]  # Usually only one document entry

        if target_xml == "PTGRXML":
            if "grantDocumentMetaData" in doc and associated_docs.get("ptgrXmlAvailable"):
                return doc["grantDocumentMetaData"]["fileLocationURI"]
            else:
                raise ValueError("No granted patent XML available - application may not be granted")

        elif target_xml == "APPXML":
            if "pgpubDocumentMetaData" in doc and associated_docs.get("appXmlAvailable"):
                return doc["pgpubDocumentMetaData"]["fileLocationURI"]
            else:
                raise ValueError("No application XML available")

        raise ValueError(f"Unknown XML type: {target_xml}")

    async def fetch_xml_from_url(self, xml_url: str) -> str:
        """
        Fetch XML content from the provided URL.

        Args:
            xml_url: URL to fetch XML from

        Returns:
            Raw XML content as string
        """
        try:
            async with httpx.AsyncClient(timeout=self.download_timeout, limits=self.download_limits, follow_redirects=True) as client:
                response = await client.get(xml_url, headers=self.headers)
                response.raise_for_status()
                return response.text
        except Exception as e:
            raise ValueError(f"Failed to fetch XML from URL {xml_url}: {str(e)}")

    def parse_xml_for_llm(
        self,
        xml_content: str,
        include_fields: Optional[List[str]] = None
    ) -> dict:
        """
        Parse USPTO XML into LLM-friendly structured format.

        Optimized for context efficiency - only extracts requested fields.

        Args:
            xml_content: Raw XML string
            include_fields: Optional list of fields to include
                          Default: ["abstract", "claims", "description"]
                          Available: "abstract", "claims", "description", "inventors",
                                    "applicants", "classifications", "citations", "publication_info"

        Note: Metadata fields (inventors, applicants, classifications) are also available
        via search_balanced. For citation analysis, use uspto_enriched_citation_mcp for
        richer citation data.
        """
        try:
            root = ET.fromstring(xml_content)

            # Determine XML type (PTGRXML vs APPXML)
            is_patent = root.tag in ['us-patent-grant', 'patent-grant']

            # Default to core content fields if not specified
            if include_fields is None:
                include_fields = ["abstract", "claims", "description"]

            # Start with xml_type (always included)
            structured = {
                "xml_type": "patent" if is_patent else "application"
            }

            # Conditionally add requested fields
            if "abstract" in include_fields:
                structured["abstract"] = self._extract_abstract(root)

            if "claims" in include_fields:
                structured["claims"] = self._extract_claims(root)

            if "description" in include_fields:
                structured["description"] = self._extract_description(root)

            if "inventors" in include_fields:
                structured["inventors"] = self._extract_inventors(root)

            if "applicants" in include_fields:
                structured["applicants"] = self._extract_applicants(root)

            if "classifications" in include_fields:
                structured["classifications"] = self._extract_classifications(root)

            if "citations" in include_fields:
                structured["citations"] = self._extract_citations(root)

            if "publication_info" in include_fields:
                structured["publication_info"] = self._extract_publication_info(root)

            return structured

        except Exception as e:
            return {
                "error": f"XML parsing failed: {str(e)}",
                "raw_available": True
            }

    def _build_fields_metadata(
        self,
        include_fields: Optional[List[str]],
        structured_content: dict
    ) -> dict:
        """
        Build minimal metadata about which fields were included in the response.

        Args:
            include_fields: The include_fields parameter passed by user (or None for default)
            structured_content: The structured content dict that was built

        Returns:
            Minimal metadata dict for field discoverability
        """
        # All available fields
        all_fields = [
            "abstract", "claims", "description",
            "inventors", "applicants", "classifications",
            "citations", "publication_info"
        ]

        # Fields actually included (from structured_content, excluding xml_type and error)
        fields_included = [
            k for k in structured_content.keys()
            if k not in ["xml_type", "error", "raw_available"]
        ]

        metadata = {
            "fields_included": fields_included,
            "fields_available": all_fields,
            "using_default": include_fields is None
        }

        # Add simple hint if using defaults (for LLM discoverability)
        if include_fields is None:
            metadata["note"] = "Using default fields. Add include_fields=['inventors', 'applicants'] for entity info. RECOMMENDED: Set include_raw_xml=False to remove ~50K token raw XML overhead. See pfw_get_guidance(section='tools') for all options"
        else:
            metadata["note"] = f"Custom fields selected. RECOMMENDED: Set include_raw_xml=False to remove ~50K token raw XML overhead unless needed for debugging."

        return metadata

    def _extract_abstract(self, root) -> str:
        """Extract abstract text from XML"""
        abstract_elem = root.find('.//abstract')
        if abstract_elem is not None:
            return ' '.join(abstract_elem.itertext()).strip()
        return "Abstract not found"

    def _extract_claims(self, root) -> list:
        """Extract all claims from XML"""
        claims = []
        for claim in root.findall('.//claim'):
            claim_num = claim.get('num', 'Unknown')
            claim_text = ' '.join(claim.itertext()).strip()
            claims.append({
                "number": claim_num,
                "text": claim_text,
                "type": "independent" if "comprising:" in claim_text or "wherein:" in claim_text else "dependent"
            })
        return claims

    def _extract_description(self, root) -> str:
        """Extract description/specification text"""
        desc_elem = root.find('.//description')
        if desc_elem is not None:
            # Get first few paragraphs for summary
            paragraphs = desc_elem.findall('.//p')[:5]  # Limit for LLM context
            return '\n\n'.join([' '.join(p.itertext()).strip() for p in paragraphs])
        return "Description not found"

    def _extract_inventors(self, root) -> list:
        """Extract inventor information"""
        inventors = []

        # Try standard inventor elements first
        for inventor in root.findall('.//inventor'):
            name_elem = inventor.find('.//name')
            if name_elem is not None:
                first = name_elem.findtext('.//first-name', '')
                last = name_elem.findtext('.//last-name', '')
                inventors.append(f"{first} {last}".strip())

        # If no standard inventors found, try applicant-inventors
        if not inventors:
            for applicant in root.findall('.//applicant[@app-type="applicant-inventor"]'):
                addressbook = applicant.find('.//addressbook')
                if addressbook is not None:
                    first = addressbook.findtext('.//first-name', '')
                    last = addressbook.findtext('.//last-name', '')
                    if first or last:
                        inventors.append(f"{first} {last}".strip())

        return inventors

    def _extract_applicants(self, root) -> list:
        """Extract applicant information"""
        applicants = []

        # Try standard applicant elements first
        for applicant in root.findall('.//applicant'):
            name_elem = applicant.find('.//name')
            if name_elem is not None:
                applicants.append(' '.join(name_elem.itertext()).strip())

        # If no standard applicants found, try addressbook format
        if not applicants:
            for applicant in root.findall('.//applicant'):
                addressbook = applicant.find('.//addressbook')
                if addressbook is not None:
                    # Check if it's an organization or person
                    orgname = addressbook.findtext('.//orgname', '')
                    if orgname:
                        applicants.append(orgname.strip())
                    else:
                        first = addressbook.findtext('.//first-name', '')
                        last = addressbook.findtext('.//last-name', '')
                        if first or last:
                            applicants.append(f"{first} {last}".strip())

        return applicants

    def _extract_classifications(self, root) -> dict:
        """Extract classification information"""
        classifications = {
            "uspc": [],
            "cpc": [],
            "ipc": []
        }

        # USPC classifications
        for uspc in root.findall('.//classification-us'):
            main = uspc.findtext('.//main-classification', '')
            if main:
                classifications["uspc"].append(main.strip())

        # CPC classifications
        for cpc in root.findall('.//classification-cpc'):
            symbol = cpc.findtext('.//symbol', '')
            if symbol:
                classifications["cpc"].append(symbol.strip())

        return classifications

    def _extract_citations(self, root) -> list:
        """Extract patent and non-patent citations"""
        citations = []
        for cite in root.findall('.//citation'):
            patent_cite = cite.find('.//patcit')
            if patent_cite is not None:
                doc_num = patent_cite.findtext('.//doc-number', '')
                if doc_num:
                    citations.append({
                        "type": "patent",
                        "number": doc_num.strip()
                    })
        return citations[:10]  # Limit for context

    def _extract_publication_info(self, root) -> dict:
        """Extract publication information"""
        pub_info = {}

        # Document number
        doc_num = root.findtext('.//doc-number')
        if doc_num:
            pub_info["document_number"] = doc_num.strip()

        # Publication date
        pub_date = root.findtext('.//publication-date')
        if pub_date:
            pub_info["publication_date"] = pub_date.strip()

        # Application number
        app_number = root.findtext('.//application-number')
        if app_number:
            pub_info["application_number"] = app_number.strip()

        return pub_info

    async def get_patent_or_application_xml(
        self,
        identifier: str,
        content_type: str = "auto",
        include_fields: Optional[List[str]] = None,
        include_raw_xml: bool = True
    ) -> Dict[str, Any]:
        """
        Get XML content with intelligent patent-to-application mapping.

        Args:
            identifier: Patent number (7971071) or application number (11752072)
            content_type: "patent", "application", "auto" (default: auto-detect)
            include_fields: Optional list of fields to include (default: ["abstract", "claims", "description"])
            include_raw_xml: Include raw XML in response (default: True for backward compatibility)

        Returns:
            Clean, structured XML content with full text, claims, and metadata
        """
        try:
            # Step 1: Determine if we have a patent or application number
            if content_type == "auto":
                content_type = self.detect_content_type(identifier)

            # Step 2: Get application number and associated documents
            if content_type == "patent":
                # Patent number → find originating application + get XML metadata
                app_number, assoc_docs = await self.find_application_for_patent(identifier)
                target_xml = "PTGRXML"  # Want granted patent XML

                # If minimal search didn't return associatedDocuments, fetch them
                if not assoc_docs:
                    assoc_docs_result = await self.get_associated_documents(app_number)
                    if assoc_docs_result.get("success"):
                        assoc_docs = {
                            "documents": assoc_docs_result.get("associated_documents", []),
                            "ptgrXmlAvailable": any(
                                "grantDocumentMetaData" in doc
                                for doc in assoc_docs_result.get("associated_documents", [])
                            ),
                            "appXmlAvailable": any(
                                "pgpubDocumentMetaData" in doc
                                for doc in assoc_docs_result.get("associated_documents", [])
                            )
                        }
            else:
                # Application number → use directly
                app_number = identifier
                target_xml = "APPXML"   # Want application XML

                # Get from direct API search first
                body = {
                    "q": f"applicationNumberText:{app_number}",
                    "pagination": {"limit": 1, "offset": 0},
                    "fields": ["applicationNumberText", "associatedDocuments"]
                }
                results = await self._make_request("search", method="POST", json=body)

                applications = results.get('patentFileWrapperDataBag', [])
                if applications:
                    assoc_docs = applications[0].get("associatedDocuments")

                # Fallback to direct API call if needed
                if not assoc_docs:
                    assoc_docs_result = await self.get_associated_documents(app_number)
                    if assoc_docs_result.get("success"):
                        assoc_docs = {
                            "documents": assoc_docs_result.get("associated_documents", []),
                            "ptgrXmlAvailable": any(
                                "grantDocumentMetaData" in doc
                                for doc in assoc_docs_result.get("associated_documents", [])
                            ),
                            "appXmlAvailable": any(
                                "pgpubDocumentMetaData" in doc
                                for doc in assoc_docs_result.get("associated_documents", [])
                            )
                        }

            # Step 3: Extract appropriate XML URL
            xml_url = self.extract_xml_url(assoc_docs, target_xml)

            # Step 4: Fetch and parse XML
            xml_content = await self.fetch_xml_from_url(xml_url)
            structured = self.parse_xml_for_llm(xml_content, include_fields)

            # Build fields metadata
            fields_metadata = self._build_fields_metadata(include_fields, structured)

            # Build response (conditionally include raw_xml)
            response = {
                "success": True,
                "identifier_used": identifier,
                "application_number": app_number,
                "xml_type": target_xml,
                "xml_source": xml_url,
                "structured_content": structured,
                "fields_metadata": fields_metadata,
                "data_limitation": "XML content only available for patents/applications filed after January 1, 2001"
            }

            # Only include raw_xml if requested (default True for backward compatibility)
            if include_raw_xml:
                response["raw_xml"] = xml_content

            return response

        except Exception as e:
            return format_error_response(f"Failed to get XML content: {str(e)}")

    def is_good_extraction(self, text: str) -> bool:
        """
        Determine if PyPDF2 extraction is usable.

        Criteria for "good" extraction:
        - Not empty or whitespace-only
        - Contains reasonable amount of text (>50 chars)
        - Contains readable words (not just symbols/garbage)
        - Has reasonable word-to-character ratio
        """

        if not text or len(text.strip()) < 50:
            return False

        # Check for reasonable word content
        words = text.split()
        if len(words) < 10:  # Very short extractions are probably garbage
            return False

        # Check character-to-word ratio (catch symbol/garbage extractions)
        avg_word_length = len(text) / len(words)
        if avg_word_length > 20:  # Probably garbage characters
            return False

        # Check for English-like content (basic heuristic)
        alpha_chars = sum(1 for c in text if c.isalpha())
        alpha_ratio = alpha_chars / len(text)
        if alpha_ratio < 0.6:  # Less than 60% alphabetic = probably scanned/garbage
            return False

        return True

    async def extract_with_pypdf2(self, pdf_content: bytes) -> str:
        """Extract text using PyPDF2"""
        if not PDF_AVAILABLE:
            raise ValueError("PyPDF2 not available")

        import PyPDF2
        import io

        pdf_reader = PyPDF2.PdfReader(io.BytesIO(pdf_content))
        text = ""

        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"

        return text.strip()

    async def extract_document_content_hybrid(
        self,
        app_number: str,
        document_identifier: str,
        auto_optimize: bool = True
    ) -> Dict[str, Any]:
        """
        Get document content with intelligent extraction method selection (Session 5 Enhancement).

        HYBRID APPROACH:
        - If auto_optimize=True (default): Try PyPDF2 first, fallback to Mistral OCR
        - If auto_optimize=False: Use Mistral OCR directly
        - Only charge for Mistral when actually used
        - Always returns usable text extraction

        Args:
            app_number: Application number (e.g., '11752072')
            document_identifier: Document ID from documentBag
            auto_optimize: Try free PyPDF2 first, fallback to Mistral OCR (default: True)

        Returns:
            Document content with extraction method and cost information
        """

        try:
            app_number = validate_app_number(app_number)

            # Get document metadata to validate the request
            docs_result = await self.get_documents(app_number)
            if docs_result.get('error'):
                return docs_result

            documents = docs_result.get('documentBag', [])

            # Find the target document
            target_doc = None
            for doc in documents:
                if doc.get('documentIdentifier') == document_identifier:
                    target_doc = doc
                    break

            if not target_doc:
                raise NotFoundError(
                    f"Document with identifier '{document_identifier}' not found in application {app_number}",
                    request_id=request_id
                )

            # Find PDF download option for metadata
            download_options = target_doc.get('downloadOptionBag', [])
            pdf_option = None

            for option in download_options:
                if option.get('mimeTypeIdentifier') == 'PDF':
                    pdf_option = option
                    break

            if not pdf_option:
                return format_error_response("PDF not available for this document")

            download_url = pdf_option.get('downloadUrl')
            page_count = pdf_option.get('pageTotalQuantity', 0)

            # Download PDF content
            async with httpx.AsyncClient(timeout=self.download_timeout, limits=self.download_limits, follow_redirects=True) as client:
                response = await client.get(download_url, headers=self.headers)
                response.raise_for_status()
                pdf_content = response.content

            extraction_result = {
                "success": True,
                "application_number": app_number,
                "document_identifier": document_identifier,
                "document_code": target_doc.get("documentCode"),
                "document_description": target_doc.get("documentCodeDescriptionText"),
                "official_date": target_doc.get("officialDate"),
                "page_count": page_count,
                "file_size_bytes": len(pdf_content)
            }

            if auto_optimize:
                # Phase 1: Try PyPDF2 first (free, fast)
                try:
                    if PDF_AVAILABLE:
                        pypdf2_text = await self.extract_with_pypdf2(pdf_content)

                        # Check if PyPDF2 extraction is usable
                        if self.is_good_extraction(pypdf2_text):
                            extraction_result.update({
                                "extracted_content": pypdf2_text,
                                "extraction_method": "PyPDF2",
                                "processing_cost_usd": 0.0,
                                "cost_breakdown": "Free PyPDF2 extraction - text-based PDF detected",
                                "auto_optimization": "PyPDF2 successful - no OCR needed"
                            })
                            return extraction_result
                        else:
                            # PyPDF2 failed - log and fallback
                            logger.info(f"PyPDF2 extraction poor for {document_identifier} - falling back to Mistral OCR")
                    else:
                        logger.warning("PyPDF2 not available - falling back to Mistral OCR")

                except Exception as e:
                    logger.warning(f"PyPDF2 extraction failed for {document_identifier}: {e} - falling back to Mistral OCR")

            # Phase 2: Use Mistral OCR (either fallback or direct)
            # First check if Mistral API key is available
            if not self.mistral_api_key:
                # No Mistral API key - provide helpful message
                if auto_optimize:
                    # PyPDF2 already tried and failed, no Mistral available
                    extraction_result.update({
                        "extracted_content": "",
                        "extraction_method": "PyPDF2 (insufficient)",
                        "processing_cost_usd": 0.0,
                        "error": "Document appears to be scanned/image-based. PyPDF2 could not extract meaningful text.",
                        "mistral_api_key_missing": True,
                        "suggestion": "Set MISTRAL_API_KEY environment variable for OCR capability on scanned documents",
                        "auto_optimization": "PyPDF2 failed, Mistral API key not available"
                    })
                else:
                    # User explicitly requested Mistral but no API key
                    extraction_result.update({
                        "extracted_content": "",
                        "extraction_method": "failed",
                        "processing_cost_usd": 0.0,
                        "error": "MISTRAL_API_KEY environment variable is required for OCR content extraction",
                        "mistral_api_key_missing": True,
                        "suggestion": "Set MISTRAL_API_KEY environment variable: set MISTRAL_API_KEY=your_key_here (Windows) or export MISTRAL_API_KEY=your_key_here (Linux/Mac)",
                        "auto_optimization": "Mistral OCR requested but API key not available"
                    })
                return extraction_result

            # Mistral API key is available, proceed with OCR
            mistral_result = await self.extract_document_content_with_mistral(app_number, document_identifier)

            if mistral_result.get("success"):
                extraction_result.update({
                    "extracted_content": mistral_result.get("extracted_content", ""),
                    "extraction_method": "Mistral OCR" + (" (PyPDF2 fallback)" if auto_optimize else " (direct)"),
                    "processing_cost_usd": mistral_result.get("processing_cost_usd", 0.0),
                    "cost_breakdown": mistral_result.get("cost_breakdown", ""),
                    "ocr_model": "mistral-ocr-latest",
                    "auto_optimization": "Mistral OCR used - scanned document detected" if auto_optimize else "Mistral OCR direct"
                })
            else:
                # Even Mistral failed - return basic document info
                extraction_result.update({
                    "extracted_content": "",
                    "extraction_method": "failed",
                    "processing_cost_usd": 0.0,
                    "error": mistral_result.get("error", "Content extraction failed"),
                    "auto_optimization": "Both PyPDF2 and Mistral OCR failed"
                })

            return extraction_result

        except Exception as e:
            return {
                "success": False,
                "application_number": app_number,
                "document_identifier": document_identifier,
                "error": str(e),
                "extracted_content": "",
                "extraction_method": "failed"
            }

    async def get_granted_patent_documents_download(
        self,
        app_number: str,
        include_drawings: bool = True,
        include_original_claims: bool = False,
        direction_category: Optional[str] = "INCOMING"
    ) -> Dict[str, Any]:
        """
        Get complete granted patent package (ABST, DRW, SPEC, CLM) in one call.

        Args:
            app_number: Patent application number
            include_drawings: Include drawings (default: True, set False to skip)
            include_original_claims: Get originally-filed claims vs. granted claims
                                    (default: False = get granted/final claims)
            direction_category: Filter claims by direction (default: INCOMING)
                              Set to None to get all claim versions

        Returns:
            dict: Structured response with all patent components and download metadata

        Raises:
            ValueError: If app_number is invalid
            Exception: If API call fails or no components found
        """

        # Validate app_number
        if not app_number or not isinstance(app_number, str):
            raise ValueError("app_number must be a non-empty string")

        # Get proxy port from environment variables
        # Check PFW_PROXY_PORT first (MCP-specific), then PROXY_PORT (generic)
        proxy_port = int(os.getenv('PFW_PROXY_PORT', os.getenv('PROXY_PORT', 8080)))

        # Components to retrieve
        components_to_fetch = ['ABST', 'SPEC', 'CLM']
        if include_drawings:
            components_to_fetch.insert(1, 'DRW')  # Insert after ABST

        results = {
            "success": False,
            "application_number": app_number,
            "granted_patent_components": {},
            "total_pages": 0,
            "components_found": [],
            "components_missing": [],
            "error_details": []
        }

        # Fetch each component
        for doc_code in components_to_fetch:
            try:
                # Call existing get_documents with filter
                response = await self.get_documents(
                    app_number=app_number,
                    document_code=doc_code,
                    direction_category=direction_category if doc_code != 'CLM' else direction_category,
                    limit=5  # Get up to 5 versions (for claims with amendments)
                )

                if response.get("success") and response.get("count", 0) > 0:
                    documents = response.get("documentBag", [])

                    # For claims, handle original vs granted
                    if doc_code == 'CLM':
                        if include_original_claims:
                            # Get oldest (originally filed) claims
                            selected_doc = min(documents, key=lambda d: d.get("officialDate", ""))
                        else:
                            # Get newest (granted/final) claims
                            selected_doc = max(documents, key=lambda d: d.get("officialDate", ""))
                    else:
                        # For other components, get the first (should only be one)
                        selected_doc = documents[0]

                    # Extract key information
                    component_name = doc_code.lower()
                    if doc_code == 'ABST':
                        component_name = 'abstract'
                    elif doc_code == 'DRW':
                        component_name = 'drawings'
                    elif doc_code == 'SPEC':
                        component_name = 'specification'
                    elif doc_code == 'CLM':
                        component_name = 'claims'

                    download_options = selected_doc.get("downloadOptionBag", [])
                    pdf_option = next((opt for opt in download_options if opt.get("mimeTypeIdentifier") == "PDF"), None)

                    results["granted_patent_components"][component_name] = {
                        "document_identifier": selected_doc.get("documentIdentifier"),
                        "document_code": selected_doc.get("documentCode"),
                        "document_description": selected_doc.get("documentCodeDescriptionText"),
                        "official_date": selected_doc.get("officialDate"),
                        "page_count": pdf_option.get("pageTotalQuantity", 0) if pdf_option else 0,
                        "direct_download_url": pdf_option.get("downloadUrl") if pdf_option else None,
                        "proxy_download_url": f"http://localhost:{proxy_port}/download/{app_number}/{selected_doc.get('documentIdentifier')}",
                        "direction_category": selected_doc.get("directionCategory")
                    }

                    results["total_pages"] += results["granted_patent_components"][component_name]["page_count"]
                    results["components_found"].append(component_name)
                else:
                    results["components_missing"].append(doc_code)

            except Exception as e:
                results["error_details"].append({
                    "component": doc_code,
                    "error": str(e)
                })
                results["components_missing"].append(doc_code)

        # Determine success
        results["success"] = len(results["components_found"]) >= 3  # At least 3 of 4 components

        # Add guidance for LLM response formatting
        results["llm_response_guidance"] = {
            "critical_requirement": "ALWAYS format each component as a clickable markdown link",
            "required_format": "**📁 [Download {ComponentName} ({PageCount} pages)]({proxy_download_url})**",
            "example": "**📁 [Download Abstract (1 page)](http://localhost:{port}/download/14171705/HR8IXPO4PXXIFW3)**",
            "presentation_order": ["abstract", "drawings", "specification", "claims"],
            "include_total": "Show total page count at end: 'Total: 59 pages'"
        }

        return results
