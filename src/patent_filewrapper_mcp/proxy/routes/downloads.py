"""Download routes for the PFW proxy: PFW/FPD/PTAB document streaming and
persistent links. Carved out of the create_proxy_app() closure (audit F4 /
metrics 7/10): module-level handlers on an APIRouter, unit-testable without
building the whole app.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask
import httpx

from ...api.helpers import validate_app_number, generate_request_id
from ...shared.safe_logger import get_safe_logger
from ...util.security_logger import security_logger
from ..fpd_document_store import get_fpd_store
from ..ptab_document_store import get_ptab_store
from ..rate_limiter import rate_limiter
from ..models import _validate_uspto_download_url

from .. import server as _server
from ..server import (
    _check_proxy_token,
    _open_upstream_pdf_stream,
    _safe_filename,
    _safe_header_value,
)

logger = get_safe_logger(__name__)

router = APIRouter()


def _live_uspto_api_key():
    """PFW's own USPTO API key, read at download time.

    Registration rows used to carry an encrypted copy of the key; they no
    longer do, so the download path resolves it the same way registration
    does: secure store first, USPTO_API_KEY second.
    """
    import os

    try:
        from ...shared_secure_storage import get_uspto_api_key
        key = get_uspto_api_key()
    except Exception as e:
        logger.warning(
            f"Secure storage unavailable ({type(e).__name__}); "
            "falling back to USPTO_API_KEY"
        )
        key = None
    return key or os.getenv("USPTO_API_KEY")


async def _stream_registered_document(
    source: str,
    primary_id: str,
    document_identifier: str,
    client_ip: str,
    request_id: str,
    doc_metadata,
    fallback_filename: str,
    upstream_headers: dict,
    response_headers_extra: dict,
):
    """Shared FPD/PTAB registered-document streaming core (audit F6: the two
    per-source helpers were ~85-90% identical and had already drifted).

    Also fixes a latent PTAB-path bug: its own 404/502 HTTPExceptions fell
    through to the generic handler and became 500s.
    """
    endpoint = f"/download/{primary_id}/{document_identifier}"
    try:
        if not doc_metadata:
            logger.warning(f"[{request_id}] {source} document not found: {primary_id}/{document_identifier}")
            security_logger.log_validation_error(
                endpoint, client_ip, f"{source.lower()}_document_not_found",
                f"Document not registered: {primary_id}/{document_identifier}", request_id,
            )
            raise HTTPException(
                status_code=404,
                detail=f"{source} document not found. Document may not be registered or may have expired."
            )

        download_url = doc_metadata['download_url']
        # Defense in depth (audit H2): re-validate the stored URL before
        # attaching the real USPTO API key to an outbound fetch
        try:
            _validate_uspto_download_url(download_url)
        except ValueError:
            logger.error(f"[{request_id}] Stored {source} download_url failed host validation")
            raise HTTPException(status_code=502, detail="Stored download URL is not a uspto.gov endpoint")

        # The key is resolved LIVE, not read out of the registration row: a
        # long-lived copy of the fleet's shared ODP credential does not belong
        # in a SQLite file that outlives the download it was registered for.
        api_key = _live_uspto_api_key()
        if not api_key:
            logger.error(f"[{request_id}] No USPTO API key available for {source} download")
            raise HTTPException(
                status_code=500,
                detail="Configuration error: No USPTO API key available"
            )
        enhanced_filename = doc_metadata.get('enhanced_filename')
        filename = enhanced_filename or fallback_filename
        logger.info(f"[{request_id}] Streaming {source} document: {primary_id}/{document_identifier} as {filename}")

        # Stream the PDF from USPTO API using stored credentials
        # (magic-byte verified before response headers go out — audit M4)
        pdf_stream = await _open_upstream_pdf_stream(
            download_url, {"X-Api-Key": api_key, **upstream_headers}, request_id, source
        )

        security_logger.log_download_access(primary_id, document_identifier, client_ip, True, request_id)

        safe_filename = _safe_filename(filename)
        headers = {
            "Content-Type": "application/pdf",
            "Content-Disposition": f'attachment; filename="{safe_filename}"',
            "X-Document-Source": source,
            "X-Document-Identifier": document_identifier,
            "X-Request-ID": request_id,
            **response_headers_extra,
        }
        if enhanced_filename:
            headers["X-Enhanced-Filename"] = _safe_header_value(enhanced_filename)

        return StreamingResponse(
            pdf_stream,
            media_type="application/pdf",
            headers=headers,
            background=BackgroundTask(
                lambda: logger.info(f"[{request_id}] {source} download completed: {filename}")
            )
        )

    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        security_logger.log_download_access(primary_id, document_identifier, client_ip, False, request_id)
        if e.response.status_code == 403:
            logger.error(
                f"[{request_id}] USPTO API authentication failed for {source} document "
                f"{primary_id}/{document_identifier}"
            )
            security_logger.log_auth_failure(
                endpoint, client_ip, f"USPTO API 403 response for {source} document", request_id
            )
            raise HTTPException(
                status_code=502,
                detail=f"Authentication failed with USPTO API for {source} document"
            )
        # Status only — response bodies stay out of logs
        logger.error(f"[{request_id}] USPTO API error {e.response.status_code} for {source} document")
        raise HTTPException(
            status_code=502,
            detail=f"USPTO API error for {source} document: {e.response.status_code}"
        )
    except Exception:
        security_logger.log_download_access(primary_id, document_identifier, client_ip, False, request_id)
        logger.exception(f"[{request_id}] {source} proxy download failed for {primary_id}/{document_identifier}")
        raise HTTPException(status_code=500, detail=f"{source} download failed")


async def _download_fpd_document(petition_id: str, document_identifier: str, client_ip: str, request_id: str):
    """Stream an FPD petition document registered with the proxy."""
    doc_metadata = get_fpd_store().get_document(petition_id, document_identifier)
    fallback_parts = [petition_id[:8]]
    extra_headers = {"X-Petition-ID": petition_id}
    if doc_metadata and doc_metadata.get('application_number'):
        fallback_parts.append(doc_metadata['application_number'])
        extra_headers["X-Application-Number"] = doc_metadata['application_number']
    fallback_parts.append(document_identifier)
    return await _stream_registered_document(
        "FPD", petition_id, document_identifier, client_ip, request_id,
        doc_metadata,
        fallback_filename="_".join(fallback_parts) + ".pdf",
        upstream_headers={"Accept": "application/pdf"},
        response_headers_extra=extra_headers,
    )


async def _download_ptab_document(proceeding_number: str, document_identifier: str, client_ip: str, request_id: str):
    """Stream a PTAB proceeding document registered with the proxy."""
    doc_metadata = get_ptab_store().get_document(proceeding_number, document_identifier)
    fallback_parts = [proceeding_number]
    if doc_metadata and doc_metadata.get('patent_number'):
        fallback_parts.append(f"PAT-{doc_metadata['patent_number']}")
    fallback_parts.append(document_identifier)
    return await _stream_registered_document(
        "PTAB", proceeding_number, document_identifier, client_ip, request_id,
        doc_metadata,
        fallback_filename="_".join(fallback_parts) + ".pdf",
        upstream_headers={"User-Agent": "USPTO-PFW-MCP/1.0 (PTAB Document Proxy)"},
        response_headers_extra={
            "X-Proceeding-Number": proceeding_number,
            "X-Proceeding-Type": (doc_metadata or {}).get('proceeding_type') or "unknown",
        },
    )



@router.get("/download/{app_number}/{document_identifier}", dependencies=[Depends(_check_proxy_token)])
async def download_document(
    app_number: str,
    document_identifier: str,
    request: Request
):
    """
    Proxy endpoint for downloading USPTO patent documents

    This endpoint handles authentication with the USPTO API and streams
    the PDF content directly to the browser, enabling direct downloads
    while keeping API keys secure.

    Supports PFW application documents, FPD petition documents, and PTAB proceeding documents:
    - PFW: /download/{app_number}/{doc_id}
    - FPD: /download/{petition_id}/{doc_id} (UUID format for petition_id)
    - PTAB: /download/{proceeding_number}/{doc_id} (AIA Trials: IPR2025-00895, Appeals: 2025000950)

    Args:
        app_number: Patent application number (e.g., '17896175'), FPD petition UUID, or PTAB proceeding number
        document_identifier: Document ID from documentBag (e.g., 'L7AJVPB2GREENX5')
        request: FastAPI request object (for client IP)
    """
    client_ip = request.client.host if request.client else "unknown"
    request_id = generate_request_id()

    # Apply rate limiting. Charged HERE only: the persistent-link resolver
    # charges it once itself and then calls _dispatch_download directly, so
    # the advertised 5-per-10s is 5, not 2 (audit M-21).
    if not rate_limiter.is_allowed(client_ip):
        import time
        remaining_time = max(1, int(rate_limiter.get_reset_time(client_ip) - time.time()))

        # Log rate limit violation
        security_logger.log_rate_limit_violation(client_ip, f"/download/{app_number}/{document_identifier}", request_id)

        return JSONResponse(
            status_code=429,
            content={
                "error": True,
                "message": "Rate limit exceeded. USPTO allows 5 downloads per 10 seconds.",
                "retry_after": remaining_time,
                "remaining_requests": 0,
                "request_id": request_id
            },
            headers={"Retry-After": str(int(remaining_time))}
        )

    return await _dispatch_download(
        app_number, document_identifier, request, client_ip, request_id
    )


def _upstream_status(docs_result: dict) -> int:
    """Map a client error envelope onto an HTTP status for the browser.

    get_documents returns the same envelope shape for a USPTO timeout (408),
    an auth failure (401), a circuit-breaker-open 503 and a genuinely unknown
    application. Reporting all four as 404 told a user retrying during a USPTO
    outage that the document does not exist (audit exception-flow F-2).
    """
    try:
        upstream = int(docs_result.get('status_code', 502))
    except (TypeError, ValueError):
        upstream = 502
    if upstream == 404:
        return 404
    if upstream in (429, 503):
        return 503
    return 502


def _select_pdf_option(documents: list, document_identifier: str) -> dict:
    """The document's PDF download option, or the right 404 explaining which
    step failed."""
    target_doc = next(
        (d for d in documents if d.get('documentIdentifier') == document_identifier),
        None,
    )
    if not target_doc:
        raise HTTPException(
            status_code=404,
            detail=f"Document with identifier '{document_identifier}' not found"
        )

    pdf_option = next(
        (o for o in target_doc.get('downloadOptionBag', [])
         if o.get('mimeTypeIdentifier') == 'PDF'),
        None,
    )
    if not pdf_option:
        raise HTTPException(status_code=404, detail="PDF not available for this document")
    if not pdf_option.get('downloadUrl'):
        raise HTTPException(status_code=404, detail="Download URL not available")

    return target_doc, pdf_option


async def _pfw_download_filename(app_number: str, doc_code: str, document_identifier: str) -> str:
    """Title-and-patent-number filename, falling back to the flat form.

    Best effort by design: the metadata lookup is a convenience, so a failure
    degrades the filename rather than the download.
    """
    from ...api.helpers import extract_patent_number, generate_safe_filename

    try:
        search_result = await _server.api_client.search_applications(
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
                if invention_title:
                    return generate_safe_filename(
                        app_number, invention_title, doc_code,
                        extract_patent_number(app_data),
                    )
    except Exception as e:
        logger.warning(f"Could not fetch application metadata for {app_number}: {e}")

    return f"{app_number}_{document_identifier}_{doc_code}.pdf"


async def _dispatch_download(
    app_number: str,
    document_identifier: str,
    request: Request,
    client_ip: str,
    request_id: str,
):
    """Route a download to the PFW, FPD or PTAB path. NOT rate limited: the
    caller owns that, so one request is charged exactly once (audit M-21)."""
    try:
        # Check if this is an FPD document (UUID format)
        fpd_store = get_fpd_store()
        if fpd_store.is_fpd_petition_id(app_number):
            # Handle FPD petition document download
            logger.info(f"Detected FPD document request: petition_id={app_number}, doc_id={document_identifier}")
            return await _download_fpd_document(app_number, document_identifier, client_ip, request_id)

        # Check if this is a PTAB document (proceeding number format)
        ptab_store = get_ptab_store()
        if ptab_store.is_ptab_proceeding_number(app_number):
            # Handle PTAB proceeding document download
            logger.info(f"Detected PTAB document request: proceeding_number={app_number}, doc_id={document_identifier}")
            return await _download_ptab_document(app_number, document_identifier, client_ip, request_id)

        # Handle PFW application document download (existing logic)
        # Validate application number
        try:
            app_number = validate_app_number(app_number)
        except Exception as e:
            # Log validation error
            security_logger.log_validation_error(
                f"/download/{app_number}/{document_identifier}",
                client_ip,
                "invalid_app_number",
                str(e),
                request_id
            )
            raise HTTPException(status_code=400, detail="Invalid application number")

        # Get document metadata and download URL
        logger.info(f"Proxying download for app {app_number}, doc {document_identifier}, IP {client_ip}")

        # Get documents to find the specific document
        docs_result = await _server.api_client.get_documents(app_number)
        if docs_result.get('error'):
            raise HTTPException(
                status_code=_upstream_status(docs_result),
                detail=docs_result.get('message', 'Document unavailable'),
            )

        target_doc, pdf_option = _select_pdf_option(
            docs_result.get('documentBag', []), document_identifier
        )
        download_url = pdf_option['downloadUrl']

        # Get document metadata for response headers
        doc_code = target_doc.get('documentCode', 'UNKNOWN')
        page_count = pdf_option.get('pageTotalQuantity', 0)

        filename = await _pfw_download_filename(
            app_number, doc_code, document_identifier
        )

        # Stream the PDF from USPTO API
        # (magic-byte verified before response headers go out — audit M4)
        pdf_stream = await _open_upstream_pdf_stream(
            download_url, _server.api_client.headers, request_id, "PFW"
        )

        # Set appropriate headers for PDF download
        # Use _safe_filename to guard against any edge-case control chars
        # from generate_safe_filename output being used in the header.
        headers = {
            "Content-Type": "application/pdf",
            "Content-Disposition": f'attachment; filename="{_safe_filename(filename)}"',
            "X-Document-Code": doc_code,
            "X-Page-Count": str(page_count),
            "X-Application-Number": app_number,
            "X-Document-Identifier": document_identifier
        }

        logger.info(f"Streaming PDF: {filename} ({page_count} pages)")

        # Log successful download access
        security_logger.log_download_access(app_number, document_identifier, client_ip, True, request_id)

        return StreamingResponse(
            pdf_stream,
            media_type="application/pdf",
            headers=headers,
            background=BackgroundTask(
                lambda: logger.info(f"Download completed: {filename}")
            )
        )

    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        # Log failed download access
        security_logger.log_download_access(app_number, document_identifier, client_ip, False, request_id)

        if e.response.status_code == 403:
            logger.error(f"USPTO API authentication failed for {app_number}/{document_identifier}")
            security_logger.log_auth_failure(
                f"/download/{app_number}/{document_identifier}",
                client_ip,
                "USPTO API 403 response",
                request_id
            )
            raise HTTPException(status_code=502, detail="Authentication failed with USPTO API")
        else:
            # Status only — response bodies stay out of logs
            logger.error(f"USPTO API error {e.response.status_code}")
            raise HTTPException(status_code=502, detail=f"USPTO API error: {e.response.status_code}")
    except Exception as e:
        # Log failed download access
        security_logger.log_download_access(app_number, document_identifier, client_ip, False, request_id)
        logger.error(f"Proxy download failed for {app_number}/{document_identifier}: {e}")
        raise HTTPException(status_code=500, detail="Download failed")


@router.get("/document/persistent/{link_hash}")
async def download_document_persistent(link_hash: str, request: Request):
    """
    Download document via persistent encrypted link

    This endpoint resolves opaque persistent links and streams the document
    while maintaining security and rate limiting.
    """
    try:
        from ..secure_link_cache import get_link_cache

        # Get client IP for rate limiting
        client_ip = request.client.host if request.client else "unknown"
        request_id = generate_request_id()

        # Apply rate limiting
        if not rate_limiter.is_allowed(client_ip):
            import time
            remaining_time = max(1, int(rate_limiter.get_reset_time(client_ip) - time.time()))

            # Log rate limit violation — truncated hash only (the full
            # hash is the credential, Lesson 43)
            security_logger.log_rate_limit_violation(client_ip, f"/document/persistent/{link_hash[:8]}...", request_id)

            return JSONResponse(
                status_code=429,
                content={
                    "error": True,
                    "message": "Rate limit exceeded. USPTO allows 5 downloads per 10 seconds.",
                    "retry_after": remaining_time,
                    "remaining_requests": 0,
                    "request_id": request_id
                },
                headers={"Retry-After": str(int(remaining_time))}
            )

        # Resolve persistent link
        link_cache = get_link_cache()
        link_info = link_cache.resolve_persistent_link(link_hash)

        if not link_info:
            security_logger.log_validation_error(
                f"/document/persistent/{link_hash[:8]}...",
                client_ip,
                "invalid_persistent_link",
                "Link expired, corrupted, or not found",
                request_id
            )
            raise HTTPException(
                status_code=404,
                detail="Persistent link expired or invalid. Please request a new download link."
            )

        app_number = link_info['app_number']
        document_identifier = link_info['doc_id']

        logger.info(f"Resolving persistent link {link_hash[:8]}... for app {app_number}, doc {document_identifier} (access #{link_info['access_count']})")

        # Continue with standard download logic. _dispatch_download, NOT
        # download_document: the limiter was already charged above, and
        # charging it twice made the advertised 5-per-10s effectively 2 on
        # this path (audit M-21).
        return await _dispatch_download(
            app_number, document_identifier, request, client_ip, request_id
        )

    except HTTPException:
        raise
    except Exception:
        logger.exception(f"Persistent link download failed for {link_hash[:8]}...")
        raise HTTPException(status_code=500, detail="Persistent download failed")


@router.delete(
    "/document/persistent/{link_hash}",
    dependencies=[Depends(_check_proxy_token)],
)
async def revoke_document_persistent(link_hash: str):
    """Revoke a persistent link.

    The GET on this path is deliberately tokenless because browsers cannot
    send X-Proxy-Token on navigation (Lesson 43). Revocation is an operator
    action, not a navigation, so it IS token-gated — otherwise anyone holding
    a leaked hash could also delete it and the audit trail with it.
    """
    from ..secure_link_cache import get_link_cache

    revoked = get_link_cache().revoke_link(link_hash)
    return {
        "success": True,
        "revoked": revoked,
        "link_hash_prefix": f"{link_hash[:8]}...",
    }

