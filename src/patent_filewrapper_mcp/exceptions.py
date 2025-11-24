"""
Custom exception classes for Patent File Wrapper MCP
"""
from typing import Optional


class PatentFileWrapperError(Exception):
    """Base exception for Patent File Wrapper MCP"""
    def __init__(self, message: str, status_code: int = 500, request_id: Optional[str] = None):
        self.message = message
        self.status_code = status_code
        self.request_id = request_id
        super().__init__(self.message)


class USPTOAPIError(PatentFileWrapperError):
    """USPTO API related errors"""
    pass


class ValidationError(PatentFileWrapperError):
    """Input validation errors"""
    def __init__(self, message: str, request_id: Optional[str] = None):
        super().__init__(message, 400, request_id)


class AuthenticationError(PatentFileWrapperError):
    """Authentication-related errors"""
    def __init__(self, message: str, request_id: Optional[str] = None):
        super().__init__(message, 401, request_id)


class AuthorizationError(PatentFileWrapperError):
    """Authorization-related errors"""
    def __init__(self, message: str, request_id: Optional[str] = None):
        super().__init__(message, 403, request_id)


class NotFoundError(PatentFileWrapperError):
    """Resource not found errors"""
    def __init__(self, message: str, request_id: Optional[str] = None):
        super().__init__(message, 404, request_id)


class RateLimitError(PatentFileWrapperError):
    """Rate limit exceeded errors"""
    def __init__(self, message: str, request_id: Optional[str] = None):
        super().__init__(message, 429, request_id)


class TimeoutError(PatentFileWrapperError):
    """Request timeout errors"""
    def __init__(self, message: str, request_id: Optional[str] = None):
        super().__init__(message, 408, request_id)


class OCRRateLimitError(RateLimitError):
    """OCR-specific rate limit errors"""
    def __init__(self, message: str, retry_after_seconds: Optional[int] = None, request_id: Optional[str] = None):
        super().__init__(message, request_id)
        self.retry_after_seconds = retry_after_seconds