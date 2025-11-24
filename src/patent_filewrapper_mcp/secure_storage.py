"""
Windows DPAPI Secure Storage for USPTO PFW API Keys - LEGACY FORMAT

⚠️ DEPRECATED - Use shared_secure_storage.py for new code ⚠️

This module provides backward compatibility with the FPD MCP's encryption format.
It uses deterministic machine-based entropy for DPAPI operations.

ARCHITECTURAL DECISION:
This module is kept solely for backward compatibility with existing FPD MCP
installations. The encryption format differs from the newer shared_secure_storage.py:

LEGACY FORMAT (this module):
- Uses deterministic machine-derived entropy (platform.node() + platform.machine() + user)
- Stores only encrypted data in file
- Compatible with older FPD MCP format
- File location: ~/.uspto_pfw_secure_keys

NEW FORMAT (shared_secure_storage.py):
- Uses cryptographically secure random entropy (secrets.token_bytes - CWE-330 compliant)
- Stores entropy + encrypted data in file (32 byte entropy header)
- Single-key-per-file architecture for better security isolation
- File locations: ~/.uspto_api_key, ~/.mistral_api_key

MIGRATION PATH:
For new deployments, use shared_secure_storage.py directly.
For existing FPD MCP users, this module allows reading legacy keys.

TODO: Deprecate this module once all users have migrated to the new format.

No PowerShell execution policies or external dependencies required - uses only Python ctypes.
"""

import ctypes
import ctypes.wintypes
import json
import os
import sys
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List

# Import shared DPAPI utilities
from .util.dpapi_utils import DATA_BLOB, get_data_from_blob, is_windows, check_dpapi_available

logger = logging.getLogger(__name__)


def _generate_machine_entropy() -> bytes:
    """
    Generate machine-specific entropy for DPAPI operations.

    Uses machine characteristics (hostname, architecture, user) to create
    deterministic entropy that's consistent for the same user on the same machine.

    This entropy is used by the legacy PFW format for backward compatibility
    with FPD MCP's encryption format.

    Returns:
        16 bytes of entropy derived from machine characteristics

    Note:
        This is deterministic - the same machine/user will always generate
        the same entropy. For new code, use cryptographically secure random
        entropy (see shared_secure_storage.py).
    """
    import hashlib
    import platform

    machine_id = platform.node() + platform.machine() + str(
        os.getuid() if hasattr(os, 'getuid') else os.getlogin()
    )
    entropy_data = hashlib.sha256(f"uspto_pfw_entropy_v2_{machine_id}".encode()).digest()[:16]
    return entropy_data


def encrypt_data(data: bytes, description: str = "USPTO PFW API Key") -> bytes:
    """
    Encrypt data using Windows DPAPI.
    
    Args:
        data: The data to encrypt (API key as bytes)
        description: Optional description for the encrypted data
        
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
    
    # Additional entropy for extra security
    # Use machine-specific entropy for better security while maintaining compatibility
    entropy_data = _generate_machine_entropy()
    entropy = DATA_BLOB()
    entropy.pbData = ctypes.cast(ctypes.create_string_buffer(entropy_data), ctypes.POINTER(ctypes.c_char))
    entropy.cbData = len(entropy_data)
    
    # Call CryptProtectData
    CRYPTPROTECT_UI_FORBIDDEN = 0x01
    result = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(data_in),          # pDataIn
        description,                     # szDataDescr
        ctypes.byref(entropy),          # pOptionalEntropy
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


def decrypt_data(encrypted_data: bytes) -> bytes:
    """
    Decrypt data using Windows DPAPI with support for both PFW and FPD formats.
    
    Args:
        encrypted_data: The encrypted data to decrypt
        
    Returns:
        Decrypted data as bytes
        
    Raises:
        OSError: If decryption fails
        RuntimeError: If not running on Windows
    """
    if sys.platform != "win32":
        raise RuntimeError("DPAPI is only available on Windows")
    
    # Try FPD format first (entropy-prefixed format)
    if len(encrypted_data) >= 32:
        try:
            return _decrypt_fpd_format(encrypted_data)
        except OSError:
            # Fall back to legacy PFW format
            pass
    
    # Fall back to legacy PFW format
    return _decrypt_pfw_format(encrypted_data)


def _decrypt_fpd_format(encrypted_data: bytes) -> bytes:
    """Decrypt data using FPD format (entropy + encrypted_data)."""
    # Extract entropy (first 32 bytes) and actual encrypted data
    entropy_data = encrypted_data[:32]
    actual_encrypted_data = encrypted_data[32:]
    
    # Prepare input data blob with actual encrypted data
    data_in = DATA_BLOB()
    data_in.pbData = ctypes.cast(ctypes.create_string_buffer(actual_encrypted_data), ctypes.POINTER(ctypes.c_char))
    data_in.cbData = len(actual_encrypted_data)
    
    # Prepare output data blob
    data_out = DATA_BLOB()
    
    # Prepare entropy blob with extracted entropy
    entropy = DATA_BLOB()
    entropy.pbData = ctypes.cast(ctypes.create_string_buffer(entropy_data), ctypes.POINTER(ctypes.c_char))
    entropy.cbData = len(entropy_data)
    
    # Prepare description pointer
    description_ptr = ctypes.wintypes.LPWSTR()
    
    # Call CryptUnprotectData
    CRYPTPROTECT_UI_FORBIDDEN = 0x01
    result = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(data_in),          # pDataIn
        ctypes.byref(description_ptr),  # ppszDataDescr
        ctypes.byref(entropy),          # pOptionalEntropy
        None,                           # pvReserved
        None,                           # pPromptStruct
        CRYPTPROTECT_UI_FORBIDDEN,      # dwFlags
        ctypes.byref(data_out)          # pDataOut
    )
    
    if not result:
        error_code = ctypes.windll.kernel32.GetLastError()
        raise OSError(f"FPD format decryption failed with error code: {error_code}")
    
    # Clean up description
    if description_ptr.value:
        ctypes.windll.kernel32.LocalFree(description_ptr)
    
    # Extract decrypted data
    return get_data_from_blob(data_out)


def _decrypt_pfw_format(encrypted_data: bytes) -> bytes:
    """Decrypt data using legacy PFW format."""
    # Prepare input data blob
    data_in = DATA_BLOB()
    data_in.pbData = ctypes.cast(ctypes.create_string_buffer(encrypted_data), ctypes.POINTER(ctypes.c_char))
    data_in.cbData = len(encrypted_data)
    
    # Prepare output data blob
    data_out = DATA_BLOB()
    
    # Same entropy used for encryption
    # Use machine-specific entropy for better security while maintaining compatibility
    entropy_data = _generate_machine_entropy()
    entropy = DATA_BLOB()
    entropy.pbData = ctypes.cast(ctypes.create_string_buffer(entropy_data), ctypes.POINTER(ctypes.c_char))
    entropy.cbData = len(entropy_data)
    
    # Prepare description pointer
    description_ptr = ctypes.wintypes.LPWSTR()
    
    # Call CryptUnprotectData
    CRYPTPROTECT_UI_FORBIDDEN = 0x01
    result = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(data_in),          # pDataIn
        ctypes.byref(description_ptr),  # ppszDataDescr
        ctypes.byref(entropy),          # pOptionalEntropy
        None,                           # pvReserved
        None,                           # pPromptStruct
        CRYPTPROTECT_UI_FORBIDDEN,      # dwFlags
        ctypes.byref(data_out)          # pDataOut
    )
    
    if not result:
        error_code = ctypes.windll.kernel32.GetLastError()
        raise OSError(f"PFW format decryption failed with error code: {error_code}")
    
    # Clean up description
    if description_ptr.value:
        ctypes.windll.kernel32.LocalFree(description_ptr)
    
    # Extract decrypted data
    return get_data_from_blob(data_out)


class SecureStorage:
    """
    Enhanced secure storage manager for USPTO API keys using Windows DPAPI.
    
    Features:
    - Windows DPAPI encryption with fallback to environment variables
    - Enhanced API key validation with format checking
    - Key rotation support with audit logging
    - Multi-key management with metadata tracking
    - Secure audit logging without exposing sensitive data
    """
    
    def __init__(self, storage_file: Optional[str] = None):
        """
        Initialize secure storage.
        
        Args:
            storage_file: Path to storage file. Defaults to user profile location.
        """
        if storage_file is None:
            storage_file = os.path.join(os.path.expanduser("~"), ".uspto_pfw_secure_keys")
        
        self.storage_file = Path(storage_file)
        self._audit_log = []  # In-memory audit log for session
    
    def store_api_key(self, api_key: str, key_name: str = "USPTO_API_KEY") -> bool:
        """
        Store API key securely using Windows DPAPI.
        
        Args:
            api_key: The API key to store
            key_name: Name of the key (USPTO_API_KEY or MISTRAL_API_KEY)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if sys.platform != "win32":
                # Fall back to environment variable on non-Windows
                return False
            
            # Enhanced validation using new validation method
            validation_result = self._validate_api_key(api_key, key_name)
            if not validation_result['valid']:
                self._log_audit_event('validation_failed', key_name, validation_result['reason'])
                raise ValueError(f"Invalid {key_name}: {validation_result['reason']}")
            
            # Load existing keys or create new structure
            keys_data = self._load_keys_data()
            
            # Add/update the key
            keys_data[key_name] = api_key
            
            # Encrypt the entire keys structure
            json_data = json.dumps(keys_data)
            encrypted_data = encrypt_data(json_data.encode('utf-8'))
            
            # Write to file
            self.storage_file.write_bytes(encrypted_data)
            
            # Set restrictive permissions (Windows)
            os.chmod(self.storage_file, 0o600)
            
            # Log successful key storage (without exposing key data)
            self._log_audit_event('key_stored', key_name, 'Successfully stored encrypted key')
            
            return True
            
        except Exception:
            return False
    
    def get_api_key(self, key_name: str = "USPTO_API_KEY") -> Optional[str]:
        """
        Retrieve API key from secure storage.
        
        Args:
            key_name: Name of the key to retrieve (USPTO_API_KEY or MISTRAL_API_KEY)
        
        Returns:
            The decrypted API key, or None if not found/failed
        """
        try:
            if sys.platform != "win32":
                # Fall back to environment variable on non-Windows
                env_key = os.environ.get(key_name)
                if env_key:
                    validation = self._validate_api_key(env_key, key_name)
                    return env_key if validation['valid'] else None
                return None
            
            if not self.storage_file.exists():
                # Fall back to environment variable if no secure storage
                env_key = os.environ.get(key_name)
                if env_key:
                    validation = self._validate_api_key(env_key, key_name)
                    return env_key if validation['valid'] else None
                return None
            
            # Load and decrypt all keys
            keys_data = self._load_keys_data()
            
            # Return the requested key or fall back to environment variable
            if key_name in keys_data:
                return keys_data[key_name]
            else:
                env_key = os.environ.get(key_name)
                if env_key:
                    validation = self._validate_api_key(env_key, key_name)
                    return env_key if validation['valid'] else None
                return None
                
        except Exception:
            # Fall back to environment variable on any error
            env_key = os.environ.get(key_name)
            if env_key:
                validation = self._validate_api_key(env_key, key_name)
                return env_key if validation['valid'] else None
            return None
    
    def _load_keys_data(self) -> Dict[str, str]:
        """Load and decrypt the keys data structure."""
        try:
            if not self.storage_file.exists():
                return {}
            
            # Read and decrypt encrypted data
            encrypted_data = self.storage_file.read_bytes()
            decrypted_data = decrypt_data(encrypted_data)
            json_data = decrypted_data.decode('utf-8')
            
            # Parse JSON
            keys_data = json.loads(json_data)
            
            # Validate it's a dictionary
            if not isinstance(keys_data, dict):
                return {}
                
            return keys_data
            
        except Exception:
            return {}
    
    def has_secure_key(self, key_name: str = "USPTO_API_KEY") -> bool:
        """
        Check if a secure key is stored.
        
        Args:
            key_name: Name of the key to check
        
        Returns:
            True if secure key exists and can be decrypted
        """
        try:
            api_key = self.get_api_key(key_name)
            return api_key is not None and len(api_key) >= 10
        except Exception:
            return False
    
    def remove_secure_key(self) -> bool:
        """
        Remove the secure key file.
        
        Returns:
            True if successful or file doesn't exist
        """
        try:
            if self.storage_file.exists():
                self.storage_file.unlink()
            return True
        except Exception:
            return False
    
    def _validate_api_key(self, api_key: str, key_name: str) -> Dict[str, any]:
        """
        Enhanced API key validation with format checking
        
        Args:
            api_key: The API key to validate
            key_name: Name of the key for context-specific validation
            
        Returns:
            Dict with validation result and reason
        """
        if not api_key:
            return {'valid': False, 'reason': 'API key is empty'}
        
        if len(api_key) < 10:
            return {'valid': False, 'reason': 'API key too short (minimum 10 characters)'}
        
        if len(api_key) > 200:
            return {'valid': False, 'reason': 'API key too long (maximum 200 characters)'}
        
        # Key-specific validation
        if key_name == "USPTO_API_KEY":
            # USPTO API keys are exactly 30 lowercase letters
            if len(api_key) != 30:
                return {'valid': False, 'reason': 'USPTO API key should be exactly 30 characters'}

            if not re.match(r'^[a-z]+$', api_key):
                return {'valid': False, 'reason': 'USPTO API key should contain only lowercase letters'}
                
        elif key_name == "MISTRAL_API_KEY":
            # Mistral API keys are typically 32 alphanumeric characters
            if len(api_key) != 32:
                return {'valid': False, 'reason': 'Mistral API key should be 32 characters'}

            if not re.match(r'^[a-zA-Z0-9]+$', api_key):
                return {'valid': False, 'reason': 'Mistral API key should contain only alphanumeric characters'}
                
        elif key_name == "PROXY_ENCRYPTION_KEY":
            # Encryption keys should be base64
            try:
                import base64
                base64.b64decode(api_key.encode('utf-8'))
            except Exception:
                return {'valid': False, 'reason': 'Encryption key is not valid base64'}
        
        # Check for common mistakes
        if api_key.lower() in ['your_api_key_here', 'insert_key_here', 'api_key', 'key']:
            return {'valid': False, 'reason': 'API key appears to be a placeholder value'}
        
        if api_key.startswith(('http://', 'https://')):
            return {'valid': False, 'reason': 'API key should not be a URL'}
        
        return {'valid': True, 'reason': 'API key validation passed'}
    
    def _log_audit_event(self, event_type: str, key_name: str, message: str):
        """
        Log security audit events without exposing sensitive data
        
        Args:
            event_type: Type of security event (key_stored, validation_failed, etc.)
            key_name: Name of the key (without the actual key value)
            message: Security event description
        """
        audit_entry = {
            'timestamp': datetime.now().isoformat(),
            'event_type': event_type,
            'key_name': key_name,
            'message': message,
            'platform': sys.platform
        }
        
        # Add to in-memory audit log
        self._audit_log.append(audit_entry)
        
        # Log to standard logger (without sensitive data)
        logger.info(f"SecureStorage audit: {event_type} for {key_name} - {message}")
        
        # Keep only last 100 entries to prevent memory bloat
        if len(self._audit_log) > 100:
            self._audit_log = self._audit_log[-50:]  # Keep last 50
    
    def get_audit_log(self) -> List[Dict]:
        """
        Get audit log for security monitoring
        
        Returns:
            List of audit events (no sensitive data included)
        """
        return self._audit_log.copy()
    
    def rotate_api_key(self, old_key: str, new_key: str, key_name: str = "USPTO_API_KEY") -> bool:
        """
        Securely rotate an API key with validation and audit logging
        
        Args:
            old_key: Current API key for verification
            new_key: New API key to store
            key_name: Name of the key to rotate
            
        Returns:
            True if rotation successful, False otherwise
        """
        try:
            # Verify current key matches stored key
            stored_key = self.get_api_key(key_name)
            if not stored_key or stored_key != old_key:
                self._log_audit_event('rotation_failed', key_name, 'Current key verification failed')
                return False
            
            # Validate new key
            validation_result = self._validate_api_key(new_key, key_name)
            if not validation_result['valid']:
                self._log_audit_event('rotation_failed', key_name, f'New key validation failed: {validation_result["reason"]}')
                return False
            
            # Store new key
            if self.store_api_key(new_key, key_name):
                self._log_audit_event('key_rotated', key_name, 'API key successfully rotated')
                return True
            else:
                self._log_audit_event('rotation_failed', key_name, 'Failed to store new key')
                return False
                
        except Exception as e:
            self._log_audit_event('rotation_failed', key_name, f'Exception during rotation: {str(e)}')
            return False
    
    def list_stored_keys(self) -> List[str]:
        """
        List all stored key names (without exposing the actual keys)
        
        Returns:
            List of key names that are currently stored
        """
        try:
            keys_data = self._load_keys_data()
            return list(keys_data.keys())
        except Exception:
            return []
    
    def get_storage_stats(self) -> Dict[str, any]:
        """
        Get storage statistics for monitoring
        
        Returns:
            Dict with storage statistics (no sensitive data)
        """
        try:
            return {
                'storage_file_exists': self.storage_file.exists(),
                'storage_file_path': str(self.storage_file),
                'platform': sys.platform,
                'stored_keys_count': len(self.list_stored_keys()),
                'audit_events_count': len(self._audit_log),
                'recent_audit_events': self._audit_log[-5:] if self._audit_log else []
            }
        except Exception as e:
            return {'error': str(e)}


def get_secure_api_key(key_name: str = "USPTO_API_KEY") -> Optional[str]:
    """
    Convenience function to get API key from secure storage.
    
    Args:
        key_name: Name of the key to retrieve (USPTO_API_KEY or MISTRAL_API_KEY)
    
    Returns:
        The API key, or None if not available
    """
    storage = SecureStorage()
    return storage.get_api_key(key_name)


def store_secure_api_key(api_key: str, key_name: str = "USPTO_API_KEY") -> bool:
    """
    Convenience function to store API key securely.
    
    Args:
        api_key: The API key to store
        key_name: Name of the key (USPTO_API_KEY or MISTRAL_API_KEY)
        
    Returns:
        True if successful
    """
    storage = SecureStorage()
    return storage.store_api_key(api_key, key_name)


if __name__ == "__main__":
    # Simple test/demo
    if len(sys.argv) > 1:
        if sys.argv[1] == "test":
            # Test encryption/decryption
            test_data = "test_uspto_key_123456789"
            print("Testing DPAPI encryption/decryption...")
            
            try:
                encrypted = encrypt_data(test_data.encode('utf-8'))
                print(f"Encrypted: {len(encrypted)} bytes")
                
                decrypted = decrypt_data(encrypted)
                decrypted_str = decrypted.decode('utf-8')
                print(f"Decrypted: {decrypted_str}")
                
                if decrypted_str == test_data:
                    print("[SUCCESS] DPAPI test PASSED")
                else:
                    print("[FAILED] DPAPI test FAILED")
                    
            except Exception as e:
                print(f"[FAILED] DPAPI test FAILED: {e}")
                
        elif sys.argv[1] == "store":
            if len(sys.argv) > 2:
                success = store_secure_api_key(sys.argv[2])
                print("[SUCCESS] API key stored securely" if success else "[FAILED] Failed to store API key")
            else:
                print("Usage: python secure_storage.py store <api_key>")
                
        elif sys.argv[1] == "get":
            api_key = get_secure_api_key()
            if api_key:
                print(f"API key: {api_key[:10]}...")
            else:
                print("No API key found")
                
    else:
        print("Usage:")
        print("  python secure_storage.py test     - Test DPAPI functionality")
        print("  python secure_storage.py store <key> - Store API key")
        print("  python secure_storage.py get      - Retrieve API key")