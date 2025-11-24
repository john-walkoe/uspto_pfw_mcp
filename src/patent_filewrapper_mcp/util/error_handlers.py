"""
Error handling decorators and utilities for MCP tools

This module provides consistent error handling across all MCP tools,
converting exceptions to standardized error responses.
"""

import logging
import functools
from typing import Callable, Any, Dict
from ..api.helpers import create_error_response, format_error_response
from ..exceptions import (
    ValidationError,
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
    RateLimitError,
    TimeoutError,
    USPTOAPIError,
    PatentFileWrapperError
)

logger = logging.getLogger(__name__)


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
    if isinstance(e, ValidationError):
        logger.warning(f"Validation error in {func_name}: {e.message}")
        return create_error_response(
            "validation_error",
            custom_message=e.message,
            status_code=e.status_code,
            request_id=e.request_id
        )

    elif isinstance(e, AuthenticationError):
        logger.error(f"Authentication error in {func_name}: {e.message}")
        return create_error_response(
            "api_auth_failed",
            custom_message=e.message,
            status_code=401,
            request_id=e.request_id
        )

    elif isinstance(e, AuthorizationError):
        logger.error(f"Authorization error in {func_name}: {e.message}")
        return format_error_response(
            e.message,
            status_code=403,
            request_id=e.request_id,
            error_type="authorization_error"
        )

    elif isinstance(e, NotFoundError):
        logger.info(f"Resource not found in {func_name}: {e.message}")
        return create_error_response(
            "document_not_found",
            custom_message=e.message,
            status_code=404,
            request_id=e.request_id
        )

    elif isinstance(e, TimeoutError):
        logger.error(f"Timeout in {func_name}: {e.message}")
        return create_error_response(
            "api_timeout",
            custom_message=e.message,
            status_code=408,
            request_id=e.request_id
        )

    elif isinstance(e, RateLimitError):
        logger.warning(f"Rate limit exceeded in {func_name}: {e.message}")
        return create_error_response(
            "rate_limit_exceeded",
            custom_message=e.message,
            status_code=429,
            request_id=e.request_id
        )

    elif isinstance(e, USPTOAPIError):
        logger.error(f"USPTO API error in {func_name}: {e.message}")
        return format_error_response(
            e.message,
            status_code=e.status_code,
            request_id=e.request_id,
            error_type="uspto_api_error"
        )

    elif isinstance(e, PatentFileWrapperError):
        # Catch-all for other custom exceptions
        logger.error(f"Patent File Wrapper error in {func_name}: {e.message}")
        return format_error_response(
            e.message,
            status_code=e.status_code,
            request_id=e.request_id,
            error_type="patent_filewrapper_error"
        )

    elif isinstance(e, ValueError):
        logger.warning(f"Value error in {func_name}: {e}")
        return create_error_response(
            "validation_error",
            custom_message=str(e),
            status_code=400
        )

    elif isinstance(e, KeyError):
        logger.error(f"Missing required field in {func_name}: {e}")
        return format_error_response(
            f"Missing required field: {str(e)}",
            status_code=400,
            error_type="missing_field"
        )

    else:
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
        @mcp.tool(name="search_applications")
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
                    raise TimeoutError("Request timed out")

                elif isinstance(e, httpx.ConnectError):
                    raise USPTOAPIError("Failed to connect to USPTO API")

            except ImportError:
                pass

            # Re-raise if not handled
            raise

    return wrapper
