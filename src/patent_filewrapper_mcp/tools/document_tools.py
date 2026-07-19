"""Document tools: OCR content, downloads, documentBag, XML, granted-patent
package (audit F2 split from main.py)."""

import os
from typing import Any, Dict, List, Optional

from fastmcp import Context
from fastmcp.server.apps import AppConfig

from ..api.helpers import (
    format_error_response,
    validate_app_number,
)
from ..client_registry import _client
from ..models.constants import DocumentDirection
from ..shared.injection_scan import RETRIEVED_TEXT_NOTE, _WARNING_NOTE, scan_text
from ..shared.safe_logger import get_safe_logger
from ..util.error_handlers import mcp_error_handler
from ..app_uris import _DOWNLOADS_URI, _XML_URI
from ..server_bootstrap import _ensure_proxy_server_running

logger = get_safe_logger(__name__)

# Max documents returnable by get_application_documents (audit F37)
MAX_DOCUMENT_LIMIT = 200


def _resolve_proxy_port(proxy_port: Optional[int]) -> int:
    """PFW_PROXY_PORT first (MCP-specific), then PROXY_PORT, then 8080."""
    if proxy_port is not None:
        return proxy_port
    return int(os.getenv('PFW_PROXY_PORT', os.getenv('PROXY_PORT', 8080)))


async def _resolve_target_document(client, app_number: str, document_identifier: str):
    """Find a document and its PDF download option in the application's
    documentBag. Returns (target_doc, pdf_option) or an error dict."""
    docs_result = await client.get_documents(app_number)
    if docs_result.get('error'):
        return docs_result

    target_doc = None
    for doc in docs_result.get('documentBag', []):
        if doc.get('documentIdentifier') == document_identifier:
            target_doc = doc
            break
    if not target_doc:
        return format_error_response(f"Document with identifier '{document_identifier}' not found")

    pdf_option = None
    for option in target_doc.get('downloadOptionBag', []):
        if option.get('mimeTypeIdentifier') == 'PDF':
            pdf_option = option
            break
    if not pdf_option:
        return format_error_response("PDF not available for this document")

    return target_doc, pdf_option


def _build_download_link(
    app_number: str, document_identifier: str, proxy_port: int, generate_persistent_link: bool
) -> str:
    """Immediate or persistent (7-day encrypted) proxy download URL.
    PFW_PROXY_BASE_URL overrides the base for external deployments."""
    proxy_base = os.getenv("PFW_PROXY_BASE_URL", f"http://localhost:{proxy_port}")
    if generate_persistent_link:
        from ..proxy.secure_link_cache import get_link_cache
        return get_link_cache().generate_persistent_link(app_number, document_identifier, proxy_base)
    return f"{proxy_base}/download/{app_number}/{document_identifier}"


async def _get_title_and_patent_number(client, app_number: str):
    """Best-effort (invention_title, patent_number) lookup for filename
    enrichment; returns (None, None) on any failure."""
    try:
        search_result = await client.search_applications(
            f"applicationNumberText:{app_number}",
            limit=1,
            offset=0,
            fields=["applicationMetaData.inventionTitle", "applicationMetaData.patentNumber"]
        )
        if search_result.get('success'):
            apps = search_result.get('patentFileWrapperDataBag') or search_result.get('applications')
            if apps:
                from ..api.helpers import extract_patent_number
                title = apps[0].get('applicationMetaData', {}).get('inventionTitle')
                return title, extract_patent_number(apps[0])
    except Exception as e:
        logger.warning(f"Could not fetch application metadata for {app_number}: {e}")
    return None, None



def _iter_strings(value):
    """Yield every string leaf in a nested dict/list structure (used to scan
    structured_content regardless of the exact claims/description shape)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _iter_strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _iter_strings(v)


def _create_document_summary(documents: List[dict]) -> Dict[str, Any]:
    """Create summary of available documents for LLM guidance"""

    if not documents:
        return {"total": 0, "types": {}, "key_documents": []}

    summary = {
        "total": len(documents),
        "document_types": {},
        "key_documents": [],
        "total_download_options": 0
    }

    # Count document types and download options
    for doc in documents:
        doc_code = doc.get("documentCode", "UNKNOWN")
        summary["document_types"][doc_code] = summary["document_types"].get(doc_code, 0) + 1
        summary["total_download_options"] += len(doc.get("downloadOptionBag", []))

    # Identify key documents for patent analysis
    key_doc_codes = ["ABST", "CLM", "SPEC", "NOA", "CTFR", "CTNF", "DRW"]
    for doc in documents:
        if doc.get("documentCode") in key_doc_codes:
            download_options = doc.get("downloadOptionBag", [])
            if download_options:
                summary["key_documents"].append({
                    "document_code": doc.get("documentCode"),
                    "document_description": doc.get("documentCodeDescriptionText", ""),
                    "official_date": doc.get("officialDate", ""),
                    "document_identifier": doc.get("documentIdentifier", ""),
                    "page_count": download_options[0].get("pageTotalQuantity", 0),
                    "download_url": download_options[0].get("downloadUrl", "")
                })

    return summary


async def _register_download_via_proxy(port: int, title: str, doc_type: str, app_number: str, proxy_url: str, filename: str = "") -> None:
    """POST a download registration to the proxy server.

    Works whether the proxy is in-process (asyncio task) or a separately running
    instance (e.g. ENABLE_ALWAYS_ON_PROXY=true carries over across sessions).
    Silently ignores failures so it never blocks tool output.
    """
    try:
        import httpx

        # Import the token directly from the proxy module — same process, same token.
        # In HTTP mode the proxy runs as a daemon thread in this process, so
        # _get_proxy_token() returns the same value the proxy server validates against.
        from ..proxy.server import _get_proxy_token
        proxy_token = _get_proxy_token()

        headers = {"X-Proxy-Token": proxy_token}
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(
                f"http://localhost:{port}/api/register-download",
                json={
                    "title": title,
                    "doc_type": doc_type,
                    "app_number": app_number,
                    "proxy_url": proxy_url,
                    "filename": filename or "",
                },
                headers=headers,
            )
            resp.raise_for_status()
            logger.info("Registered download '%s' via proxy (HTTP %s)", title, resp.status_code)
    except Exception as e:
        logger.warning(f"Could not register download via proxy endpoint (port {port}): {e}")




def register(mcp) -> None:
    """Register the five document tools."""
    @mcp.tool(name="pfw_get_document_content_with_ocr", annotations={"defer_loading": True, "readOnlyHint": True})
    @mcp_error_handler
    async def pfw_get_document_content(
        app_number: str,
        document_identifier: str,
        auto_optimize: bool = True,
        ctx: Context = None
    ) -> Dict[str, Any]:
        """Extract full text from USPTO prosecution documents with intelligent hybrid extraction (PyPDF2 first, Mistral OCR fallback).
    PREREQUISITE: First use pfw_get_application_documents to get document_identifier from documentBag.
    Auto-optimizes cost: free PyPDF2 for text-based PDFs, ~$0.001/page Mistral OCR only for scanned documents.
    MISTRAL_API_KEY is optional - without it, only PyPDF2 extraction is available (works well for text-based PDFs).
    Returns: extracted_content, extraction_method, processing_cost_usd.
    Example workflow:
    1. pfw_get_application_documents(app_number='17896175') → get doc IDs
    2. pfw_get_document_content_with_ocr(app_number='17896175', document_identifier='ABC123XYZ')
    For document selection strategies and cost optimization, use pfw_get_guidance (see quick reference chart for section selection)."""
        try:
            api_client = _client()

            async def _progress(progress: float, total: float, message: str):
                if ctx:
                    await ctx.report_progress(progress, total, message)

            result = await api_client.extract_document_content_hybrid(
                app_number, document_identifier, auto_optimize, progress_cb=_progress
            )
            # Provenance labeling + detection-only injection scan of the
            # extracted text (kind labels only, text served verbatim — see
            # shared/injection_scan.py). `injection_scan` is ABSENT when clean.
            if isinstance(result, dict) and result.get("success"):
                result["provenance_note"] = RETRIEVED_TEXT_NOTE
                kinds = scan_text(result.get("extracted_content") or "")
                if kinds:
                    result["injection_scan"] = {
                        "flagged": [{
                            "application_number": result.get("application_number", app_number),
                            "document_identifier": result.get("document_identifier", document_identifier),
                            "kinds": kinds,
                        }],
                        "note": _WARNING_NOTE,
                    }
            return result
        except RuntimeError as e:
            # Catch async lifecycle errors specifically
            error_msg = str(e)
            if "cannot schedule new futures" in error_msg or "interpreter shutdown" in error_msg:
                logger.error(f"Async lifecycle error in document extraction: {error_msg}")
                return format_error_response(
                    "Document extraction failed due to async runtime issue. This may be an environment-specific problem. "
                    "Try restarting the MCP server or check if MISTRAL_API_KEY is properly configured. "
                    f"Technical details: {error_msg}"
                )
            else:
                return format_error_response(f"Runtime error during document extraction: {str(e)}")
        except Exception as e:
            logger.exception("Unexpected error in document content extraction")
            return format_error_response(f"Failed to extract document content: {str(e)}")

    # --- download-tool helpers (extracted from pfw_get_document_download; audit:
    # --- the tool body was ~140 logic lines doing 6 jobs at complexity ~12-14) ---


    @mcp.tool(name="pfw_get_document_download", app=AppConfig(resource_uri=_DOWNLOADS_URI), annotations={"defer_loading": True, "readOnlyHint": True})
    @mcp_error_handler
    async def pfw_get_document_download(app_number: str, document_identifier: str, proxy_port: Optional[int] = None, generate_persistent_link: bool = True) -> Dict[str, Any]:
        """Generate secure browser-accessible download URLs for USPTO prosecution documents (PDFs).
    PREREQUISITE: First use pfw_get_application_documents to get document_identifier from documentBag.
    Creates clickable proxy links that handle API authentication while keeping credentials secure.

    🔗 LINK TYPES:
    - generate_persistent_link=True: Persistent links (default) - encrypted, valid for 7 days
    - generate_persistent_link=False: Immediate links - work while proxy running

    🔧 ENHANCED PROXY BEHAVIOR:
    - Always-on proxy: Set ENABLE_ALWAYS_ON_PROXY=true for immediate access
    - On-demand proxy: Automatic startup when first download is requested
    - Persistent links: Enabled by default - 7-day encrypted links (set generate_persistent_link=false to disable)
    - Download links work immediately in user's browser and remain valid for 7 days

    🔒 PERSISTENT LINK BENEFITS:
    - Links work for 7 days without proxy restart
    - Encrypted storage - no sensitive data in URLs
    - Automatic cleanup of expired links
    - Perfect for lawyer workflows with delayed document review

    CRITICAL RESPONSE FORMAT - Always format with BOTH clickable link and raw URL:
    **📁 [Download {DocumentType} ({PageCount} pages)]({proxy_url})** | Raw URL: `{proxy_url}`

    Why both formats?
    - Clickable links work in Claude Desktop and most clients
    - Raw URLs enable copy/paste in Msty and other clients where links aren't clickable

    Example workflow for multiple downloads:
    1. pfw_get_application_documents(app_number='17896175') → get doc IDs
    2. pfw_get_document_download(app_number='17896175', document_identifier='ABC123XYZ') → GENERATES PERSISTENT LINK
    3. Format ALL download links as clickable markdown (links work immediately and remain valid for 7 days)
    4. Optional: Use generate_persistent_link=false for immediate-only links (requires proxy to stay running)

    For document selection strategies and multi-document workflows, use pfw_get_guidance (see quick reference chart for section selection)."""
        try:
            api_client = _client()

            proxy_port = _resolve_proxy_port(proxy_port)
            app_number = validate_app_number(app_number)

            # Start proxy server if not already running
            await _ensure_proxy_server_running(proxy_port)

            resolved = await _resolve_target_document(api_client, app_number, document_identifier)
            if isinstance(resolved, dict):  # error response
                return resolved
            target_doc, pdf_option = resolved

            proxy_download_url = _build_download_link(
                app_number, document_identifier, proxy_port, generate_persistent_link
            )
            original_download_url = pdf_option.get('downloadUrl', '')

            invention_title, patent_number = await _get_title_and_patent_number(api_client, app_number)

            # Generate expected filename for user reference
            expected_filename = "Legacy format used (metadata unavailable)"
            if invention_title:
                from ..api.helpers import generate_safe_filename
                expected_filename = generate_safe_filename(app_number, invention_title, target_doc.get('documentCode', 'UNKNOWN'), patent_number)

            document_info = {
                "document_code": target_doc.get('documentCode', ''),
                "document_description": target_doc.get('documentCodeDescriptionText', ''),
                "official_date": target_doc.get('officialDate', ''),
                "page_count": pdf_option.get('pageTotalQuantity', 0),
                "file_size_bytes": pdf_option.get('fileSizeQuantity', 0),
                "invention_title": invention_title,
                "patent_number": patent_number,
                "expected_filename_format": expected_filename,
                "filename_enhancement": {
                    "app_prefix": f"APP-{app_number}",
                    "patent_prefix": f"PAT-{patent_number}" if patent_number else "No patent granted",
                    "title_portion": invention_title[:40] if invention_title else "UNTITLED",
                    "document_type": target_doc.get('documentCode', 'UNKNOWN')
                }
            }

            # Register in recent downloads store for the MCP App panel (via proxy endpoint)
            await _register_download_via_proxy(
                port=proxy_port,
                title=document_info.get("document_description") or document_info.get("document_code") or "Document",
                doc_type=document_info.get("document_code", ""),
                app_number=app_number,
                proxy_url=proxy_download_url,
                filename=expected_filename if isinstance(expected_filename, str) and expected_filename != "Legacy format used (metadata unavailable)" else "",
            )

            return {
                "success": True,
                "proxy_download_url": proxy_download_url,
                "original_download_url": original_download_url,
                "document_info": document_info,
                "application_number": app_number,
                "document_identifier": document_identifier,

                # LLM guidance for proper response formatting
                "llm_response_guidance": {
                    "format": f"**📁 [Download {document_info.get('document_description', 'Document')} ({document_info.get('page_count', 'N/A')} pages)]({proxy_download_url})** | Raw URL: `{proxy_download_url}`",
                    "critical": "Provide clickable markdown link for browser access AND raw URL for clients like Msty where links aren't clickable",
                    "explanation": "Clickable link works in Claude Desktop, raw URL enables copy/paste in Msty and other clients"
                },
                "note": "Proxy handles authentication and rate limiting (5 downloads per 10s)"
            }

        except Exception as e:
            return format_error_response(f"Failed to create download proxy: {str(e)}")


    @mcp.tool(name="get_application_documents", annotations={"defer_loading": False, "readOnlyHint": True})
    @mcp_error_handler
    async def pfw_get_application_documents(
        app_number: str,
        limit: int = 50,
        document_code: Optional[str] = None,
        direction_category: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get prosecution document metadata (documentBag) with SELECTIVE FILTERING to avoid context explosion.

    ⚠️ CRITICAL: For heavily-prosecuted applications with 200+ documents, ALWAYS use filtering parameters.
    Requesting all documents without filters can cause massive token usage (100K+ characters).

    🆕 FOR GRANTED PATENTS: Use pfw_get_granted_patent_documents_download for complete patent package (ABST, DRW, SPEC, CLM).

    📋 FILTERING PARAMETERS:

    **document_code** - Filter by specific document type (case-insensitive):
      Key Examiner Actions:
        - NOA: Notice of Allowance, CTNF: Non-Final Rejection, CTFR: Final Rejection, 892: Examiner Citations
      Key Applicant Responses:
        - A...: Amendment/Response, RCEX: Continued Examination, IDS: Info Disclosure, 1449: Applicant Citations
      Patent Components:
        - ABST: Abstract, CLM: Claims, SPEC: Specification, DRW: Drawings, FWCLM: Claims Index

    **direction_category** - Filter by source:
        - INCOMING: Applicant submissions, OUTGOING: USPTO examiner documents, INTERNAL: USPTO internal

    **limit** - Max documents to return (default: 50, max: 200). Applied AFTER filtering.

    📌 EXAMPLES (always use filtering):

    # Allowance reasoning for litigation
    pfw_get_application_documents(app_number='14171705', document_code='NOA')

    # Office action rejections
    pfw_get_application_documents(app_number='14171705', document_code='CTFR', limit=20)

    # All applicant responses
    pfw_get_application_documents(app_number='14171705', direction_category='INCOMING', limit=100)

    # Examiner's cited prior art
    pfw_get_application_documents(app_number='14171705', document_code='892')

    ⚠️ AVOID: pfw_get_application_documents(app_number='...', limit=200) without filters
    ✅ DO: Always filter by document_code or direction_category

    Returns document identifiers needed for pfw_get_document_download or pfw_get_document_content_with_ocr.

    For cross-MCP workflows, use pfw_get_guidance (see quick reference chart)."""
        try:
            api_client = _client()

            # Input validation
            if not app_number or len(app_number.strip()) == 0:
                return format_error_response("Application number cannot be empty", 400)
            if limit < 1 or limit > MAX_DOCUMENT_LIMIT:
                return format_error_response(f"Limit must be between 1 and {MAX_DOCUMENT_LIMIT}", 400)
            if direction_category and not DocumentDirection.is_valid(direction_category):
                return format_error_response(
                    f"direction_category must be one of: {', '.join(DocumentDirection.all())}",
                    400
                )

            # Validate and clean app number
            app_number = validate_app_number(app_number)

            # Get document bag from USPTO API with filtering
            docs_result = await api_client.get_documents(
                app_number,
                limit=limit,
                document_code=document_code,
                direction_category=direction_category
            )

            if docs_result.get('error'):
                return docs_result

            return {
                "success": True,
                "application_number": docs_result.get('application_number'),
                "count": docs_result.get('count'),
                "documentBag": docs_result.get('documentBag', []),
                "summary": docs_result.get('summary', {}),
                "request_id": f"docs-{app_number}",
                "guidance": {
                    "workflow": [
                        "Use document_identifier with pfw_get_document_download for browser downloads",
                        "Use document_identifier with pfw_get_document_content_with_ocr for text extraction (auto PyPDF2/OCR)",
                        "Filter with document_code (NOA, CTFR, CTNF, 892) for key documents"
                    ],
                    "filtering": {
                        "noa": "document_code='NOA' - Allowance reasoning",
                        "rejections": "document_code='CTFR'/'CTNF' - Office actions",
                        "prior_art": "document_code='892' - Examiner citations, '1449' - Applicant citations",
                        "amendments": "document_code='CLM' - Claim evolution"
                    },
                    "cross_mcp": {
                        "ptab": "PTAB applicationNumberText/patentNumber → PFW minimal → get_application_documents(document_code='NOA') → compare examiner vs PTAB reasoning",
                        "fpd": "FPD applicationNumber → PFW minimal → get_application_documents(document_code='CTFR'|'CTNF') → analyze rejection patterns",
                        "citations": "Citations applicationNumber/patentNumber → PFW minimal → get_application_documents(document_code='892'|'1449') → examiner citation analysis"
                    },
                    "key_insight": "Document identifiers are ONLY valid with this specific applicationNumberText",
                    "expectation": "No single 'complete patent PDF' - must download individual documents"
                }
            }

        except Exception as e:
            return {
                "success": False,
                "application_number": app_number,
                "error": str(e),
                "documentBag": [],
                "count": 0
            }


    @mcp.tool(name="get_patent_or_application_xml", app=AppConfig(resourceUri=_XML_URI), annotations={"defer_loading": True, "readOnlyHint": True})
    @mcp_error_handler
    async def pfw_get_patent_or_application_xml(
        identifier: str,
        content_type: str = "auto",
        include_fields: Optional[List[str]] = None,
        include_raw_xml: bool = True
    ) -> Dict[str, Any]:
        """Get structured XML content for patents or applications (filed after January 1, 2001).
    Use after finding applications via search to analyze claims, description, abstract, and citations.
    Auto-detects patent vs application from identifier. Prefers granted patent XML (PTGRXML) over application XML (APPXML).

    **DEFAULT BEHAVIOR (include_fields not specified):**
    Returns only core content fields optimized for patent analysis (~5K tokens structured + ~50K raw_xml):
    - abstract: Full abstract text
    - claims: All independent and dependent claims with full text
    - description: First 5 paragraphs of detailed description/specification

    **MAXIMUM EFFICIENCY (include_raw_xml=False):**
    Suppress raw XML to achieve 95% token reduction (e.g., ~1.5K tokens for claims only):
    - Set include_raw_xml=False when you only need structured_content fields
    - Raw XML useful for debugging or custom parsing, but not needed for most workflows

    **AVAILABLE FIELDS (use include_fields to customize):**
    Core Content:
      - abstract: Full abstract text
      - claims: All claims with full text
      - description: First 5 paragraphs of specification

    Metadata (also available via pfw_search_applications_balanced):
      - inventors: Inventor names, sequences, and locations
      - applicants: Applicant/assignee information
      - classifications: USPTO and Cooperative Patent Classifications (CPC/IPC)
      - publication_info: Publication dates, numbers, and document information

    References:
      - citations: Forward and backward citations (consider uspto_enriched_citation_mcp for richer analysis)

    **SELECTIVE USAGE EXAMPLES:**

    1. Recommended (patent analysis without raw XML overhead):
       pfw_get_patent_or_application_xml(identifier='7971071', include_raw_xml=False)
       → Returns: abstract, claims, description (~5K tokens - 91% reduction vs default!)

    2. Ultra-efficient claims only (claim construction, infringement analysis):
       pfw_get_patent_or_application_xml(identifier='7971071', include_fields=['claims'], include_raw_xml=False)
       → Returns: claims only (~1.5K tokens - 95% reduction!)

    3. Claims + citations without raw XML (prior art analysis):
       pfw_get_patent_or_application_xml(identifier='7971071', include_fields=['claims', 'citations'], include_raw_xml=False)
       → Returns: claims, citations (~2.5K tokens)

    4. Just inventors without raw XML (portfolio analysis):
       pfw_get_patent_or_application_xml(identifier='7971071', include_fields=['inventors'], include_raw_xml=False)
       → Returns: inventors only (~300 tokens - 99% reduction!)

    5. Inventors + applicants without raw XML (entity analysis):
       pfw_get_patent_or_application_xml(identifier='7971071', include_fields=['inventors', 'applicants'], include_raw_xml=False)
       → Returns: inventors, applicants (~500 tokens)

    6. Legacy default (backward compatibility - includes raw XML):
       pfw_get_patent_or_application_xml(identifier='7971071')
       → Returns: abstract, claims, description + raw_xml (~55K tokens total)

    7. Everything with raw XML (debugging or custom XML parsing):
       pfw_get_patent_or_application_xml(
           identifier='7971071',
           include_fields=['abstract', 'claims', 'description', 'inventors', 'applicants', 'classifications', 'citations', 'publication_info']
       )
       → Returns: all fields + raw_xml (~80K tokens)

    **CONTEXT OPTIMIZATION TIPS:**
    - For maximum efficiency: Set include_raw_xml=False (most workflows don't need raw XML)
    - For inventor/applicant reports: Add include_fields=['inventors', 'applicants'] if using minimal search
    - For metadata: Check if already available from prior pfw_search_applications_balanced call
    - For citations: Consider uspto_enriched_citation_mcp for deeper citation analysis with backward/forward citation trees
    - Request only what you need to minimize context

    For field selection guidance and token estimates, use pfw_get_guidance(section='tools')."""
        try:
            api_client = _client()

            result = await api_client.get_patent_or_application_xml(identifier, content_type, include_fields, include_raw_xml)

            # Add patent_number to response so the MCP App widget can show it.
            # For PTGRXML: if the user passed a patent number (identifier != derived app_number),
            # identifier_used IS the patent number.
            if result.get("success"):
                identifier_used = result.get("identifier_used", "")
                application_number = result.get("application_number", "")
                xml_type = result.get("xml_type", "")
                if xml_type == "PTGRXML" and identifier_used and identifier_used != application_number:
                    result["patent_number"] = identifier_used
                else:
                    result["patent_number"] = ""

                # Provenance labeling + detection-only injection scan of the
                # structured content (abstract/claims/description). Kind
                # labels only, text served verbatim; `injection_scan` is
                # ABSENT when clean. See shared/injection_scan.py.
                result["provenance_note"] = RETRIEVED_TEXT_NOTE
                joined = " ".join(_iter_strings(result.get("structured_content")))
                kinds = scan_text(joined)
                if kinds:
                    result["injection_scan"] = {
                        "flagged": [{
                            "application_number": result.get("application_number", ""),
                            "identifier_used": identifier_used or identifier,
                            "kinds": kinds,
                        }],
                        "note": _WARNING_NOTE,
                    }

            return result

        except Exception as e:
            return format_error_response(f"Failed to get XML content: {str(e)}")


    @mcp.tool(name="get_granted_patent_documents_download", app=AppConfig(resourceUri=_DOWNLOADS_URI), annotations={"defer_loading": True, "readOnlyHint": True})
    @mcp_error_handler
    # NOTE (audit F33): this tool's flag is generate_persistent_links (plural —
    # one per patent component) while pfw_get_document_download uses the singular
    # generate_persistent_link. Both are deployed parameter names; do not rename.
    async def pfw_get_granted_patent_documents_download(
        app_number: str,
        include_drawings: bool = True,
        include_original_claims: bool = False,
        direction_category: Optional[str] = "INCOMING",
        proxy_port: Optional[int] = None,
        generate_persistent_links: bool = True
    ) -> Dict[str, Any]:
        """Get complete granted patent package (Abstract, Drawings, Specification, Claims) in one call.

        Perfect for: Due diligence, portfolio review, litigation preparation, or whenever an attorney
        needs the complete granted patent. Returns all 4 components with organized download links.

        ✅ ENHANCED PROXY INTEGRATION: This tool provides immediate download access!
        - Always-on proxy: Links work immediately (if ENABLE_ALWAYS_ON_PROXY=true)
        - On-demand proxy: Automatic startup when needed
        - Persistent links: Enabled by default - 7-day encrypted access (set generate_persistent_links=false to disable)
        - Download links are immediately clickable after tool execution and remain valid for 7 days

        📋 RESPONSE FORMAT: Each component includes BOTH clickable link AND raw URL:
        **📁 [Download {Component} ({Pages} pages)]({url})** | Raw URL: `{url}`
        - Clickable links work in Claude Desktop and most clients
        - Raw URLs enable copy/paste in Msty and other clients where links aren't clickable

        Args:
            app_number: Patent application number (required)
            include_drawings: Include drawings in response (default: True, set False to skip)
            include_original_claims: Get originally-filed claims vs. granted claims (default: False = granted)
            proxy_port: Proxy server port (default: 8080)

        Common scenarios:
        - "Get me the granted patent for application 14171705"
        - "I need the complete patent package for portfolio review"
        - "Download all components of the granted patent"

        Returns structured response with all components and download links. Use pfw_get_application_documents
        for selective filtering in complex prosecutions with 200+ documents.

        For complex workflows, see pfw_get_guidance (quick reference chart available).
        """
        try:
            api_client = _client()

            proxy_port = _resolve_proxy_port(proxy_port)

            # Validate app_number using the existing validation function
            app_number = validate_app_number(app_number)

            # Start proxy server if not already running
            await _ensure_proxy_server_running(proxy_port)

            result = await api_client.get_granted_patent_documents_download(
                app_number=app_number,
                include_drawings=include_drawings,
                include_original_claims=include_original_claims,
                direction_category=direction_category
            )

            # Upgrade proxy URLs to persistent encrypted links if requested
            proxy_base = os.getenv("PFW_PROXY_BASE_URL", f"http://localhost:{proxy_port}")
            if generate_persistent_links and result.get("success"):
                try:
                    from ..proxy.secure_link_cache import get_link_cache
                    link_cache = get_link_cache()
                    for comp_data in result.get("granted_patent_components", {}).values():
                        doc_id = comp_data.get("document_identifier")
                        if doc_id:
                            comp_data["proxy_download_url"] = link_cache.generate_persistent_link(
                                app_number, doc_id, proxy_base
                            )
                except Exception as link_err:
                    logger.debug(f"Could not generate persistent links for granted package: {link_err}")

            # Register each component in recent downloads store for MCP App panel (via proxy endpoint)
            if result.get("success"):
                component_titles = {
                    "abstract": "Abstract",
                    "drawings": "Drawings",
                    "specification": "Specification",
                    "claims": "Claims (Granted)" if not include_original_claims else "Claims (Original)",
                }
                for comp_name, comp_data in result.get("granted_patent_components", {}).items():
                    await _register_download_via_proxy(
                        port=proxy_port,
                        title=f"{component_titles.get(comp_name, comp_name.title())} — App {app_number}",
                        doc_type=comp_name,
                        app_number=app_number,
                        proxy_url=comp_data.get("proxy_download_url", ""),
                        filename=f"{app_number}_{comp_name}.pdf",
                    )

            return result

        except ValueError as ve:
            return format_error_response(str(ve), 400)
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "guidance": "Use pfw_search_applications_balanced to verify application number exists"
            }

    # REMOVED: pfw_get_tool_reflections - migrated to pfw_get_guidance for context efficiency
    # The comprehensive tool reflection functionality has been migrated to sectioned guidance
    # Use pfw_get_guidance(section='tools') for tool-specific guidance
    # Use pfw_get_guidance(section='overview') to see all available sections

