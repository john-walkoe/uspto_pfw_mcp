"""
Log sanitizer for automatically masking sensitive data in log messages.

This module provides sanitization patterns for common sensitive data types:
- API keys (USPTO, Mistral, etc.)
- JWT tokens
- IP addresses (partial masking)
- Email addresses (partial masking)
- Passwords and secrets
"""

import logging
import re
import traceback
from typing import Dict, Pattern


class LogSanitizer:
    """
    Sanitizes log messages by replacing sensitive data with placeholders.

    Uses regex patterns to detect and mask sensitive information.
    """

    # Pre-compiled regex patterns for performance
    PATTERNS: Dict[str, Pattern] = {
        # USPTO API keys (30 character alphanumeric)
        'uspto_api_key': re.compile(r'\b[a-zA-Z0-9]{30}\b'),

        # Mistral API keys (32 character alphanumeric)
        'mistral_api_key': re.compile(r'\b[a-zA-Z0-9]{32}\b'),

        # JWT tokens (Bearer token pattern)
        'jwt_token': re.compile(r'Bearer\s+[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.?[A-Za-z0-9-_.+/=]*'),

        # Generic API key patterns (common formats)
        'api_key_sk': re.compile(r'\bsk-[a-zA-Z0-9]{20,}\b'),
        'api_key_live': re.compile(r'\blive_[a-zA-Z0-9]{20,}\b'),
        'api_key_test': re.compile(r'\btest_[a-zA-Z0-9]{20,}\b'),

        # IP addresses (partial masking - show first two octets)
        'ip_address': re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b'),

        # Email addresses (partial masking - show first char)
        'email_address': re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),

        # Password/secret fields in JSON/dict-like strings
        'password_field': re.compile(r'(?i)(["\']?password["\']?\s*[:=]\s*["\']?)([^"\'}\s]+)'),
        'secret_field': re.compile(r'(?i)(["\']?secret["\']?\s*[:=]\s*["\']?)([^"\'}\s]+)'),
        'token_field': re.compile(r'(?i)(["\']?token["\']?\s*[:=]\s*["\']?)([^"\'}\s]+)'),
        'api_key_field': re.compile(r'(?i)(["\']?api[_-]?key["\']?\s*[:=]\s*["\']?)([^"\'}\s]+)'),

        # Generic API response keys
        'response_key': re.compile(r'(?i)api[_-]?key["\']?\s*[:\s]+["\']?([a-zA-Z0-9_-]{20,})'),

        # Persistent download link hashes — the hash IS the credential (Lesson 43)
        'persistent_link_path': re.compile(r'(/(?:document|download)/persistent/)[A-Za-z0-9_\-]{16,}'),
        # Bare link hashes (sha256[:24] hex)
        'link_hash_hex': re.compile(r'\b[a-f0-9]{24}\b'),

        # URL query strings — may embed tokens or search terms
        'url_query': re.compile(r'(https?://[^\s"\'<>?]+)\?[^\s"\'<>]+'),

        # Long urlsafe-base64 tokens (secrets.token_urlsafe(32) is 43 chars)
        'urlsafe_token': re.compile(r'\b(?=[A-Za-z0-9_\-]*[A-Za-z])(?=[A-Za-z0-9_\-]*[0-9])[A-Za-z0-9_\-]{40,}\b'),
    }

    # Replacement strings
    REPLACEMENTS: Dict[str, str] = {
        'uspto_api_key': '[USPTO_API_KEY]',
        'mistral_api_key': '[MISTRAL_API_KEY]',
        'jwt_token': '[FILTERED]',
        'api_key_sk': '[API_KEY]',
        'api_key_live': '[API_KEY]',
        'api_key_test': '[API_KEY]',
        'ip_address': '[IP]',
        'email_address': '[EMAIL]',
        'password_field': r'\1[REDACTED]',
        'secret_field': r'\1[REDACTED]',
        'token_field': r'\1[REDACTED]',
        'api_key_field': r'\1[REDACTED]',
        'response_key': 'api_key": "[REDACTED]"',
        'persistent_link_path': r'\1[LINK_HASH]',
        'link_hash_hex': '[LINK_HASH]',
        'url_query': r'\1?[QUERY_REDACTED]',
        'urlsafe_token': '[TOKEN]',
    }

    def __init__(self, enable_all: bool = True):
        """
        Initialize the log sanitizer.

        Args:
            enable_all: If False, only sanitize critical patterns (passwords, tokens)
        """
        self.enable_all = enable_all

    def sanitize_string(self, message: str) -> str:
        """
        Sanitize a string message by replacing sensitive data.

        Args:
            message: The message to sanitize

        Returns:
            The sanitized message with sensitive data replaced
        """
        if not isinstance(message, str):
            return str(message)

        # Strip CR/LF and other control characters unconditionally (audit M5,
        # CWE-117): a URL-encoded %0A in an unvalidated identifier must not be
        # able to forge log lines. Done before secret-masking so multi-line
        # payloads can't split a secret across the pattern boundary.
        result = re.sub(r'[\r\n\x00-\x08\x0b\x0c\x0e-\x1f]', ' ', message)

        # Always sanitize critical patterns (passwords, secrets, tokens)
        critical_patterns = ['password_field', 'secret_field', 'token_field', 'api_key_field', 'response_key']
        for pattern_name in critical_patterns:
            if pattern_name in self.PATTERNS:
                result = self.PATTERNS[pattern_name].sub(self.REPLACEMENTS[pattern_name], result)

        # Sanitize other patterns if enabled
        if self.enable_all:
            for pattern_name, pattern in self.PATTERNS.items():
                if pattern_name not in critical_patterns:
                    # Special handling for IP addresses and emails to preserve some info
                    if pattern_name == 'ip_address':
                        result = self._mask_ip_address(result, pattern)
                    elif pattern_name == 'email_address':
                        result = self._mask_email_address(result, pattern)
                    else:
                        result = pattern.sub(self.REPLACEMENTS[pattern_name], result)

        return result

    def _mask_ip_address(self, message: str, pattern: Pattern) -> str:
        """Mask IP address showing first two octets."""
        def replace_ip(match):
            ip = match.group(0)
            parts = ip.split('.')
            if len(parts) == 4:
                return f"{parts[0]}.{parts[1]}.***.***"
            return '[IP]'

        return pattern.sub(replace_ip, message)

    def _mask_email_address(self, message: str, pattern: Pattern) -> str:
        """Mask email address showing first character."""
        def replace_email(match):
            email = match.group(0)
            parts = email.split('@')
            if len(parts) == 2:
                username = parts[0]
                domain = parts[1]
                masked_username = username[0] + '***' if len(username) > 1 else '***'
                return f"{masked_username}@{domain}"
            return '[EMAIL]'

        return pattern.sub(replace_email, message)

    def sanitize_dict(self, data: dict) -> dict:
        """
        Sanitize a dictionary by masking sensitive values.

        Args:
            data: Dictionary to sanitize

        Returns:
            Dictionary with sensitive values masked
        """
        sanitized = {}
        sensitive_keys = {
            'password', 'passwd', 'secret', 'token', 'api_key', 'apikey',
            'access_token', 'auth_token', 'refresh_token', 'private_key',
            'session_id', 'session_key', 'cookie'
        }

        for key, value in data.items():
            if isinstance(key, str) and key.lower() in sensitive_keys:
                sanitized[key] = '[REDACTED]'
            elif isinstance(value, dict):
                sanitized[key] = self.sanitize_dict(value)
            elif isinstance(value, str):
                sanitized[key] = self.sanitize_string(value)
            else:
                sanitized[key] = value

        return sanitized

    def sanitize_args(self, *args, **kwargs) -> tuple:
        """
        Sanitize logging function arguments.

        Args:
            *args: Positional arguments to sanitize
            **kwargs: Keyword arguments to sanitize

        Returns:
            Tuple of (sanitized_args, sanitized_kwargs)
        """
        sanitized_args = []
        for arg in args:
            if isinstance(arg, str):
                sanitized_args.append(self.sanitize_string(arg))
            elif isinstance(arg, dict):
                sanitized_args.append(self.sanitize_dict(arg))
            else:
                sanitized_args.append(arg)

        sanitized_kwargs = {}
        for key, value in kwargs.items():
            if isinstance(value, str):
                sanitized_kwargs[key] = self.sanitize_string(value)
            elif isinstance(value, dict):
                sanitized_kwargs[key] = self.sanitize_dict(value)
            else:
                sanitized_kwargs[key] = value

        return tuple(sanitized_args), sanitized_kwargs


# Global sanitizer instance for convenience
_default_sanitizer = LogSanitizer()


def sanitize_string(message: str) -> str:
    """
    Convenience function to sanitize a string using the default sanitizer.

    Args:
        message: Message to sanitize

    Returns:
        Sanitized message
    """
    return _default_sanitizer.sanitize_string(message)


def sanitize_dict(data: dict) -> dict:
    """
    Convenience function to sanitize a dict using the default sanitizer.

    Args:
        data: Dictionary to sanitize

    Returns:
        Sanitized dictionary
    """
    return _default_sanitizer.sanitize_dict(data)


class SanitizingFilter(logging.Filter):
    """Handler-level filter that sanitizes every record at the sink.

    Attached to each handler by setup_logging() so sanitization does not
    depend on which logger object a module (or a third-party library such
    as httpx/uvicorn) happened to grab. SafeLogger remains the ergonomic
    call-site wrapper; this filter is the guarantee.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _default_sanitizer.sanitize_string(record.getMessage())
        record.args = ()
        # Handlers format exc_info AFTER filters run, so pre-render and
        # sanitize the traceback here (httpx exception reprs embed full
        # request URLs) and stop the handler re-formatting it.
        if record.exc_info and record.exc_info[0] is not None:
            if not record.exc_text:
                record.exc_text = "".join(
                    traceback.format_exception(*record.exc_info)
                )
            record.exc_info = None
        if record.exc_text:
            record.exc_text = _default_sanitizer.sanitize_string(record.exc_text)
        return True
