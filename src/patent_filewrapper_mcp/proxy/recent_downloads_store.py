"""In-memory store for recently generated document download links.

Tracks the last N documents retrieved via pfw_get_document_download and
pfw_get_granted_patent_documents_download. Used by the Recent Downloads MCP App
to display a navigable list of recent document links.
"""
import threading
from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Optional


_MAX_ITEMS = 10

# Module-level singleton with thread lock
_store: deque = deque(maxlen=_MAX_ITEMS)
_lock = threading.Lock()


def register_download(
    title: str,
    doc_type: str,
    app_number: str,
    proxy_url: str,
    filename: Optional[str] = None,
) -> None:
    """Register a newly generated download link.

    Args:
        title: Human-readable document title (e.g. "Non-Final Office Action")
        doc_type: Document code/type (e.g. "CTNF", "claims", "drawings")
        app_number: Patent application number
        proxy_url: The proxied download URL (localhost link)
        filename: Optional suggested filename
    """
    entry = {
        "title": title,
        "doc_type": doc_type,
        "app_number": app_number,
        "proxy_url": proxy_url,
        "filename": filename or "",
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }
    with _lock:
        _store.appendleft(entry)


def get_recent(n: int = _MAX_ITEMS) -> List[Dict[str, Any]]:
    """Return the most recent download entries (newest first).

    Args:
        n: Maximum number of entries to return (capped at _MAX_ITEMS)

    Returns:
        List of download entry dicts
    """
    with _lock:
        return list(_store)[:n]


def clear() -> None:
    """Clear all stored downloads (mainly for testing)."""
    with _lock:
        _store.clear()
