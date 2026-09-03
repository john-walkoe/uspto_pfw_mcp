"""MCP App HTML views for USPTO Patent File Wrapper MCP."""
from .views import SEARCH_RESULTS_HTML, XML_VIEW_HTML, DOWNLOADS_HTML, FAMILY_VIEW_HTML
from .user_management_view import USER_MANAGEMENT_HTML

__all__ = [
    "SEARCH_RESULTS_HTML",
    "XML_VIEW_HTML",
    "DOWNLOADS_HTML",
    "FAMILY_VIEW_HTML",
    "USER_MANAGEMENT_HTML",
]
