"""
Error handling decorators and utilities for MCP tools

This module provides consistent error handling across all MCP tools,
converting exceptions to standardized error responses.
"""

import functools
from typing import Callable, Any, Dict
from ..api.helpers import create_error_response, format_error_response
from ..exceptions import (
    ValidationError,
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
    RateLimitError,
    RequestTimeoutError,
    USPTOAPIError,
    PatentFileWrapperError
)
from ..shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)


#: Exception type -> (log level, ERROR_TEMPLATES key or None, status override
#: or None, error_type for the untemplated path).
#:
#: A table, not the ten-arm `elif isinstance(...)` ladder this was (audits
#: Q-3, SOLID F-4). The ORDER is still load-bearing — PatentFileWrapperError is
#: the base of five entries above it and must stay last, and USPTOAPIError
#: must precede it — but now that is one property of one ordered structure
#: rather than something a careless insertion anywhere in 110 lines can break.
#: Python dicts preserve insertion order, which is what makes this equivalent.
_DISPATCH = (
    (ValidationError,         "warning", "validation_error",    None, None),
    (AuthenticationError,     "error",   "api_auth_failed",     401,  None),
    (AuthorizationError,      "error",   None,                  403,  "authorization_error"),
    (NotFoundError,           "info",    "document_not_found",  404,  None),
    (RequestTimeoutError,     "error",   "api_timeout",         408,  None),
    (RateLimitError,          "warning", "rate_limit_exceeded", 429,  None),
    (USPTOAPIError,           "error",   None,                  None, "uspto_api_error"),
    (PatentFileWrapperError,  "error",   None,                  None, "patent_filewrapper_error"),
)


def _handle_exception(e: Exception, func_name: str) -> Dict[str, Any]:
    """
    Centralized exception handling logic for both async and sync wrappers.

    This function provides a single source of truth for exception handling,
    eliminating duplication between async and sync wrapper implementations.

    Args:
        e: The exception to handle
        func_name: Name of the function that raised the exception

    Returns:
        Standardized error response dictionary
    """
    for exc_type, level, template_key, status, error_type in _DISPATCH:
        if not isinstance(e, exc_type):
            continue
        getattr(logger, level)(f"{exc_type.__name__} in {func_name}: {e.message}")
        if template_key:
            return create_error_response(
                template_key,
                custom_message=e.message,
                status_code=status if status is not None else e.status_code,
                request_id=e.request_id,
            )
        return format_error_response(
            e.message,
            status_code=status if status is not None else e.status_code,
            request_id=e.request_id,
            error_type=error_type,
        )

    if isinstance(e, ValueError):
        logger.warning(f"Value error in {func_name}: {e}")
        return create_error_response(
            "validation_error",
            custom_message=str(e),
            status_code=400
        )

    if isinstance(e, KeyError):
        # A KeyError raised while walking a USPTO response is a server-side
        # bug or an upstream schema change, not bad client input, so it is a
        # 500 with a stack trace rather than a 400 telling the caller to fix
        # their request (audit exception-flow F-7). The key name stays out of
        # the response: it names an internal field.
        logger.exception(f"Missing key in {func_name}: {e}")
        return format_error_response(
            "The USPTO response was missing an expected field.",
            status_code=500,
            error_type="upstream_schema_error",
            exception=e,
        )

    # Catch-all for unexpected errors
    logger.exception(f"Unexpected error in {func_name}: {e}")
    return format_error_response(
        "An unexpected error occurred. Please try again.",
        status_code=500,
        error_type="unexpected_error",
        exception=e  # Include exception for dev/prod filtering
    )


def mcp_error_handler(func: Callable) -> Callable:
    """
    Decorator to standardize error handling for MCP tool functions

    This decorator catches all exceptions and converts them to standardized
    error response dictionaries. It provides different handling for:
    - Custom exceptions (ValidationError, AuthenticationError, etc.)
    - HTTP errors from external APIs
    - Unexpected exceptions

    Usage:
        @mcp.tool(name="PFW_search_applications")
        @mcp_error_handler
        async def pfw_search_applications(...):
            # Tool implementation
            pass

    Args:
        func: The MCP tool function to decorate

    Returns:
        Wrapped function with consistent error handling
    """
    @functools.wraps(func)
    async def async_wrapper(*args, **kwargs) -> Dict[str, Any]:
        """Async wrapper for error handling"""
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            return _handle_exception(e, func.__name__)

    @functools.wraps(func)
    def sync_wrapper(*args, **kwargs) -> Dict[str, Any]:
        """Sync wrapper for error handling"""
        try:
            return func(*args, **kwargs)
        except Exception as e:
            return _handle_exception(e, func.__name__)

    # Return async or sync wrapper based on function type
    import asyncio
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper


def handle_api_errors(func: Callable) -> Callable:
    """
    Decorator specifically for API client methods

    Similar to mcp_error_handler but designed for API client methods
    that may raise httpx exceptions.

    Usage:
        @handle_api_errors
        async def search_applications(self, query: str):
            # API implementation
            pass

    Args:
        func: The API client method to decorate

    Returns:
        Wrapped function with API error handling
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)

        except Exception as e:
            # Import httpx here to avoid circular import
            try:
                import httpx

                if isinstance(e, httpx.HTTPStatusError):
                    status_code = e.response.status_code

                    if status_code == 401:
                        raise AuthenticationError("Invalid API key or authentication failed")
                    elif status_code == 403:
                        raise AuthorizationError("Access forbidden")
                    elif status_code == 404:
                        raise NotFoundError("Resource not found")
                    elif status_code == 429:
                        raise RateLimitError("Rate limit exceeded")
                    elif status_code >= 500:
                        raise USPTOAPIError(f"Server error: {status_code}")
                    else:
                        raise USPTOAPIError(f"HTTP error: {status_code}")

                elif isinstance(e, httpx.TimeoutException):
                    raise RequestTimeoutError("Request timed out")

                elif isinstance(e, httpx.ConnectError):
                    raise USPTOAPIError("Failed to connect to USPTO API")

            except ImportError:
                pass

            # Re-raise if not handled
            raise

    return wrapper
