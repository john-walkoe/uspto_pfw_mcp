"""
Windows DPAPI Utility Functions and Structures

Shared DPAPI operations for all secure storage implementations.
This module provides a single source of truth for DPAPI-related
structures and helper functions, eliminating duplication across
secure_storage.py and shared_secure_storage.py.
"""

import ctypes
import ctypes.wintypes
import sys
from typing import Optional


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
        ('cbData', ctypes.wintypes.DWORD),
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
