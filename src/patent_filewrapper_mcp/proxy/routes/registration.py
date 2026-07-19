"""FPD/PTAB document-registration routes for the PFW proxy (carved out of
create_proxy_app() — audit F4)."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
import os
import time

from ...api.helpers import generate_request_id
from ...shared.internal_auth import get_pfw_auth
from ...shared.safe_logger import get_safe_logger
from ...util.security_logger import security_logger
from ..fpd_document_store import get_fpd_store
from ..models import (
    FPDDocumentRegistration,
    FPDDocumentRegistrationResponse,
    PTABDocumentRegistration,
    PTABDocumentRegistrationResponse,
)
from ..ptab_document_store import get_ptab_store
from ..rate_limiter import rate_limiter

logger = get_safe_logger(__name__)

router = APIRouter()

@router.post("/register-fpd-document", response_model=FPDDocumentRegistrationResponse)
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
        # Get client IP for logging and rate limiting
        client_ip = request.client.host if request.client else "unknown"
        request_id = generate_request_id()

        # Rate-limit registration endpoints: 10 req/min per IP
        if not rate_limiter.is_allowed(client_ip, limit=10, window=60.0):
            remaining_time = max(1, int(rate_limiter.get_reset_time(client_ip) - time.time()))
            security_logger.log_rate_limit_violation(
                client_ip, "/register-fpd-document", request_id
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": True,
                    "message": "Rate limit exceeded for registration endpoint (10 req/min).",
                    "retry_after": remaining_time,
                    "remaining_requests": 0,
                    "request_id": request_id,
                },
                headers={"Retry-After": str(int(remaining_time))},
            )

        logger.info(
            f"[{request_id}] FPD document registration request from {client_ip}: "
            f"petition_id={registration.petition_id}, doc_id={registration.document_identifier}"
        )

        # Validate the access token from FPD MCP
        is_valid, token_payload = get_pfw_auth().validate_incoming_token(
            registration.access_token,
            expected_service="fpd-mcp",   # Bind token to originating service
        )

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
            from ...shared_secure_storage import get_uspto_api_key
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
            proxy_base = os.getenv("PFW_PROXY_BASE_URL", f"http://localhost:{proxy_port}")

            # Return a browser-usable PERSISTENT link. The direct
            # /download/{petition_id}/{doc} route requires X-Proxy-Token,
            # which browsers cannot send on navigation (Lesson 43) — a
            # direct URL here would 401 on click. The persistent resolver
            # calls download_document() directly, which dispatches to the
            # FPD document store.
            try:
                from ..secure_link_cache import get_link_cache
                download_url = get_link_cache().generate_persistent_link(
                    app_number=registration.petition_id,
                    doc_id=registration.document_identifier,
                    base_url=proxy_base,
                )
            except Exception as link_error:
                logger.warning(
                    f"[{request_id}] Persistent link generation failed "
                    f"({type(link_error).__name__}); returning direct URL"
                )
                download_url = f"{proxy_base}/download/{registration.petition_id}/{registration.document_identifier}"

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


@router.post("/register-ptab-document", response_model=PTABDocumentRegistrationResponse)
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
        # Get client IP for logging and rate limiting
        client_ip = request.client.host if request.client else "unknown"
        request_id = generate_request_id()

        # Rate-limit registration endpoints: 10 req/min per IP
        if not rate_limiter.is_allowed(client_ip, limit=10, window=60.0):
            remaining_time = max(1, int(rate_limiter.get_reset_time(client_ip) - time.time()))
            security_logger.log_rate_limit_violation(
                client_ip, "/register-ptab-document", request_id
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": True,
                    "message": "Rate limit exceeded for registration endpoint (10 req/min).",
                    "retry_after": remaining_time,
                    "remaining_requests": 0,
                    "request_id": request_id,
                },
                headers={"Retry-After": str(int(remaining_time))},
            )

        logger.info(
            f"[{request_id}] PTAB document registration request from {client_ip}: "
            f"proceeding={registration.proceeding_number}, doc_id={registration.document_identifier}, "
            f"type={registration.proceeding_type}"
        )

        # Validate the access token from PTAB MCP
        is_valid, token_payload = get_pfw_auth().validate_incoming_token(
            registration.access_token,
            expected_service="ptab-mcp",   # Bind token to originating service
        )

        if not is_valid:
            logger.warning(f"[{request_id}] Invalid access token from PTAB MCP")
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired access token"
            )

        logger.info(f"[{request_id}] Access token validated successfully for PTAB document")

        # Get PFW's own secure USPTO API key
        try:
            from ...shared_secure_storage import get_uspto_api_key
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
            proxy_base = os.getenv("PFW_PROXY_BASE_URL", f"http://localhost:{proxy_port}")

            # Return a browser-usable PERSISTENT link. The direct
            # /download/{proceeding}/{doc} route requires X-Proxy-Token,
            # which browsers cannot send on navigation (Lesson 43) — a
            # direct URL here would 401 on click. The persistent resolver
            # calls download_document() directly, which dispatches to the
            # PTAB document store.
            try:
                from ..secure_link_cache import get_link_cache
                download_url = get_link_cache().generate_persistent_link(
                    app_number=registration.proceeding_number,
                    doc_id=registration.document_identifier,
                    base_url=proxy_base,
                )
            except Exception as link_error:
                logger.warning(
                    f"[{request_id}] Persistent link generation failed "
                    f"({type(link_error).__name__}); returning direct URL"
                )
                download_url = f"{proxy_base}/download/{registration.proceeding_number}/{registration.document_identifier}"

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

