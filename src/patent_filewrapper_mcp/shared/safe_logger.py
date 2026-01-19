"""
Safe logging wrapper with automatic sensitive data sanitization.

This module provides a logger adapter that automatically sanitizes log messages
to prevent sensitive data (API keys, tokens, passwords, etc.) from being logged.

Usage:
    from patent_filewrapper_mcp.shared.safe_logger import get_safe_logger

    logger = get_safe_logger(__name__)
    logger.info(f"API response: {response_text}")  # API keys auto-masked
"""

import logging
from typing import Any

from .log_sanitizer import LogSanitizer


# Global sanitizer instance
_sanitizer = LogSanitizer()


class SafeLoggerAdapter(logging.LoggerAdapter):
    """
    Logger adapter that automatically sanitizes all log messages.

    Wraps the standard Python logger and sanitizes:
    - String messages
    - Dictionary arguments
    - Keyword arguments with sensitive keys
    """

    def process(self, msg: Any, kwargs: Any) -> tuple:
        """
        Sanitize message and arguments before logging.

        Args:
            msg: The log message
            kwargs: Keyword arguments

        Returns:
            Tuple of (sanitized_msg, sanitized_kwargs)
        """
        # Sanitize the message
        if isinstance(msg, str):
            msg = _sanitizer.sanitize_string(msg)

        # Sanitize extra keyword arguments if present
        if 'extra' in kwargs:
            if isinstance(kwargs['extra'], dict):
                kwargs['extra'] = _sanitizer.sanitize_dict(kwargs['extra'])

        return msg, kwargs

    def debug(self, msg: Any, *args, **kwargs) -> None:
        """Log a debug message with sanitization."""
        msg, kwargs = self._sanitize_args(msg, *args, **kwargs)
        super().debug(msg, *args, **kwargs)

    def info(self, msg: Any, *args, **kwargs) -> None:
        """Log an info message with sanitization."""
        msg, kwargs = self._sanitize_args(msg, *args, **kwargs)
        super().info(msg, *args, **kwargs)

    def warning(self, msg: Any, *args, **kwargs) -> None:
        """Log a warning message with sanitization."""
        msg, kwargs = self._sanitize_args(msg, *args, **kwargs)
        super().warning(msg, *args, **kwargs)

    def warn(self, msg: Any, *args, **kwargs) -> None:
        """Log a warning message with sanitization (alias for warning)."""
        self.warning(msg, *args, **kwargs)

    def error(self, msg: Any, *args, **kwargs) -> None:
        """Log an error message with sanitization."""
        msg, kwargs = self._sanitize_args(msg, *args, **kwargs)
        super().error(msg, *args, **kwargs)

    def exception(self, msg: Any, *args, **kwargs) -> None:
        """Log an exception message with sanitization."""
        msg, kwargs = self._sanitize_args(msg, *args, **kwargs)
        super().exception(msg, *args, **kwargs)

    def critical(self, msg: Any, *args, **kwargs) -> None:
        """Log a critical message with sanitization."""
        msg, kwargs = self._sanitize_args(msg, *args, **kwargs)
        super().critical(msg, *args, **kwargs)

    def _sanitize_args(self, msg: Any, *args, **kwargs) -> tuple:
        """
        Sanitize message and keyword arguments.

        Args:
            msg: The log message
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Tuple of (sanitized_msg, sanitized_kwargs)
        """
        # Sanitize the message
        if isinstance(msg, str):
            msg = _sanitizer.sanitize_string(msg)
        elif isinstance(msg, dict):
            msg = _sanitizer.sanitize_dict(msg)

        # Sanitize positional arguments
        sanitized_args = []
        for arg in args:
            if isinstance(arg, str):
                sanitized_args.append(_sanitizer.sanitize_string(arg))
            elif isinstance(arg, dict):
                sanitized_args.append(_sanitizer.sanitize_dict(arg))
            else:
                sanitized_args.append(arg)

        # Sanitize keyword arguments (except standard logging kwargs)
        standard_logging_kwargs = {'exc_info', 'stack_info', 'stacklevel', 'extra'}
        sanitized_kwargs = {}
        for key, value in kwargs.items():
            if key in standard_logging_kwargs:
                sanitized_kwargs[key] = value
            elif isinstance(value, str):
                sanitized_kwargs[key] = _sanitizer.sanitize_string(value)
            elif isinstance(value, dict):
                sanitized_kwargs[key] = _sanitizer.sanitize_dict(value)
            else:
                sanitized_kwargs[key] = value

        return msg, sanitized_kwargs


def get_safe_logger(name: str) -> SafeLoggerAdapter:
    """
    Get a logger that automatically sanitizes sensitive data.

    This is the preferred way to get a logger for the USPTO Patent File Wrapper MCP.
    It ensures that sensitive data like API keys, tokens, and passwords are never
    logged in plain text.

    Usage:
        from patent_filewrapper_mcp.shared.safe_logger import get_safe_logger

        logger = get_safe_logger(__name__)
        logger.info(f"API response: {response_text}")  # API keys auto-masked

    Args:
        name: Logger name (typically __name__)

    Returns:
        SafeLoggerAdapter that sanitizes all messages
    """
    base_logger = logging.getLogger(name)
    return SafeLoggerAdapter(base_logger, {})


def get_security_logger() -> logging.Logger:
    """
    Get the dedicated security logger.

    The security logger writes to a separate log file (security.log) and is used
    for security-related events like authentication failures, rate limit violations,
    and suspicious activity.

    Usage:
        from patent_filewrapper_mcp.shared.safe_logger import get_security_logger

        security_logger = get_security_logger()
        security_logger.warning(f"Failed authentication attempt from IP: {ip}")

    Returns:
        Logger configured for security events
    """
    return logging.getLogger('security')


def set_sanitizer_enabled(enabled: bool) -> None:
    """
    Enable or disable sanitization for all safe loggers.

    WARNING: Disabling sanitization is not recommended in production.

    Args:
        enabled: Whether to enable sanitization
    """
    _sanitizer.enable_all = enabled


def is_sanitizer_enabled() -> bool:
    """
    Check if sanitization is currently enabled.

    Returns:
        True if sanitization is enabled, False otherwise
    """
    return _sanitizer.enable_all