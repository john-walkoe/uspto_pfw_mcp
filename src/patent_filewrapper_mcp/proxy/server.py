"""
FastAPI HTTP server for secure document downloads

Provides browser-accessible download URLs while keeping USPTO API keys secure.
"""
import logging
import os
from typing import Dict, Any, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.background import BackgroundTask
from starlette.middleware.base import BaseHTTPMiddleware
import httpx

from ..api.enhanced_client import EnhancedPatentClient
from ..api.helpers import validate_app_number, format_error_response, generate_request_id
from .rate_limiter import rate_limiter
from ..util.security_logger import security_logger
from .fpd_document_store import get_fpd_store
from .ptab_document_store import get_ptab_store
from .models import FPDDocumentRegistration, FPDDocumentRegistrationResponse, PTABDocumentRegistration, PTABDocumentRegistrationResponse
from ..shared.internal_auth import pfw_auth

logger = logging.getLogger(__name__)

# Request size limit configuration
MAX_REQUEST_SIZE = 1024 * 1024  # 1MB limit


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware to limit request body size for security.

    Prevents DoS attacks via large request bodies.
    """

    def __init__(self, app, max_request_size: int = MAX_REQUEST_SIZE):
        super().__init__(app)
        self.max_request_size = max_request_size

    async def dispatch(self, request: Request, call_next):
        """Check request size and reject if too large"""
        # Get Content-Length header if present
        content_length = request.headers.get('content-length')

        if content_length:
            content_length = int(content_length)
            if content_length > self.max_request_size:
                # Log security event
                client_ip = request.client.host if request.client else "unknown"
                request_id = generate_request_id()

                logger.warning(
                    f"[{request_id}] Request body too large: {content_length} bytes from {client_ip}"
                )
                security_logger.log_validation_error(
                    str(request.url.path),
                    client_ip,
                    "request_body_too_large",
                    f"Content-Length: {content_length} bytes exceeds {self.max_request_size} bytes",
                    request_id
                )

                return JSONResponse(
                    status_code=413,  # Payload Too Large
                    content={
                        "error": True,
                        "message": f"Request body too large. Maximum size: {self.max_request_size} bytes",
                        "content_length": content_length,
                        "max_allowed": self.max_request_size,
                        "request_id": request_id
                    }
                )

        return await call_next(request)

# Global client instance
api_client = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan"""
    global api_client
    try:
        api_client = EnhancedPatentClient()
        logger.info("USPTO API client initialized for proxy server")
        yield
    except Exception as e:
        logger.error(f"Failed to initialize USPTO API client: {e}")
        raise

def create_proxy_app() -> FastAPI:
    """Create FastAPI application for document proxy"""
    app = FastAPI(
        title="USPTO Document Proxy",
        description="Secure proxy for USPTO patent document downloads",
        version="1.0.0",
        lifespan=lifespan
    )

    # Add request size limit middleware
    app.add_middleware(RequestSizeLimitMiddleware, max_request_size=MAX_REQUEST_SIZE)

    # Add CORS middleware with localhost-only restrictions
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:*", "http://127.0.0.1:*"],  # Restrict to localhost only
        allow_credentials=False,
        allow_methods=["GET", "POST"],  # Allow GET for downloads, POST for FPD registration
        allow_headers=["Accept", "User-Agent", "Content-Type"],
    )

    # Add IP whitelist middleware for additional security
    @app.middleware("http")
    async def add_ip_access_control(request: Request, call_next):
        """Restrict access to localhost IPs only"""
        client_ip = request.client.host if request.client else "unknown"
        allowed_ips = ["127.0.0.1", "::1"]  # IPv4 and IPv6 localhost

        if client_ip not in allowed_ips:
            request_id = generate_request_id()
            logger.warning(f"[{request_id}] Access denied from IP: {client_ip}")
            security_logger.log_auth_failure(
                str(request.url.path),
                client_ip,
                "ip_not_whitelisted",
                f"IP {client_ip} not in allowed list: {allowed_ips}",
                request_id
            )
            return JSONResponse(
                status_code=403,
                content={"error": "Access denied from this IP address"}
            )

        response = await call_next(request)
        return response

    # Add security headers middleware
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        """Add standard security headers to all responses"""
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = "default-src 'none'"
        return response

    # =========================================================================
    # Global Exception Handlers
    # =========================================================================

    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException
    import traceback
    import os

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        """
        Handle HTTP exceptions with consistent error format

        This ensures all HTTP errors (404, 403, etc.) return consistent
        JSON responses with proper logging and request IDs.
        """
        request_id = generate_request_id()
        client_ip = request.client.host if request.client else "unknown"

        logger.warning(
            f"[{request_id}] HTTP {exc.status_code}: {exc.detail} "
            f"(path={request.url.path}, client={client_ip})"
        )

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": True,
                "success": False,
                "status_code": exc.status_code,
                "message": str(exc.detail),
                "request_id": request_id,
                "path": str(request.url.path),
                "timestamp": import_time().strftime('%Y-%m-%dT%H:%M:%SZ', import_time().gmtime())
            }
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """
        Handle request validation errors with actionable guidance

        This catches malformed requests (missing params, wrong types, etc.)
        and returns user-friendly error messages.
        """
        request_id = generate_request_id()
        client_ip = request.client.host if request.client else "unknown"

        logger.warning(
            f"[{request_id}] Validation error: {exc.errors()} "
            f"(path={request.url.path}, client={client_ip})"
        )

        security_logger.log_validation_error(
            str(request.url.path),
            client_ip,
            "request_validation_failed",
            str(exc.errors()),
            request_id
        )

        return JSONResponse(
            status_code=422,
            content={
                "error": True,
                "success": False,
                "status_code": 422,
                "message": "Request validation failed",
                "request_id": request_id,
                "errors": exc.errors(),
                "guidance": "Check request parameters and try again",
                "timestamp": import_time().strftime('%Y-%m-%dT%H:%M:%SZ', import_time().gmtime())
            }
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """
        Handle all unhandled exceptions with environment-aware detail levels

        This is the catch-all handler for any exception that wasn't caught
        by more specific handlers. It provides different detail levels for
        development vs production environments.
        """
        request_id = generate_request_id()
        client_ip = request.client.host if request.client else "unknown"

        logger.exception(
            f"[{request_id}] Unhandled exception: {str(exc)} "
            f"(path={request.url.path}, client={client_ip})"
        )

        # Security log for unexpected errors
        security_logger.log_validation_error(
            str(request.url.path),
            client_ip,
            "unhandled_exception",
            type(exc).__name__,
            request_id
        )

        # Return different detail levels for dev vs production
        is_development = os.getenv("ENVIRONMENT", "production").lower() in ["development", "dev", "local"]

        response_content = {
            "error": True,
            "success": False,
            "status_code": 500,
            "message": "An unexpected error occurred",
            "request_id": request_id,
            "guidance": "Please try again. If the problem persists, contact support with request ID.",
            "timestamp": import_time().strftime('%Y-%m-%dT%H:%M:%SZ', import_time().gmtime())
        }

        if is_development:
            response_content["debug"] = {
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "traceback": traceback.format_exc()
            }

        return JSONResponse(
            status_code=500,
            content=response_content
        )

    def import_time():
        """Import time module to avoid circular imports"""
        import time
        return time

    # =========================================================================
    # Helper Functions
    # =========================================================================

    async def _download_fpd_document(
        petition_id: str,
        document_identifier: str,
        client_ip: str,
        request_id: str
    ):
        """
        Helper function to download FPD petition documents

        Args:
            petition_id: FPD petition UUID
            document_identifier: Document identifier
            client_ip: Client IP for logging
            request_id: Request ID for tracking
        """
        try:
            # Get FPD document store
            fpd_store = get_fpd_store()

            # Retrieve document metadata
            doc_metadata = fpd_store.get_document(petition_id, document_identifier)

            if not doc_metadata:
                security_logger.log_validation_error(
                    f"/download/{petition_id}/{document_identifier}",
                    client_ip,
                    "fpd_document_not_found",
                    "Document not registered in FPD store",
                    request_id
                )
                raise HTTPException(
                    status_code=404,
                    detail=f"FPD document not found. Document may not be registered or may have expired."
                )

            download_url = doc_metadata['download_url']
            api_key = doc_metadata['api_key']
            application_number = doc_metadata.get('application_number')
            enhanced_filename = doc_metadata.get('enhanced_filename')

            logger.info(
                f"[{request_id}] Streaming FPD document: petition_id={petition_id}, "
                f"doc_id={document_identifier}, app_number={application_number}"
            )

            # Use enhanced filename if available, otherwise generate fallback
            if enhanced_filename:
                filename = enhanced_filename
                logger.info(f"[{request_id}] Using enhanced filename: {filename}")
            else:
                # Fallback to generic filename format
                filename_parts = [petition_id[:8]]  # Use first 8 chars of UUID
                if application_number:
                    filename_parts.append(application_number)
                filename_parts.append(document_identifier)
                filename = "_".join(filename_parts) + ".pdf"
                logger.info(f"[{request_id}] Using fallback filename: {filename}")

            # Stream the PDF from USPTO API using stored credentials
            async def stream_pdf():
                headers = {
                    "X-Api-Key": api_key,
                    "Accept": "application/pdf"
                }
                async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                    async with client.stream("GET", download_url, headers=headers) as response:
                        response.raise_for_status()
                        async for chunk in response.aiter_bytes(chunk_size=8192):
                            yield chunk

            # Set appropriate headers for PDF download
            headers = {
                "Content-Type": "application/pdf",
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Document-Source": "FPD",
                "X-Petition-ID": petition_id,
                "X-Document-Identifier": document_identifier
            }

            if application_number:
                headers["X-Application-Number"] = application_number

            if enhanced_filename:
                headers["X-Enhanced-Filename"] = enhanced_filename

            logger.info(f"[{request_id}] Streaming FPD PDF: {filename}")

            # Log successful download access
            security_logger.log_download_access(
                petition_id,
                document_identifier,
                client_ip,
                True,
                request_id
            )

            return StreamingResponse(
                stream_pdf(),
                media_type="application/pdf",
                headers=headers,
                background=BackgroundTask(
                    lambda: logger.info(f"[{request_id}] FPD download completed: {filename}")
                )
            )

        except HTTPException:
            raise
        except httpx.HTTPStatusError as e:
            # Log failed download access
            security_logger.log_download_access(
                petition_id,
                document_identifier,
                client_ip,
                False,
                request_id
            )

            if e.response.status_code == 403:
                logger.error(
                    f"[{request_id}] USPTO API authentication failed for FPD document "
                    f"{petition_id}/{document_identifier}"
                )
                security_logger.log_auth_failure(
                    f"/download/{petition_id}/{document_identifier}",
                    client_ip,
                    "USPTO API 403 response for FPD document",
                    request_id
                )
                raise HTTPException(
                    status_code=502,
                    detail="Authentication failed with USPTO API for FPD document"
                )
            else:
                logger.error(
                    f"[{request_id}] USPTO API error {e.response.status_code} for FPD document: "
                    f"{e.response.text}"
                )
                raise HTTPException(
                    status_code=502,
                    detail=f"USPTO API error for FPD document: {e.response.status_code}"
                )
        except Exception as e:
            # Log failed download access
            security_logger.log_download_access(
                petition_id,
                document_identifier,
                client_ip,
                False,
                request_id
            )
            logger.error(
                f"[{request_id}] FPD proxy download failed for {petition_id}/{document_identifier}: {e}"
            )
            raise HTTPException(
                status_code=500,
                detail=f"FPD download failed: {str(e)}"
            )

    async def _download_ptab_document(
        proceeding_number: str,
        document_identifier: str,
        client_ip: str,
        request_id: str
    ):
        """
        Helper function to download PTAB proceeding documents

        Args:
            proceeding_number: PTAB proceeding number (e.g., 'IPR2024-00123')
            document_identifier: Document identifier
            client_ip: Client IP for logging
            request_id: Request ID for tracking
        """
        try:
            # Get PTAB document store
            ptab_store = get_ptab_store()

            # Retrieve document metadata
            doc_metadata = ptab_store.get_document(proceeding_number, document_identifier)

            if not doc_metadata:
                logger.warning(f"[{request_id}] PTAB document not found: {proceeding_number}/{document_identifier}")
                security_logger.log_validation_error(
                    f"/download/{proceeding_number}/{document_identifier}",
                    client_ip,
                    "ptab_document_not_found",
                    f"Document not registered: {proceeding_number}/{document_identifier}",
                    request_id
                )
                raise HTTPException(
                    status_code=404,
                    detail="PTAB document not found. Document may not be registered or may have expired."
                )

            # Extract metadata
            download_url = doc_metadata['download_url']
            api_key = doc_metadata['api_key']
            patent_number = doc_metadata.get('patent_number')
            application_number = doc_metadata.get('application_number')
            proceeding_type = doc_metadata.get('proceeding_type')
            enhanced_filename = doc_metadata.get('enhanced_filename')

            logger.info(
                f"[{request_id}] Streaming PTAB document: {proceeding_number}/{document_identifier}, "
                f"patent={patent_number}, type={proceeding_type}"
            )

            # Generate filename for download
            if enhanced_filename:
                filename = enhanced_filename
                logger.info(f"[{request_id}] Using enhanced filename: {filename}")
            else:
                # Fallback to generic filename format
                filename_parts = [proceeding_number]
                if patent_number:
                    filename_parts.append(f"PAT-{patent_number}")
                filename_parts.append(document_identifier)
                filename = "_".join(filename_parts) + ".pdf"
                logger.info(f"[{request_id}] Using fallback filename: {filename}")

            # Stream the PDF from USPTO API using stored credentials
            async def stream_pdf():
                headers = {
                    "X-Api-Key": api_key,
                    "User-Agent": "USPTO-PFW-MCP/1.0 (PTAB Document Proxy)"
                }

                async with httpx.AsyncClient() as client:
                    async with client.stream("GET", download_url, headers=headers) as response:
                        response.raise_for_status()
                        async for chunk in response.aiter_bytes():
                            yield chunk

            # Log successful download access
            security_logger.log_download_access(
                proceeding_number,
                document_identifier,
                client_ip,
                True,
                request_id
            )

            # Return streaming response with enhanced filename
            return StreamingResponse(
                stream_pdf(),
                media_type="application/pdf",
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"',
                    "X-Enhanced-Filename": filename,
                    "X-Document-Source": "PTAB",
                    "X-Proceeding-Number": proceeding_number,
                    "X-Proceeding-Type": proceeding_type or "unknown",
                    "X-Request-ID": request_id
                }
            )

        except httpx.HTTPStatusError as e:
            # Log failed download access
            security_logger.log_download_access(
                proceeding_number,
                document_identifier,
                client_ip,
                False,
                request_id
            )

            if e.response.status_code == 403:
                logger.error(
                    f"[{request_id}] USPTO API authentication failed for PTAB document "
                    f"{proceeding_number}/{document_identifier}"
                )
                security_logger.log_auth_failure(
                    f"/download/{proceeding_number}/{document_identifier}",
                    client_ip,
                    "USPTO API 403 response for PTAB document",
                    request_id
                )
                raise HTTPException(
                    status_code=502,
                    detail="Authentication failed with USPTO API for PTAB document"
                )
            else:
                logger.error(
                    f"[{request_id}] USPTO API error {e.response.status_code} for PTAB document: "
                    f"{e.response.text}"
                )
                raise HTTPException(
                    status_code=502,
                    detail=f"USPTO API error for PTAB document: {e.response.status_code}"
                )
        except Exception as e:
            # Log failed download access
            security_logger.log_download_access(
                proceeding_number,
                document_identifier,
                client_ip,
                False,
                request_id
            )
            logger.error(
                f"[{request_id}] PTAB proxy download failed for {proceeding_number}/{document_identifier}: {e}"
            )
            raise HTTPException(
                status_code=500,
                detail=f"PTAB download failed: {str(e)}"
            )

    @app.get("/")
    async def health_check():
        """
        Enhanced health check endpoint with component status

        Returns health status of all system components including:
        - Circuit breaker state
        - Database connectivity
        - Response cache statistics
        - Retry budget tracking
        """
        import time
        health_data = {
            "service": "USPTO Document Proxy",
            "timestamp": time.time(),
            "components": {}
        }

        overall_healthy = True

        # Circuit breaker health
        if api_client:
            cb_state = api_client.circuit_breaker.state.value
            cb_failures = api_client.circuit_breaker.failure_count

            health_data["components"]["circuit_breaker"] = {
                "status": "healthy" if cb_state == "closed" else "degraded" if cb_state == "half_open" else "unhealthy",
                "state": cb_state,
                "failure_count": cb_failures,
                "threshold": api_client.circuit_breaker.failure_threshold
            }

            if cb_state == "open":
                overall_healthy = False

            # Response cache statistics
            cache_stats = api_client.response_cache.get_stats()
            health_data["components"]["response_cache"] = {
                "status": "healthy",
                "size": cache_stats["size"],
                "max_size": cache_stats["max_size"],
                "utilization": f"{(cache_stats['size'] / cache_stats['max_size'] * 100):.1f}%"
            }

            # Retry budget statistics
            budget_stats = api_client.retry_budget.get_stats()
            budget_utilization = budget_stats["utilization_percent"]
            health_data["components"]["retry_budget"] = {
                "status": "healthy" if budget_utilization < 80 else "degraded" if budget_utilization < 95 else "unhealthy",
                "retries_used": budget_stats["retries_used"],
                "retries_remaining": budget_stats["retries_remaining"],
                "max_retries_per_hour": budget_stats["max_retries_per_hour"],
                "utilization": f"{budget_utilization:.1f}%"
            }

            # Mark overall health as degraded if retry budget is nearly exhausted
            if budget_utilization >= 95:
                overall_healthy = False
        else:
            health_data["components"]["api_client"] = {"status": "unhealthy", "reason": "Not initialized"}
            overall_healthy = False

        # Database health check
        try:
            from ..util.database import create_secure_connection
            import os
            import tempfile

            # Test database connectivity with temporary database
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_db:
                tmp_db_path = tmp_db.name

            try:
                conn = create_secure_connection(tmp_db_path, timeout=5.0)
                conn.execute("SELECT 1").fetchone()
                conn.close()
                os.unlink(tmp_db_path)

                health_data["components"]["database"] = {
                    "status": "healthy",
                    "message": "SQLite connectivity verified"
                }
            except Exception as db_error:
                health_data["components"]["database"] = {
                    "status": "unhealthy",
                    "error": str(db_error)
                }
                overall_healthy = False
                # Clean up temp file if exists
                if os.path.exists(tmp_db_path):
                    os.unlink(tmp_db_path)

        except Exception as e:
            health_data["components"]["database"] = {
                "status": "unknown",
                "error": f"Health check failed: {str(e)}"
            }

        # Set overall status
        health_data["status"] = "healthy" if overall_healthy else "degraded"

        # Return appropriate HTTP status code
        status_code = 200 if overall_healthy else 503

        return JSONResponse(content=health_data, status_code=status_code)

    @app.get("/download/{app_number}/{document_identifier}")
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
        try:
            # Get client IP for rate limiting
            client_ip = request.client.host if request.client else "unknown"
            request_id = generate_request_id()

            # Apply rate limiting
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
                raise HTTPException(status_code=400, detail=f"Invalid application number: {e}")

            # Get document metadata and download URL
            logger.info(f"Proxying download for app {app_number}, doc {document_identifier}, IP {client_ip}")

            # Get documents to find the specific document
            docs_result = await api_client.get_documents(app_number)
            if docs_result.get('error'):
                raise HTTPException(status_code=404, detail=docs_result.get('message', 'Document not found'))

            documents = docs_result.get('documentBag', [])

            # Find the target document
            target_doc = None
            for doc in documents:
                if doc.get('documentIdentifier') == document_identifier:
                    target_doc = doc
                    break

            if not target_doc:
                raise HTTPException(
                    status_code=404,
                    detail=f"Document with identifier '{document_identifier}' not found"
                )

            # Find PDF download option
            download_options = target_doc.get('downloadOptionBag', [])
            pdf_option = None

            for option in download_options:
                if option.get('mimeTypeIdentifier') == 'PDF':
                    pdf_option = option
                    break

            if not pdf_option:
                raise HTTPException(status_code=404, detail="PDF not available for this document")

            download_url = pdf_option.get('downloadUrl')
            if not download_url:
                raise HTTPException(status_code=404, detail="Download URL not available")

            # Get document metadata for response headers
            doc_code = target_doc.get('documentCode', 'UNKNOWN')
            page_count = pdf_option.get('pageTotalQuantity', 0)

            # Get invention title and patent number for better filename
            invention_title = None
            patent_number = None
            try:
                # Search for the application to get the title and patent number info
                search_result = await api_client.search_applications(
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
                        from ..api.helpers import extract_patent_number
                        patent_number = extract_patent_number(app_data)
            except Exception as e:
                logger.warning(f"Could not fetch application metadata for {app_number}: {e}")

            # Generate filename using invention title and patent number if available
            if invention_title:
                from ..api.helpers import generate_safe_filename
                filename = generate_safe_filename(app_number, invention_title, doc_code, patent_number)
            else:
                # Fallback to old format if no title available
                filename = f"{app_number}_{document_identifier}_{doc_code}.pdf"

            # Stream the PDF from USPTO API
            async def stream_pdf():
                async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                    async with client.stream("GET", download_url, headers=api_client.headers) as response:
                        response.raise_for_status()
                        async for chunk in response.aiter_bytes(chunk_size=8192):
                            yield chunk

            # Set appropriate headers for PDF download
            headers = {
                "Content-Type": "application/pdf",
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Document-Code": doc_code,
                "X-Page-Count": str(page_count),
                "X-Application-Number": app_number,
                "X-Document-Identifier": document_identifier
            }

            logger.info(f"Streaming PDF: {filename} ({page_count} pages)")

            # Log successful download access
            security_logger.log_download_access(app_number, document_identifier, client_ip, True, request_id)

            return StreamingResponse(
                stream_pdf(),
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
                # Sanitize and truncate error response for logging
                sanitized_text = e.response.text[:500] + "..." if len(e.response.text) > 500 else e.response.text
                logger.error(f"USPTO API error {e.response.status_code}: {sanitized_text}")
                raise HTTPException(status_code=502, detail=f"USPTO API error: {e.response.status_code}")
        except Exception as e:
            # Log failed download access
            security_logger.log_download_access(app_number, document_identifier, client_ip, False, request_id)
            logger.error(f"Proxy download failed for {app_number}/{document_identifier}: {e}")
            raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")

    @app.get("/document/persistent/{link_hash}")
    async def download_document_persistent(link_hash: str, request: Request):
        """
        Download document via persistent encrypted link

        This endpoint resolves opaque persistent links and streams the document
        while maintaining security and rate limiting.
        """
        try:
            from .secure_link_cache import get_link_cache

            # Get client IP for rate limiting
            client_ip = request.client.host if request.client else "unknown"
            request_id = generate_request_id()

            # Apply rate limiting
            if not rate_limiter.is_allowed(client_ip):
                import time
                remaining_time = max(1, int(rate_limiter.get_reset_time(client_ip) - time.time()))

                # Log rate limit violation
                security_logger.log_rate_limit_violation(client_ip, f"/document/persistent/{link_hash}", request_id)

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
                    f"/document/persistent/{link_hash}",
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

            logger.info(f"Resolving persistent link {link_hash} for app {app_number}, doc {document_identifier} (access #{link_info['access_count']})")

            # Continue with standard download logic
            return await download_document(app_number, document_identifier, request)

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Persistent link download failed for {link_hash}: {e}")
            raise HTTPException(status_code=500, detail=f"Persistent download failed: {str(e)}")

    @app.get("/cache/stats")
    async def get_cache_stats():
        """Get persistent link cache statistics for monitoring"""
        try:
            from .secure_link_cache import get_link_cache
            link_cache = get_link_cache()
            return link_cache.get_cache_stats()
        except Exception as e:
            logger.error(f"Error getting cache stats: {e}")
            return {"error": str(e)}

    @app.post("/cache/cleanup")
    async def cleanup_expired_links():
        """Clean up expired persistent links"""
        try:
            from .secure_link_cache import get_link_cache
            link_cache = get_link_cache()
            deleted_count = link_cache.cleanup_expired_links()
            return {
                "success": True,
                "deleted_links": deleted_count,
                "message": f"Cleaned up {deleted_count} expired links"
            }
        except Exception as e:
            logger.error(f"Error during cache cleanup: {e}")
            return {"error": str(e)}

    @app.get("/reflections")
    async def list_reflections(mcp_type: Optional[str] = None, tags: Optional[str] = None):
        """
        List available reflection resources for MCP Resources capability

        Query Parameters:
            mcp_type: Filter by MCP type (pfw, fpd, ptab)
            tags: Comma-separated list of tags to filter by
        """
        try:
            from ..reflections.reflection_manager import get_reflection_manager

            # Parse tags parameter
            tag_list = None
            if tags:
                tag_list = [tag.strip() for tag in tags.split(',') if tag.strip()]

            reflection_manager = get_reflection_manager()
            resources = reflection_manager.list_resources(mcp_type=mcp_type, tags=tag_list)

            return {
                "success": True,
                "resources": resources,
                "count": len(resources),
                "filters": {
                    "mcp_type": mcp_type,
                    "tags": tag_list
                }
            }

        except Exception as e:
            logger.error(f"Error listing reflections: {e}")
            return {"success": False, "error": str(e)}

    @app.get("/reflections/{mcp_type}/{resource_name}")
    async def get_reflection_resource(mcp_type: str, resource_name: str, format: str = "markdown"):
        """
        Get specific reflection resource content

        Path Parameters:
            mcp_type: MCP type (pfw, fpd, ptab)
            resource_name: Resource name identifier

        Query Parameters:
            format: Response format (markdown, json, summary)
        """
        try:
            from ..reflections.reflection_manager import get_reflection_manager

            resource_path = f"/reflections/{mcp_type}/{resource_name}"
            reflection_manager = get_reflection_manager()

            if format == "summary":
                # Get resource metadata and summary
                resources = reflection_manager.list_resources(mcp_type=mcp_type)
                matching_resource = None
                for resource in resources:
                    if resource['uri'] == resource_path:
                        matching_resource = resource
                        break

                if not matching_resource:
                    raise HTTPException(status_code=404, detail="Resource not found")

                reflection = reflection_manager.get_reflection_by_name(resource_name)
                if reflection:
                    return {
                        "success": True,
                        "resource": matching_resource,
                        "summary": reflection.get_summary(),
                        "format": "summary"
                    }

            elif format == "json":
                # Get resource as JSON metadata
                reflection = reflection_manager.get_reflection_by_name(resource_name)
                if reflection:
                    return {
                        "success": True,
                        "metadata": reflection.get_metadata(),
                        "content_available": True,
                        "format": "json"
                    }

            else:
                # Get full content as markdown (default)
                content = reflection_manager.get_resource(resource_path)
                if content:
                    return Response(
                        content=content,
                        media_type="text/markdown",
                        headers={
                            "Content-Type": "text/markdown; charset=utf-8",
                            "X-Resource-Type": "USPTO-MCP-Reflection",
                            "X-MCP-Type": mcp_type,
                            "X-Resource-Name": resource_name
                        }
                    )

            raise HTTPException(status_code=404, detail="Resource not found")

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting reflection resource {resource_path}: {e}")
            raise HTTPException(status_code=500, detail=f"Resource access failed: {str(e)}")

    @app.get("/reflections/stats")
    async def get_reflection_stats():
        """Get reflection statistics for monitoring"""
        try:
            from ..reflections.reflection_manager import get_reflection_manager

            reflection_manager = get_reflection_manager()
            stats = reflection_manager.get_statistics()

            return {
                "success": True,
                "stats": stats,
                "endpoints": {
                    "list_resources": "/reflections",
                    "get_resource": "/reflections/{mcp_type}/{resource_name}",
                    "statistics": "/reflections/stats"
                }
            }

        except Exception as e:
            logger.error(f"Error getting reflection stats: {e}")
            return {"success": False, "error": str(e)}

    @app.get("/rate-limit/{client_ip}")
    async def check_rate_limit(client_ip: str):
        """Check rate limit status for a client IP"""
        return {
            "client_ip": client_ip,
            "remaining_requests": rate_limiter.get_remaining_requests(client_ip),
            "max_requests": rate_limiter.max_requests,
            "time_window": rate_limiter.time_window,
            "reset_time": rate_limiter.get_reset_time(client_ip)
        }

    @app.post("/register-fpd-document", response_model=FPDDocumentRegistrationResponse)
    async def register_fpd_document(registration: FPDDocumentRegistration, request: Request):
        """
        Register FPD petition document for centralized proxy downloads

        This endpoint allows FPD MCP to register documents with the PFW centralized
        proxy, enabling unified download experience across USPTO MCPs.

        Args:
            registration: FPD document registration payload
            request: FastAPI request object (for client IP logging)
        """
        import os  # Import at function scope to ensure availability

        try:
            # Get client IP for logging
            client_ip = request.client.host if request.client else "unknown"
            request_id = generate_request_id()

            logger.info(
                f"[{request_id}] FPD document registration request from {client_ip}: "
                f"petition_id={registration.petition_id}, doc_id={registration.document_identifier}"
            )

            # Validate the access token from FPD MCP
            is_valid, token_payload = pfw_auth.validate_incoming_token(registration.access_token)

            if not is_valid:
                logger.warning(f"[{request_id}] Invalid access token from FPD MCP")
                raise HTTPException(
                    status_code=401,
                    detail="Invalid or expired access token"
                )

            # Verify token is for document access and contains expected metadata
            metadata = token_payload.get("metadata", {})
            if metadata.get("type") != "document_access":
                logger.warning(f"[{request_id}] Token not for document access: {metadata.get('type')}")
                raise HTTPException(
                    status_code=401,
                    detail="Invalid token type"
                )

            # Verify token metadata matches request
            token_petition_id = metadata.get("petition_id")
            token_doc_id = metadata.get("document_identifier")

            if (token_petition_id != registration.petition_id or
                token_doc_id != registration.document_identifier):
                logger.warning(
                    f"[{request_id}] Token metadata mismatch: "
                    f"token({token_petition_id}/{token_doc_id}) != request({registration.petition_id}/{registration.document_identifier})"
                )
                raise HTTPException(
                    status_code=401,
                    detail="Token metadata does not match request"
                )

            logger.info(f"[{request_id}] Access token validated successfully for FPD document")

            # Get PFW's own secure USPTO API key (don't use the one from FPD)
            try:
                from ..shared_secure_storage import get_uspto_api_key
                pfw_uspto_api_key = get_uspto_api_key()
                if not pfw_uspto_api_key:
                    # Fall back to environment variable
                    pfw_uspto_api_key = os.getenv("USPTO_API_KEY")

                if not pfw_uspto_api_key:
                    logger.error(f"[{request_id}] No USPTO API key available in PFW")
                    raise HTTPException(
                        status_code=500,
                        detail="Configuration error: No USPTO API key available"
                    )

                logger.info(f"[{request_id}] Using PFW's secure USPTO API key for document registration")

            except Exception as e:
                logger.error(f"[{request_id}] Failed to get PFW USPTO API key: {e}")
                raise HTTPException(
                    status_code=500,
                    detail="Configuration error: Unable to access secure API key"
                )

            # Get FPD document store
            fpd_store = get_fpd_store()

            # Register the document using PFW's secure API key
            success = fpd_store.register_document(
                petition_id=registration.petition_id,
                document_identifier=registration.document_identifier,
                download_url=registration.download_url,
                api_key=pfw_uspto_api_key,  # Use PFW's secure API key, not the token
                application_number=registration.application_number,
                enhanced_filename=registration.enhanced_filename
            )

            if success:
                # Get the configured proxy port (same logic as other parts of the code)
                proxy_port = int(os.getenv('PFW_PROXY_PORT', os.getenv('PROXY_PORT', '8080')))

                # Generate download URL
                download_url = f"http://localhost:{proxy_port}/download/{registration.petition_id}/{registration.document_identifier}"

                logger.info(
                    f"[{request_id}] Successfully registered FPD document: {registration.petition_id}/{registration.document_identifier}"
                )

                if registration.enhanced_filename:
                    logger.info(f"[{request_id}] Enhanced filename: {registration.enhanced_filename}")

                return FPDDocumentRegistrationResponse(
                    success=True,
                    message="Document registered successfully",
                    petition_id=registration.petition_id,
                    document_identifier=registration.document_identifier,
                    download_url=download_url
                )
            else:
                logger.error(
                    f"[{request_id}] Failed to register FPD document: {registration.petition_id}/{registration.document_identifier}"
                )
                raise HTTPException(
                    status_code=500,
                    detail="Failed to register document in database"
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[{request_id}] Error registering FPD document: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Registration failed: {str(e)}"
            )

    @app.post("/register-ptab-document", response_model=PTABDocumentRegistrationResponse)
    async def register_ptab_document(registration: PTABDocumentRegistration, request: Request):
        """
        Register PTAB proceeding document for centralized proxy downloads

        This endpoint allows future PTAB MCP to register documents with the PFW centralized
        proxy when PTAB moves to USPTO Open Data Portal, enabling unified download
        experience across USPTO MCPs.

        Args:
            registration: PTAB document registration payload
            request: FastAPI request object (for client IP logging)
        """
        try:
            # Get client IP for logging
            client_ip = request.client.host if request.client else "unknown"
            request_id = generate_request_id()

            logger.info(
                f"[{request_id}] PTAB document registration request from {client_ip}: "
                f"proceeding={registration.proceeding_number}, doc_id={registration.document_identifier}, "
                f"type={registration.proceeding_type}"
            )

            # Validate the access token from PTAB MCP
            is_valid, token_payload = pfw_auth.validate_incoming_token(registration.access_token)

            if not is_valid:
                logger.warning(f"[{request_id}] Invalid access token from PTAB MCP")
                raise HTTPException(
                    status_code=401,
                    detail="Invalid or expired access token"
                )

            logger.info(f"[{request_id}] Access token validated successfully for PTAB document")

            # Get PFW's own secure USPTO API key
            try:
                from ..shared_secure_storage import get_uspto_api_key
                pfw_uspto_api_key = get_uspto_api_key()
                if not pfw_uspto_api_key:
                    # Fall back to environment variable
                    pfw_uspto_api_key = os.getenv("USPTO_API_KEY")

                if not pfw_uspto_api_key:
                    logger.error(f"[{request_id}] No USPTO API key available in PFW")
                    raise HTTPException(
                        status_code=500,
                        detail="Configuration error: No USPTO API key available"
                    )

            except Exception as e:
                logger.error(f"[{request_id}] Failed to get PFW USPTO API key: {e}")
                raise HTTPException(
                    status_code=500,
                    detail="Configuration error: Unable to access secure API key"
                )

            # Get PTAB document store
            ptab_store = get_ptab_store()

            # Register the document using PFW's secure API key
            success = ptab_store.register_document(
                proceeding_number=registration.proceeding_number,
                document_identifier=registration.document_identifier,
                download_url=registration.download_url,
                api_key=pfw_uspto_api_key,  # Use PFW's secure API key, not the token
                patent_number=registration.patent_number,
                application_number=registration.application_number,
                proceeding_type=registration.proceeding_type,
                document_type=registration.document_type,
                enhanced_filename=registration.enhanced_filename
            )

            if success:
                # Get the configured proxy port (same logic as other parts of the code)
                proxy_port = int(os.getenv('PFW_PROXY_PORT', os.getenv('PROXY_PORT', '8080')))

                # Generate download URL
                download_url = f"http://localhost:{proxy_port}/download/{registration.proceeding_number}/{registration.document_identifier}"

                logger.info(
                    f"[{request_id}] Successfully registered PTAB document: {registration.proceeding_number}/{registration.document_identifier}"
                )

                if registration.enhanced_filename:
                    logger.info(f"[{request_id}] Enhanced filename: {registration.enhanced_filename}")

                return PTABDocumentRegistrationResponse(
                    success=True,
                    message="Document registered successfully",
                    proceeding_number=registration.proceeding_number,
                    document_identifier=registration.document_identifier,
                    download_url=download_url
                )
            else:
                logger.error(
                    f"[{request_id}] Failed to register PTAB document: {registration.proceeding_number}/{registration.document_identifier}"
                )
                raise HTTPException(
                    status_code=500,
                    detail="Failed to register document in database"
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[{request_id}] Error registering PTAB document: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Registration failed: {str(e)}"
            )

    @app.get("/ptab-stats")
    async def get_ptab_stats():
        """Get PTAB document store statistics for monitoring"""
        try:
            ptab_store = get_ptab_store()
            return ptab_store.get_statistics()
        except Exception as e:
            logger.error(f"Error getting PTAB stats: {e}")
            return {"error": str(e)}

    @app.get("/fpd-stats")
    async def get_fpd_stats():
        """Get FPD document store statistics for monitoring"""
        try:
            fpd_store = get_fpd_store()
            return fpd_store.get_statistics()
        except Exception as e:
            logger.error(f"Error getting FPD stats: {e}")
            return {"error": str(e)}

    @app.get("/doc-codes")
    async def get_doc_codes():
        """
        Serve USPTO Document Code Decoder Table

        This endpoint provides a formatted markdown table of USPTO document codes
        for patent prosecution, PTAB proceedings, and FPD petitions.

        Source: https://www.uspto.gov/patents/apply/filing-online/efs-info-document-description
        """
        try:
            import csv
            import os

            # Find the CSV file relative to project root
            # Get project root (go up from src/patent_filewrapper_mcp/proxy/)
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.join(current_dir, "..", "..", "..")
            csv_path = os.path.join(project_root, "reference", "Document_Descriptions_List.csv")

            if not os.path.exists(csv_path):
                raise FileNotFoundError(f"Document_Descriptions_List.csv not found at {csv_path}")

            # Parse CSV and format as markdown
            output = []
            output.append("# USPTO Document Code Decoder Table")
            output.append("")
            output.append("**Source**: [USPTO EFS-Web Document Description List](https://www.uspto.gov/patents/apply/filing-online/efs-info-document-description)")
            output.append("**Updated**: April 27, 2022")
            output.append("")
            output.append("This table provides document codes used in USPTO patent prosecution, PTAB proceedings, and FPD petitions.")
            output.append("")

            prosecution_codes = []
            ptab_codes = []
            fpd_codes = []

            # Try multiple encodings to handle the CSV file
            encodings_to_try = ['utf-8', 'utf-8-sig', 'latin1', 'cp1252', 'iso-8859-1']

            for encoding in encodings_to_try:
                try:
                    logger.info(f"Trying to read CSV with encoding: {encoding}")
                    with open(csv_path, 'r', encoding=encoding) as file:
                        csv_reader = csv.reader(file)
                        headers = None

                        for row in csv_reader:
                            if not headers:
                                headers = row
                                continue

                            if len(row) >= 4:
                                category = row[0].strip()
                                description = row[1].strip()
                                business_process = row[2].strip()
                                doc_code = row[3].strip()

                                if doc_code and doc_code != "DOC CODE":
                                    # Clean up description and business process
                                    description = description.replace('\n', ' ').replace('\r', ' ')
                                    business_process = business_process.replace('\n', ' ').replace('\r', ' ')

                                    # Remove any problematic characters
                                    description = ''.join(char if ord(char) < 128 else '?' for char in description)
                                    business_process = ''.join(char if ord(char) < 128 else '?' for char in business_process)

                                    # Limit lengths for readability
                                    if len(description) > 120:
                                        description = description[:117] + "..."
                                    if len(business_process) > 100:
                                        business_process = business_process[:97] + "..."

                                    # Escape pipe characters for markdown table
                                    description = description.replace('|', '\\|')
                                    business_process = business_process.replace('|', '\\|')

                                    code_entry = {
                                        'code': doc_code,
                                        'description': description,
                                        'process': business_process,
                                        'category': category
                                    }

                                    if 'PTAB' in category:
                                        ptab_codes.append(code_entry)
                                    elif 'FPD' in category or 'Final Petition Decision' in category:
                                        fpd_codes.append(code_entry)
                                    else:
                                        prosecution_codes.append(code_entry)

                    logger.info(f"Successfully read CSV with {encoding} encoding")
                    break  # Success - exit the encoding loop

                except UnicodeDecodeError as e:
                    logger.warning(f"Failed to read CSV with {encoding} encoding: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Error reading CSV with {encoding} encoding: {e}")
                    continue
            else:
                # If we get here, all encodings failed
                raise FileNotFoundError(f"Unable to read CSV file with any of the attempted encodings: {encodings_to_try}")

            # Add common prosecution codes section
            output.append("## Common Prosecution Document Codes")
            output.append("")
            output.append("| Code | Description | Business Process |")
            output.append("|------|-------------|------------------|")

            # Sort prosecution codes by code for better organization
            prosecution_codes.sort(key=lambda x: x['code'])

            for code_info in prosecution_codes[:60]:  # Limit to first 60 for readability
                output.append(f"| `{code_info['code']}` | {code_info['description']} | {code_info['process']} |")

            # Add PTAB codes section if available
            if ptab_codes:
                output.append("")
                output.append("## PTAB (Patent Trial and Appeal Board) Document Codes")
                output.append("")
                output.append("| Code | Description | Business Process |")
                output.append("|------|-------------|------------------|")

                ptab_codes.sort(key=lambda x: x['code'])

                for code_info in ptab_codes:
                    output.append(f"| `{code_info['code']}` | {code_info['description']} | {code_info['process']} |")

            # Add FPD codes section if available
            if fpd_codes:
                output.append("")
                output.append("## FPD (Final Petition Decision) Document Codes")
                output.append("")
                output.append("| Code | Description | Business Process |")
                output.append("|------|-------------|------------------|")

                fpd_codes.sort(key=lambda x: x['code'])

                for code_info in fpd_codes:
                    output.append(f"| `{code_info['code']}` | {code_info['description']} | {code_info['process']} |")

            # Add common codes reference
            output.append("")
            output.append("## Quick Reference - Most Common Codes")
            output.append("")
            output.append("| Code | Document Type |")
            output.append("|------|---------------|")
            output.append("| `A...` | Amendment/Request for Reconsideration-After Non-Final Rejection |")
            output.append("| `A.PE` | Preliminary Amendment |")
            output.append("| `A.NE` | Response After Final Action |")
            output.append("| `SPEC` | Specification |")
            output.append("| `CLM` | Claims |")
            output.append("| `DRW` | Drawings (black and white line drawings) |")
            output.append("| `N/AP` | Notice of Appeal Filed |")
            output.append("| `AP.B` | Appeal Brief Filed |")
            output.append("| `APRB` | Reply Brief Filed |")
            output.append("| `PA..` | Power of Attorney |")
            output.append("| `IDS` | Information Disclosure Statement |")
            output.append("")
            output.append("---")
            output.append("*This table is generated from the USPTO EFS-Web Document Description List and includes document codes used in patent prosecution, PTAB proceedings, and FPD petitions.*")
            output.append("")
            output.append(f"**Generated**: {import_time().strftime('%Y-%m-%d %H:%M:%S UTC', import_time().gmtime())}")

            result = "\n".join(output)
            logger.info(f"Generated document codes table ({len(result)} characters)")

            return Response(
                content=result,
                media_type="text/markdown",
                headers={
                    "Content-Type": "text/markdown; charset=utf-8",
                    "X-Resource-Type": "USPTO-DOC-CODES",
                    "X-Source": "USPTO-EFS-Web",
                    "Cache-Control": "public, max-age=3600"  # Cache for 1 hour
                }
            )

        except Exception as e:
            logger.error(f"Error generating document codes table: {e}")
            return JSONResponse(
                status_code=500,
                content={
                    "error": True,
                    "message": f"Failed to generate document codes table: {str(e)}",
                    "guidance": "Check that reference/Document_Descriptions_List.csv exists in project root"
                }
            )

    return app
