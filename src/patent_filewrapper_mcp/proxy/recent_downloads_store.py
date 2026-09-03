"""In-memory store for recently generated document download links.

Tracks the last N documents retrieved via PFW_get_document_download and
PFW_get_granted_patent_documents_download. Used by the Recent Downloads MCP App
to display a navigable list of recent document links.

SCOPED BY OWNER (audit M-3). Each entry holds a working
/document/persistent/{hash} URL, which is a tokenless bearer credential. A
single process-global deque handed every caller the last ten documents ANY
caller had fetched, with their application numbers and titles — in a
multi-user OAuth deployment that is one user's research visible to the next.
Entries are keyed by owner and filtered on read; the single-user and stdio
deployments simply have one key and behave exactly as before.
"""
import threading
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


_MAX_ITEMS = 10

#: Owner key used when no identity is available: stdio, PFW_AUTH_MODE=none,
#: and the single-operator deployments. Not a fallback that MIXES identities —
#: a caller with an identity never reads this bucket and vice versa.
_ANONYMOUS_OWNER = "_local"

# Per-owner deques behind one lock. Both event loops in this process reach
# this store from different threads.
_store: Dict[str, deque] = defaultdict(lambda: deque(maxlen=_MAX_ITEMS))
_lock = threading.Lock()


def _owner_key(owner: Optional[str]) -> str:
    owner = (owner or "").strip()
    return owner or _ANONYMOUS_OWNER


def register_download(
    title: str,
    doc_type: str,
    app_number: str,
    proxy_url: str,
    filename: Optional[str] = None,
    owner: Optional[str] = None,
) -> None:
    """Register a newly generated download link.

    Args:
        title: Human-readable document title (e.g. "Non-Final Office Action")
        doc_type: Document code/type (e.g. "CTNF", "claims", "drawings")
        app_number: Patent application number
        proxy_url: The proxied download URL (localhost link)
        filename: Optional suggested filename
        owner: Identity this download belongs to. Omitted outside OAuth mode,
            where the process boundary is the only tenant there is.
    """
    entry = {
        "title": title,
        "doc_type": doc_type,
        "app_number": app_number,
        "proxy_url": proxy_url,
        "filename": filename or "",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    with _lock:
        _store[_owner_key(owner)].appendleft(entry)


def get_recent(n: int = _MAX_ITEMS, owner: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return the most recent download entries for ONE owner (newest first).

    Args:
        n: Maximum number of entries to return (capped at _MAX_ITEMS)
        owner: Identity to read for. Never returns another owner's entries.

    Returns:
        List of download entry dicts
    """
    with _lock:
        return list(_store.get(_owner_key(owner), ()))[:n]


def clear(owner: Optional[str] = None) -> None:
    """Clear stored downloads for one owner, or all of them when owner is
    omitted (mainly for testing)."""
    with _lock:
        if owner is None:
            _store.clear()
        else:
            _store.pop(_owner_key(owner), None)
