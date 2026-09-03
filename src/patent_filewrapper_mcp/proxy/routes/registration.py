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

# The document identifier is the one binding every registering sibling carries.
# FPD's create_document_access_token writes "document_identifier"; PTAB's
# deployed create_service_token writes "document_id".
_DOC_ID_ALIASES = ("document_identifier", "document_id")

# PTAB's proceeding number reaches the token as "identifier" when the
# document-access shape is used, and is absent from today's service token.
_PROCEEDING_ALIASES = ("proceeding_number", "identifier")


def _require_bound_token(request_id, token_payload, bindings, *, required_binding):
    """Reject a registration token that was not minted for THIS resource.

    A signed inter-MCP token proves only who issued it. Without this check any
    unexpired token from the expected service registers any uspto.gov URL under
    any identifier, and PFW then attaches its own shared USPTO key to fetch it
    (audit H-1 / security-report R-1).

    `bindings` maps a request value to the metadata key aliases that may carry
    it. Every alias the token DOES carry must match; `required_binding` names
    the entry that must be present, so an empty or stripped metadata block is
    rejected rather than skipped. The `type` claim is checked only when the
    token carries one: PTAB's deployed registration path mints a service token
    (`create_service_token`, metadata `{source, document_id}`) rather than
    FPD's `create_document_access_token`, so demanding `type` unconditionally
    would reject every live PTAB registration.
    """
    metadata = token_payload.get("metadata") or {}

    token_type = metadata.get("type")
    if token_type is not None and token_type != "document_access":
        logger.warning(f"[{request_id}] Token not for document access: {token_type}")
        raise HTTPException(status_code=401, detail="Invalid token type")

    matched_required = False
    for expected_value, aliases in bindings.items():
        for alias in aliases:
            if alias not in metadata:
                continue
            if metadata[alias] != expected_value:
                logger.warning(
                    f"[{request_id}] Token metadata mismatch on '{alias}'; "
                    f"token was not minted for this resource"
                )
                raise HTTPException(
                    status_code=401,
                    detail="Token metadata does not match request",
                )
            if aliases is required_binding:
                matched_required = True

    if not matched_required:
        logger.warning(
            f"[{request_id}] Token carries no resource binding "
            f"({'/'.join(required_binding)}); refusing to register"
        )
        raise HTTPException(
            status_code=401,
            detail="Token metadata does not match request",
        )


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
    # no local `import os` here — os is imported at module level (L6) and a
    # function-scope re-import shadows it; main.py:319 records that exact
    # shadowing causing an UnboundLocalError elsewhere in this repo.
    request_id = generate_request_id()

    try:
        # Get client IP for logging and rate limiting
        client_ip = request.client.host if request.client else "unknown"

        # Rate-limit registration endpoints: 10 req/min per IP
        if not rate_limiter.is_allowed(client_ip, limit=10, window=60.0):
            remaining_time = max(1, int(rate_limiter.get_reset_time(client_ip, limit=10, window=60.0) - time.time()))
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
            single_use=True,              # One token, one registration (audit L-4)
        )

        if not is_valid:
            logger.warning(f"[{request_id}] Invalid access token from FPD MCP")
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired access token"
            )

        # Verify the token was minted for THIS petition and THIS document
        _require_bound_token(
            request_id,
            token_payload,
            {
                registration.document_identifier: _DOC_ID_ALIASES,
                registration.petition_id: ("petition_id",),
            },
            required_binding=_DOC_ID_ALIASES,
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

        # The key is NOT written into the row: the download route reads the
        # live one from the secure store. The check above stays so a missing
        # key fails here, at registration, rather than at download time.
        success = fpd_store.register_document(
            petition_id=registration.petition_id,
            document_identifier=registration.document_identifier,
            download_url=registration.download_url,
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
    except Exception:
        logger.exception(f"[{request_id}] Error registering FPD document")
        raise HTTPException(
            status_code=500,
            detail="Registration failed"
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
    request_id = generate_request_id()

    try:
        # Get client IP for logging and rate limiting
        client_ip = request.client.host if request.client else "unknown"

        # Rate-limit registration endpoints: 10 req/min per IP
        if not rate_limiter.is_allowed(client_ip, limit=10, window=60.0):
            remaining_time = max(1, int(rate_limiter.get_reset_time(client_ip, limit=10, window=60.0) - time.time()))
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
            single_use=True,               # One token, one registration (audit L-4)
        )

        if not is_valid:
            logger.warning(f"[{request_id}] Invalid access token from PTAB MCP")
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired access token"
            )

        # Verify the token was minted for THIS proceeding and THIS document.
        # Absent before audit H-1: the handler went straight from the signature
        # check to spending PFW's shared USPTO key on a caller-chosen URL.
        _require_bound_token(
            request_id,
            token_payload,
            {
                registration.document_identifier: _DOC_ID_ALIASES,
                registration.proceeding_number: _PROCEEDING_ALIASES,
            },
            required_binding=_DOC_ID_ALIASES,
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

        # The key is NOT written into the row: the download route reads the
        # live one from the secure store. The check above stays so a missing
        # key fails here, at registration, rather than at download time.
        success = ptab_store.register_document(
            proceeding_number=registration.proceeding_number,
            document_identifier=registration.document_identifier,
            download_url=registration.download_url,
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
    except Exception:
        logger.exception(f"[{request_id}] Error registering PTAB document")
        raise HTTPException(
            status_code=500,
            detail="Registration failed"
        )

