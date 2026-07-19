"""Process-wide EnhancedPatentClient registry (audit F2/F28).

Owns the lazily-initialized shared client so main.py and the tools/ package
do not need import-cycle gymnastics. main.py re-exports these names for
backward compatibility.
"""
from .api.enhanced_client import EnhancedPatentClient
from .shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)

# API client initialization with lazy loading and fallback
# This prevents entire server failure if API client initialization fails
_api_client = None
_api_client_error = None


def get_api_client() -> EnhancedPatentClient:
    """
    Get API client with lazy initialization and error handling

    This function implements lazy initialization to prevent server failure
    if the API client cannot be initialized immediately. It also caches
    initialization errors to avoid repeated failed attempts.

    Returns:
        EnhancedPatentClient instance

    Raises:
        Exception: If API client cannot be initialized (with helpful error message)
    """
    global _api_client, _api_client_error

    if _api_client is not None:
        return _api_client

    # If we've already failed once, return cached error
    if _api_client_error is not None:
        logger.error("API client initialization previously failed - check configuration")
        raise _api_client_error

    try:
        logger.info("Initializing USPTO API client...")
        _api_client = EnhancedPatentClient()
        logger.info("USPTO API client initialized successfully")
        return _api_client
    except Exception as e:
        # Cache the error to avoid repeated failed attempts
        _api_client_error = Exception(
            f"Failed to initialize USPTO API client: {str(e)}. "
            f"Please check:\n"
            f"  1. USPTO_API_KEY environment variable is set\n"
            f"  2. API key is valid (get one from developer.uspto.gov)\n"
            f"  3. Network connectivity to USPTO API\n"
            f"Original error: {type(e).__name__}: {str(e)}"
        )
        logger.exception(f"Failed to initialize API client: {e}")
        raise _api_client_error


# Get initial API client for package manager (with fallback)
try:
    api_client = get_api_client()
except Exception as e:
    logger.warning(f"Could not initialize API client at startup: {e}")
    logger.warning("API client will be initialized on first use")
    api_client = None

def _client() -> EnhancedPatentClient:
    """Single lazy-init seam for the shared API client (audit F28): replaces
    six per-tool `global api_client` boilerplate blocks and is the one place
    a test can inject a fake client."""
    global api_client
    if api_client is None:
        api_client = get_api_client()
    return api_client
