"""
Enhanced USPTO Patent File Wrapper API client

This client provides access to the USPTO Patent File Wrapper API for searching
applications, getting detailed application data, retrieving documents, and
downloading PDFs.
"""
import httpx
import os
# defusedxml: hardens against XXE / entity-expansion in USPTO-served XML (audit L12)
from typing import Dict, Any, List, Optional
from .helpers import validate_app_number, format_error_response, generate_request_id, create_inventor_queries, map_user_fields_to_api_fields
from ..exceptions import AuthenticationError, NotFoundError
from ..shared.safe_logger import get_safe_logger
from ..shared.uspto_shared_rate_limiter import get_shared_limiter

try:
    import PyPDF2  # noqa: F401 — availability probe; used lazily in extract_with_pypdf2
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

from .docling_client import DoclingClient

logger = get_safe_logger(__name__)


# Resilience primitives live in api/resilience.py (audit F3); re-exported
# here for backward compatibility (tests and older imports).
from .resilience import (  # noqa: E402, F401
    CircuitBreaker,
    CircuitState,
    ResponseCache,
    RetryBudget,
)


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
        self.ocr_timeout = float(os.getenv("MISTRAL_OCR_TIMEOUT", "30.0"))
        # Mistral OCR model slug. Default `mistral-ocr-latest` tracks Mistral's
        # current GA model (= OCR 4 as of 2026-06-23); pin a dated slug
        # (e.g. mistral-ocr-2503, mistral-ocr-4-0) via MISTRAL_OCR_MODEL.
        self.mistral_ocr_model = os.getenv("MISTRAL_OCR_MODEL", "mistral-ocr-latest")
        logger.info(f"Timeout configuration: default={self.default_timeout}s, download={self.download_timeout}s, ocr={self.ocr_timeout}s")

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

        # HTTP call path lives in USPTOTransport (audit F3): semaphore,
        # retry loop, circuit breaker, response cache, retry budget.
        from .transport import USPTOTransport
        self.transport = USPTOTransport(
            base_url=self.base_url,
            headers=self.headers,
            default_timeout=self.default_timeout,
            api_limits=self.api_limits,
            max_retries_per_hour=int(os.getenv("USPTO_MAX_RETRIES_PER_HOUR", "100")),
        )
        # Aliases: health endpoint and existing callers read these off the client
        self.semaphore = self.transport.semaphore
        self.circuit_breaker = self.transport.circuit_breaker
        self.response_cache = self.transport.response_cache
        self.retry_budget = self.transport.retry_budget

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

        # Single Mistral OCR implementation lives in OCRService (audit F1);
        # it owns rate limiting, the model slug, and the page cap.
        from ..services.ocr_service import OCRService
        self.ocr_service = OCRService(
            api_key=self.mistral_api_key,
            model=self.mistral_ocr_model,
            timeout=self.ocr_timeout,
            limits=self.ocr_limits,
        )

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
            "change_me",
            "replace_me",
            "insert_key_here",
            "api_key_here",
        ]
        if env_patterns:
            placeholder_patterns.extend([p.strip() for p in env_patterns.split(",") if p.strip()])

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

    async def _make_request(self, endpoint: str, method: str = "GET", **kwargs) -> Dict[str, Any]:
        """Make HTTP request to the PFW API — delegates to USPTOTransport
        (audit F3), which owns the semaphore/retry/breaker/cache/budget."""
        return await self.transport.request(endpoint, method, **kwargs)


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
            queries_failed = 0

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
                    # Never log the query text — user search intent is work-product
                    queries_failed += 1
                    logger.warning(f"Search query failed ({type(e).__name__}): {e}")
                    continue

            response = {
                "success": True,
                "inventor_name": name,
                "strategy": strategy,
                "total_unique_applications": len(all_results),
                "unique_applications": all_results[:limit],
                "queries_used": queries[:5]  # Show first 5 queries used
            }
            # Aggregate failure reporting (audit F26): silent partial results
            # look identical to complete ones otherwise
            if queries_failed:
                response["queries_failed"] = queries_failed
                response["partial_results_note"] = (
                    f"{queries_failed} of {len(queries)} search queries failed; "
                    "results may be incomplete."
                )
            return response

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
                    "ocrExtraction": "pfw_get_document_content_with_ocr requires applicationNumberText + document_identifier from pfw_get_application_documents",
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
                "applicationMetaData.applicationStatusCode:Patent"
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

    async def _download_once(self, url: str) -> "httpx.Response":
        """Perform exactly one direct USPTO download GET (XML or PDF),
        gated by the shared cross-process rate limiter (token + concurrency
        slot) — off unless USPTO_SHARED_RATE_LIMIT_DIR is set. Single choke
        point for the two download paths that don't route through
        USPTOTransport (fetch_xml_from_url and the OCR-extraction PDF
        fetch); both are api.uspto.gov fetches under the same ODP key."""
        async with httpx.AsyncClient(timeout=self.download_timeout, limits=self.download_limits, follow_redirects=True) as client:
            send = client.get(url, headers=self.headers)
            limiter = get_shared_limiter()
            if limiter is not None:
                async with limiter:
                    return await send
            return await send

    async def fetch_xml_from_url(self, xml_url: str) -> str:
        """
        Fetch XML content from the provided URL.

        Args:
            xml_url: URL to fetch XML from

        Returns:
            Raw XML content as string
        """
        try:
            response = await self._download_once(xml_url)
            response.raise_for_status()
            return response.text
        except Exception as e:
            raise ValueError(f"Failed to fetch XML from URL {xml_url}: {str(e)}")

    # XML parsing lives in api/xml_parsing.py (audit F3); these delegators
    # preserve the public client surface.
    def parse_xml_for_llm(self, xml_content: str, include_fields: Optional[List[str]] = None) -> dict:
        """Parse USPTO XML into LLM-friendly structured format (see
        api/xml_parsing.py for field options)."""
        from .xml_parsing import parse_xml_for_llm
        return parse_xml_for_llm(xml_content, include_fields)

    def _build_fields_metadata(self, include_fields, structured_content) -> dict:
        from .xml_parsing import build_fields_metadata
        return build_fields_metadata(include_fields, structured_content)


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

    async def extract_with_docling(self, pdf_content: bytes, document_identifier: str) -> str:
        """Extract text via docling-serve REST API (true OCR, handles scanned PDFs).

        Uses the DOCLING_SERVE_URL environment variable to locate the server.
        Supports both local Docker (http://localhost:5001) and remote instances.
        """
        client = DoclingClient()
        return await client.extract(pdf_content, filename=f"{document_identifier}.pdf")

    async def _fetch_document_for_extraction(
        self, app_number: str, document_identifier: str, request_id: str, progress_cb=None
    ):
        """Resolve document metadata and download the PDF for extraction.

        Returns (target_doc, pdf_option, pdf_content) on success, or an error
        dict (shaped like a tool response) that the orchestrator returns
        as-is. Raises NotFoundError for an unknown document identifier.
        """
        docs_result = await self.get_documents(app_number)
        if docs_result.get('error'):
            return docs_result

        target_doc = None
        for doc in docs_result.get('documentBag', []):
            if doc.get('documentIdentifier') == document_identifier:
                target_doc = doc
                break
        if not target_doc:
            raise NotFoundError(
                f"Document with identifier '{document_identifier}' not found in application {app_number}",
                request_id=request_id
            )

        pdf_option = None
        for option in target_doc.get('downloadOptionBag', []):
            if option.get('mimeTypeIdentifier') == 'PDF':
                pdf_option = option
                break
        if not pdf_option:
            return format_error_response("PDF not available for this document")

        page_count = pdf_option.get('pageTotalQuantity', 0)
        if progress_cb:
            await progress_cb(10, 100, f"Downloading PDF ({page_count} pages)...")

        # A download failure blocks every extraction tier — label it as such
        # (audit F49: previously reported as extraction_method "failed")
        try:
            response = await self._download_once(pdf_option.get('downloadUrl'))
            response.raise_for_status()
            pdf_content = response.content
        except Exception as e:
            return {
                "success": False,
                "application_number": app_number,
                "document_identifier": document_identifier,
                "error": f"Failed to download PDF from USPTO: {e}",
                "extracted_content": "",
                "extraction_method": "download_failed",
            }

        return target_doc, pdf_option, pdf_content

    async def _try_pypdf2_tier(self, pdf_content: bytes, document_identifier: str, progress_cb=None):
        """Tier 1 (auto-optimize only): free PyPDF2 text extraction.
        Returns a result-update dict, or None to fall through."""
        if progress_cb:
            await progress_cb(25, 100, "Trying text extraction (PyPDF2)...")
        try:
            if not PDF_AVAILABLE:
                logger.warning("PyPDF2 not available - falling back to Mistral OCR")
                return None
            pypdf2_text = await self.extract_with_pypdf2(pdf_content)
            if not self.is_good_extraction(pypdf2_text):
                logger.info(f"PyPDF2 extraction poor for {document_identifier} - falling back to Mistral OCR")
                return None
            return {
                "extracted_content": pypdf2_text,
                "extraction_method": "PyPDF2",
                "processing_cost_usd": 0.0,
                "cost_breakdown": "Free PyPDF2 extraction - text-based PDF detected",
                "auto_optimization": "PyPDF2 successful - no OCR needed",
            }
        except Exception as e:
            logger.warning(f"PyPDF2 extraction failed for {document_identifier}: {e} - falling back to Mistral OCR")
            return None

    async def _try_mistral_tier(
        self, pdf_content: bytes, page_count: int, app_number: str,
        document_identifier: str, auto_optimize: bool, progress_cb=None
    ):
        """Tier 2: Mistral OCR via OCRService (paid, ~$0.001/page).
        Returns a result-update dict, or None to fall through."""
        if not self.mistral_api_key:
            return None
        if progress_cb:
            await progress_cb(50, 100, f"Sending to Mistral OCR ({page_count} pages)...")
        mistral_result = await self.ocr_service.extract_document_content(
            pdf_content, page_count, app_number, document_identifier
        )
        if not mistral_result.get("success"):
            logger.warning(
                f"Mistral OCR failed for {document_identifier}: {mistral_result.get('error')} - falling back to Docling"
            )
            return None
        update = {
            "extracted_content": mistral_result.get("extracted_content", ""),
            "extraction_method": "Mistral OCR" + (" (PyPDF2 fallback)" if auto_optimize else " (direct)"),
            "processing_cost_usd": mistral_result.get("processing_cost_usd", 0.0),
            "cost_breakdown": mistral_result.get("cost_breakdown", ""),
            "ocr_model": mistral_result.get("ocr_model", self.mistral_ocr_model),
            "auto_optimization": "Mistral OCR used - scanned document detected" if auto_optimize else "Mistral OCR direct",
        }
        # Pass through the cost-cap truncation signal (audit F48)
        if mistral_result.get("pages_truncated"):
            update["pages_truncated"] = mistral_result["pages_truncated"]
            update["truncation_note"] = mistral_result.get("truncation_note", "")
        return update

    async def _try_docling_tier(
        self, pdf_content: bytes, page_count: int, document_identifier: str,
        docling_client, progress_cb=None
    ):
        """Tier 3 (auto-optimize only): free Docling OCR via docling-serve.
        Returns a result-update dict, or None to fall through."""
        if not docling_client.is_available():
            return None
        if not docling_client.within_page_limit(page_count):
            logger.warning(
                f"Skipping Docling for {document_identifier}: {page_count} pages exceeds "
                f"DOCLING_MAX_PAGES={docling_client.max_pages}. Set MISTRAL_API_KEY for large documents."
            )
            return None
        try:
            if progress_cb:
                await progress_cb(50, 100, f"Sending to Docling OCR ({page_count} pages — this may take a minute)...")
            docling_text = await self.extract_with_docling(pdf_content, document_identifier)
            if not self.is_good_extraction(docling_text):
                logger.info(f"Docling extraction also poor for {document_identifier}")
                return None
            return {
                "extracted_content": docling_text,
                "extraction_method": "Docling OCR",
                "processing_cost_usd": 0.0,
                "cost_breakdown": "Free Docling extraction - EasyOCR engine, handles scanned documents",
                "auto_optimization": "Docling OCR used - PyPDF2 insufficient, no Mistral key",
            }
        except Exception as e:
            logger.warning(f"Docling extraction failed for {document_identifier}: {e}")
            return None

    async def extract_document_content_hybrid(
        self,
        app_number: str,
        document_identifier: str,
        auto_optimize: bool = True,
        progress_cb=None
    ) -> Dict[str, Any]:
        """
        Get document content with intelligent extraction method selection.

        Walks a tier waterfall (each tier is its own method — audit: this was
        a single ~200-line function at manual complexity ~18-20):
        - auto_optimize=True (default): PyPDF2 (free) -> Mistral OCR (paid)
          -> Docling OCR (free, self-hosted)
        - auto_optimize=False: Mistral OCR only
        Only charges for Mistral when that tier actually runs.

        Args:
            app_number: Application number (e.g., '11752072')
            document_identifier: Document ID from documentBag
            auto_optimize: Try free PyPDF2 first, fall back to OCR (default: True)

        Returns:
            Document content with extraction method and cost information
        """
        try:
            app_number = validate_app_number(app_number)
            request_id = generate_request_id()

            fetched = await self._fetch_document_for_extraction(
                app_number, document_identifier, request_id, progress_cb
            )
            if isinstance(fetched, dict):  # error response from fetch/download
                return fetched
            target_doc, pdf_option, pdf_content = fetched
            page_count = pdf_option.get('pageTotalQuantity', 0)

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
                update = await self._try_pypdf2_tier(pdf_content, document_identifier, progress_cb)
                if update is not None:
                    extraction_result.update(update)
                    return extraction_result

            update = await self._try_mistral_tier(
                pdf_content, page_count, app_number, document_identifier, auto_optimize, progress_cb
            )
            if update is not None:
                extraction_result.update(update)
                return extraction_result

            if not auto_optimize and not self.mistral_api_key:
                # User explicitly requested Mistral but no API key
                extraction_result.update({
                    "extracted_content": "",
                    "extraction_method": "failed",
                    "processing_cost_usd": 0.0,
                    "error": "MISTRAL_API_KEY environment variable is required for OCR content extraction",
                    "mistral_api_key_missing": True,
                    "suggestion": "Set MISTRAL_API_KEY environment variable: set MISTRAL_API_KEY=your_key_here (Windows) or export MISTRAL_API_KEY=your_key_here (Linux/Mac)",
                })
                return extraction_result

            docling_client = DoclingClient()
            if auto_optimize:
                update = await self._try_docling_tier(
                    pdf_content, page_count, document_identifier, docling_client, progress_cb
                )
                if update is not None:
                    extraction_result.update(update)
                    return extraction_result

            # All methods failed
            extraction_result.update({
                "extracted_content": "",
                "extraction_method": "failed",
                "processing_cost_usd": 0.0,
                "error": "Document appears to be a scanned image. Could not extract meaningful text.",
                "mistral_api_key_missing": not bool(self.mistral_api_key),
                "docling_not_configured": not docling_client.is_available(),
                "docling_page_limit_exceeded": docling_client.is_available() and not docling_client.within_page_limit(page_count),
                "suggestion": (
                    "Add MISTRAL_API_KEY to enable Mistral OCR (~$0.001/page), or "
                    "set DOCLING_SERVE_URL to enable free Docling OCR (e.g. http://localhost:5001 or https://docling.[yourdomain].com)."
                ),
                "llm_guidance": {
                    "explain_to_user": "Many USPTO Patent File Wrapper documents are scanned images rather than text-based PDFs. "
                                      "PyPDF2 cannot read scanned images. Mistral OCR and Docling handle true scans.",
                    "recommended_solution": "Configure MISTRAL_API_KEY (~$0.001/page) or DOCLING_SERVE_URL (free, self-hosted)",
                    "free_tier_info": "Mistral offers a generous free tier - sign up at https://console.mistral.ai/",
                    "cost_example": "A typical 7-page office action costs only $0.007 with Mistral OCR"
                }
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
                        "proxy_download_url": f"{os.getenv('PFW_PROXY_BASE_URL', f'http://localhost:{proxy_port}')}/download/{app_number}/{selected_doc.get('documentIdentifier')}",
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
            "critical_requirement": "ALWAYS format each component as a clickable markdown link AND raw URL",
            "required_format": "**📁 [Download {ComponentName} ({PageCount} pages)]({proxy_download_url})** | Raw URL: `{proxy_download_url}`",
            "example": "**📁 [Download Abstract (1 page)]({proxy_download_url})** | Raw URL: `{proxy_download_url}`",
            "presentation_order": ["abstract", "drawings", "specification", "claims"],
            "include_total": "Show total page count at end: 'Total: 59 pages'",
            "explanation": "Clickable link works in Claude Desktop, raw URL enables copy/paste in Msty and other clients where links aren't clickable"
        }

        return results
