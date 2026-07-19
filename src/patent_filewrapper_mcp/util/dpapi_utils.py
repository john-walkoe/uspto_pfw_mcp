"""
Windows DPAPI Utility Functions and Structures

Shared DPAPI operations for all secure storage implementations.
This module provides a single source of truth for DPAPI-related
structures and helper functions, eliminating duplication across
secure_storage.py and shared_secure_storage.py.
"""

import ctypes
import sys

# wintypes is Windows-only — import lazily so this module can be imported on Linux/macOS
try:
    import ctypes.wintypes
    _WINTYPES_AVAILABLE = True
except ImportError:
    _WINTYPES_AVAILABLE = False


# Use wintypes DWORD if available (Windows), otherwise use ctypes.c_uint32 directly
if _WINTYPES_AVAILABLE:
    _DWORD = ctypes.wintypes.DWORD
else:
    _DWORD = ctypes.c_uint32  # type: ignore[misc]


class DATA_BLOB(ctypes.Structure):
    """
    Windows DATA_BLOB structure for DPAPI operations.

    This structure is used by Windows CryptProtectData and CryptUnprotectData
    functions to pass binary data.

    Fields:
        cbData: Size of data in bytes (DWORD)
        pbData: Pointer to data buffer (POINTER(c_char))
    """
    _fields_ = [
        ('cbData', _DWORD),
        ('pbData', ctypes.POINTER(ctypes.c_char))
    ]


def get_data_from_blob(blob: DATA_BLOB) -> bytes:
    """
    Extract bytes from a DATA_BLOB structure.

    This function safely extracts the binary data from a Windows DATA_BLOB
    structure and frees the memory allocated by Windows DPAPI functions.

    Args:
        blob: DATA_BLOB structure containing encrypted or decrypted data

    Returns:
        Extracted data as bytes, or empty bytes if blob contains no data

    Note:
        This function calls LocalFree to release memory allocated by
        CryptProtectData or CryptUnprotectData. Only call this on blobs
        returned by DPAPI functions.
    """
    if not blob.cbData:
        return b''

    cbData = int(blob.cbData)
    pbData = blob.pbData
    buffer = ctypes.create_string_buffer(cbData)
    ctypes.memmove(buffer, pbData, cbData)
    ctypes.windll.kernel32.LocalFree(pbData)
    return buffer.raw


def is_windows() -> bool:
    """
    Check if running on Windows platform.

    Returns:
        True if running on Windows, False otherwise
    """
    return sys.platform == "win32"


def check_dpapi_available() -> None:
    """
    Check if DPAPI is available, raise RuntimeError if not.

    This should be called before attempting any DPAPI operations
    to provide clear error messages on non-Windows platforms.

    Raises:
        RuntimeError: If not running on Windows

    Example:
        >>> check_dpapi_available()  # On Windows - no error
        >>> check_dpapi_available()  # On Linux - RuntimeError
    """
    if not is_windows():
        raise RuntimeError("DPAPI is only available on Windows")


def create_data_blob(data: bytes) -> DATA_BLOB:
    """
    Create a DATA_BLOB structure from bytes.

    Helper function to create a properly initialized DATA_BLOB
    structure from Python bytes.

    Args:
        data: Binary data to wrap in DATA_BLOB

    Returns:
        DATA_BLOB structure containing the data

    Example:
        >>> blob = create_data_blob(b"my secret data")
        >>> blob.cbData
        14
    """
    blob = DATA_BLOB()
    blob.pbData = ctypes.cast(
        ctypes.create_string_buffer(data),
        ctypes.POINTER(ctypes.c_char)
    )
    blob.cbData = len(data)
    return blob


# LPWSTR is only available on Windows — use a compatible type on other platforms
if _WINTYPES_AVAILABLE:
    _LPWSTR = ctypes.wintypes.LPWSTR  # type: ignore[attr-defined]
else:
    _LPWSTR = ctypes.c_wchar_p  # type: ignore[attr-defined,misc]


def encrypt_with_dpapi(data: bytes, entropy: bytes, description: str = "USPTO MCP API Key") -> bytes:
    """
    Encrypt data using Windows DPAPI with custom entropy.

    Args:
        data: The data to encrypt
        entropy: Custom entropy for additional security
        description: Human-readable description for the data blob

    Returns:
        Encrypted data as bytes

    Raises:
        OSError: If encryption fails
        RuntimeError: If not running on Windows
    """
    if sys.platform != "win32":
        raise RuntimeError("DPAPI is only available on Windows")

    # Prepare input data blob
    data_in = DATA_BLOB()
    data_in.pbData = ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char))
    data_in.cbData = len(data)

    # Prepare output data blob
    data_out = DATA_BLOB()

    # Prepare entropy blob
    entropy_blob = DATA_BLOB()
    entropy_blob.pbData = ctypes.cast(ctypes.create_string_buffer(entropy), ctypes.POINTER(ctypes.c_char))
    entropy_blob.cbData = len(entropy)

    # Call CryptProtectData
    CRYPTPROTECT_UI_FORBIDDEN = 0x01
    result = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(data_in),          # pDataIn
        description,                    # szDataDescr
        ctypes.byref(entropy_blob),     # pOptionalEntropy
        None,                           # pvReserved
        None,                           # pPromptStruct
        CRYPTPROTECT_UI_FORBIDDEN,      # dwFlags
        ctypes.byref(data_out)          # pDataOut
    )

    if not result:
        error_code = ctypes.windll.kernel32.GetLastError()
        raise OSError(f"CryptProtectData failed with error code: {error_code}")

    # Extract encrypted data
    encrypted_data = get_data_from_blob(data_out)
    return encrypted_data


def decrypt_with_dpapi(encrypted_data: bytes, entropy: bytes) -> bytes:
    """
    Decrypt data using Windows DPAPI with custom entropy.

    Args:
        encrypted_data: The encrypted data to decrypt
        entropy: Custom entropy used during encryption

    Returns:
        Decrypted data as bytes

    Raises:
        OSError: If decryption fails
        RuntimeError: If not running on Windows
    """
    if sys.platform != "win32":
        raise RuntimeError("DPAPI is only available on Windows")

    # Prepare input data blob
    data_in = DATA_BLOB()
    data_in.pbData = ctypes.cast(ctypes.create_string_buffer(encrypted_data), ctypes.POINTER(ctypes.c_char))
    data_in.cbData = len(encrypted_data)

    # Prepare output data blob
    data_out = DATA_BLOB()

    # Prepare entropy blob
    entropy_blob = DATA_BLOB()
    entropy_blob.pbData = ctypes.cast(ctypes.create_string_buffer(entropy), ctypes.POINTER(ctypes.c_char))
    entropy_blob.cbData = len(entropy)

    # Prepare description pointer — use _LPWSTR (portable across Windows/Linux/macOS)
    description_ptr = _LPWSTR()

    # Call CryptUnprotectData
    CRYPTPROTECT_UI_FORBIDDEN = 0x01
    result = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(data_in),          # pDataIn
        ctypes.byref(description_ptr),  # ppszDataDescr
        ctypes.byref(entropy_blob),     # pOptionalEntropy
        None,                           # pvReserved
        None,                           # pPromptStruct
        CRYPTPROTECT_UI_FORBIDDEN,      # dwFlags
        ctypes.byref(data_out)          # pDataOut
    )

    if not result:
        error_code = ctypes.windll.kernel32.GetLastError()
        raise OSError(f"CryptUnprotectData failed with error code: {error_code}")

    # Clean up description
    if description_ptr.value:
        ctypes.windll.kernel32.LocalFree(description_ptr)

    # Extract decrypted data
    return get_data_from_blob(data_out)
