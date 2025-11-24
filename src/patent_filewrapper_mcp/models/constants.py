"""
Constants for USPTO Patent File Wrapper MCP

This module defines constants for frequently used strings throughout the codebase
to prevent typos, improve maintainability, and enable IDE autocomplete.
"""

from typing import List


class IdentifierType:
    """Constants for patent identifier types"""

    APPLICATION = "application"
    PATENT = "patent"
    PUBLICATION = "publication"

    @classmethod
    def all(cls) -> List[str]:
        """Get all valid identifier types"""
        return [cls.APPLICATION, cls.PATENT, cls.PUBLICATION]


class DocumentDirection:
    """Constants for document direction categories"""

    INCOMING = "INCOMING"
    OUTGOING = "OUTGOING"
    INTERNAL = "INTERNAL"

    @classmethod
    def all(cls) -> List[str]:
        """Get all valid direction categories"""
        return [cls.INCOMING, cls.OUTGOING, cls.INTERNAL]

    @classmethod
    def is_valid(cls, direction: str) -> bool:
        """Check if a direction is valid"""
        return direction.upper() in cls.all()


class TechnologyKeyword:
    """Common technology classification keywords for search"""

    WIRELESS = "wireless"
    DIGITAL = "digital"
    ELECTRONIC = "electronic"
    COMPUTER = "computer"
    SOFTWARE = "software"
    HARDWARE = "hardware"
    NETWORK = "network"
    SYSTEM = "system"

    @classmethod
    def all(cls) -> List[str]:
        """Get all technology keywords"""
        return [
            cls.WIRELESS,
            cls.DIGITAL,
            cls.ELECTRONIC,
            cls.COMPUTER,
            cls.SOFTWARE,
            cls.HARDWARE,
            cls.NETWORK,
            cls.SYSTEM
        ]


class ApplicationStatus:
    """Common application status codes"""

    PENDING = "pending"
    ALLOWED = "allowed"
    PATENTED = "patented"
    ABANDONED = "abandoned"
    REJECTED = "rejected"

    @classmethod
    def all(cls) -> List[str]:
        """Get all status codes"""
        return [
            cls.PENDING,
            cls.ALLOWED,
            cls.PATENTED,
            cls.ABANDONED,
            cls.REJECTED
        ]


class SearchStrategy:
    """Constants for inventor search strategies"""

    EXACT = "exact"
    FUZZY = "fuzzy"
    COMPREHENSIVE = "comprehensive"

    @classmethod
    def all(cls) -> List[str]:
        """Get all valid search strategies"""
        return [cls.EXACT, cls.FUZZY, cls.COMPREHENSIVE]

    @classmethod
    def is_valid(cls, strategy: str) -> bool:
        """Check if a search strategy is valid"""
        return strategy.lower() in [s.lower() for s in cls.all()]


class MimeType:
    """MIME type constants for document downloads"""

    PDF = "PDF"
    XML = "XML"
    JSON = "JSON"
    TEXT = "TEXT"

    @classmethod
    def all(cls) -> List[str]:
        """Get all MIME types"""
        return [cls.PDF, cls.XML, cls.JSON, cls.TEXT]


class CircuitBreakerState:
    """Circuit breaker state constants"""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class ErrorType:
    """Error type constants for consistent error categorization"""

    VALIDATION_ERROR = "validation_error"
    AUTHENTICATION_ERROR = "authentication_error"
    AUTHORIZATION_ERROR = "authorization_error"
    NOT_FOUND_ERROR = "not_found_error"
    TIMEOUT_ERROR = "timeout_error"
    RATE_LIMIT_ERROR = "rate_limit_error"
    USPTO_API_ERROR = "uspto_api_error"
    UNEXPECTED_ERROR = "unexpected_error"
