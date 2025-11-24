"""
Secure SQLite persistent link cache for USPTO document downloads

Provides encrypted persistent download links that work for configurable duration
while keeping all sensitive data encrypted and API keys secure.
"""

import sqlite3
import hashlib
import secrets
import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from pathlib import Path
from cryptography.fernet import Fernet
from ..util.database import create_secure_connection

logger = logging.getLogger(__name__)


class SecureLinkCache:
    """
    Secure persistent link cache with encryption
    
    Features:
    - Encrypted storage of application numbers and document IDs
    - Opaque URLs that don't reveal business data
    - Configurable link expiration (default 7 days)
    - Automatic cleanup of expired links
    - Windows DPAPI integration for encryption keys
    """
    
    def __init__(self, cache_duration_days: int = 7, db_path: Optional[str] = None):
        """
        Initialize secure link cache
        
        Args:
            cache_duration_days: How long links remain valid (default: 7 days)
            db_path: Path to SQLite database (default: proxy_link_cache.db in project root)
        """
        self.cache_duration = timedelta(days=cache_duration_days)
        
        if db_path:
            self.db_path = db_path
        else:
            # Use absolute path in project root to ensure consistent location
            project_root = Path(__file__).parent.parent.parent.parent
            self.db_path = str(project_root / "proxy_link_cache.db")
        
        self.encryption_key = self._get_or_create_encryption_key()
        self.cipher = Fernet(self.encryption_key)
        self._init_database()
    
    def _get_or_create_encryption_key(self) -> bytes:
        """
        Get encryption key from secure storage or create new one
        
        Leverages existing PFW secure storage infrastructure for Windows DPAPI.
        Falls back to file-based storage for non-Windows systems.
        """
        try:
            # Try to use unified secure storage infrastructure
            from ..shared_secure_storage import get_secure_api_key, store_secure_api_key
            
            # Check if we have a stored encryption key
            stored_key = get_secure_api_key('PROXY_ENCRYPTION_KEY')
            if stored_key:
                # Key is stored as base64 string, convert back to bytes
                import base64
                return base64.b64decode(stored_key.encode('utf-8'))
            else:
                # Generate new encryption key and store securely
                import base64
                key = Fernet.generate_key()
                key_b64 = base64.b64encode(key).decode('utf-8')
                success = store_secure_api_key(key_b64, 'PROXY_ENCRYPTION_KEY')
                
                if success:
                    logger.info("Generated and stored new proxy encryption key via secure storage")
                    return key
                else:
                    # Fall back to file-based storage
                    logger.warning("Secure storage failed, using file-based encryption key")
                    return self._get_file_based_key()
                    
        except ImportError:
            # Fallback for systems without secure storage
            logger.info("Secure storage not available, using file-based encryption key")
            return self._get_file_based_key()
        except Exception as e:
            logger.warning(f"Error accessing secure storage: {e}, using file-based encryption key")
            return self._get_file_based_key()
    
    def _get_file_based_key(self) -> bytes:
        """Fallback file-based encryption key storage for non-Windows systems"""
        # Use same project root as database
        project_root = Path(__file__).parent.parent.parent.parent
        key_file = project_root / ".proxy_encryption_key"
        
        if key_file.exists():
            try:
                with open(key_file, 'rb') as f:
                    return f.read()
            except Exception as e:
                logger.warning(f"Error reading encryption key file: {e}, generating new key")
        
        # Generate new key
        key = Fernet.generate_key()
        try:
            with open(key_file, 'wb') as f:
                f.write(key)
            # Set restrictive permissions (owner read/write only)
            os.chmod(key_file, 0o600)
            logger.info("Generated new file-based encryption key")
        except Exception as e:
            logger.warning(f"Could not save encryption key to file: {e}")
        
        return key
    
    def _init_database(self):
        """Initialize SQLite database with encrypted storage design"""
        try:
            conn = create_secure_connection(self.db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS download_links (
                    link_hash TEXT PRIMARY KEY,           -- Irreversible hash for lookup
                    encrypted_token TEXT,                 -- Fernet-encrypted data
                    created_at TIMESTAMP,                 -- When link was created
                    last_accessed TIMESTAMP,              -- Last access time
                    access_count INTEGER DEFAULT 0,       -- Number of times accessed
                    expires_at TIMESTAMP                  -- When link expires
                )
            """)
            
            # Create index for efficient cleanup of expired links
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_expires_at ON download_links(expires_at)
            """)
            
            # Create index for access tracking
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_created_at ON download_links(created_at)
            """)
            
            conn.commit()
            conn.close()
            logger.info(f"Initialized secure link cache database: {self.db_path}")
            
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise
    
    def generate_persistent_link(self, app_number: str, doc_id: str, base_url: str = "http://localhost:8080") -> str:
        """
        Generate secure persistent link with encrypted storage
        
        Args:
            app_number: Patent application number
            doc_id: Document identifier
            base_url: Base URL for the proxy server
            
        Returns:
            Opaque persistent download URL
        """
        try:
            # Create token with random component to prevent pattern analysis
            timestamp = datetime.now().isoformat()
            random_component = secrets.token_hex(16)
            token_data = json.dumps({
                'app_number': app_number,
                'doc_id': doc_id,
                'timestamp': timestamp,
                'random': random_component
            })
            
            # Encrypt the token
            encrypted_token = self.cipher.encrypt(token_data.encode('utf-8')).decode('utf-8')
            
            # Generate irreversible hash for database lookup
            link_hash = hashlib.sha256(encrypted_token.encode('utf-8')).hexdigest()[:16]
            
            # Calculate expiration time
            expires_at = datetime.now() + self.cache_duration
            
            # Store in database (only encrypted data, no plaintext)
            conn = create_secure_connection(self.db_path)
            conn.execute("""
                INSERT OR REPLACE INTO download_links 
                (link_hash, encrypted_token, created_at, last_accessed, access_count, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                link_hash, 
                encrypted_token, 
                datetime.now(), 
                datetime.now(),
                0,
                expires_at
            ))
            conn.commit()
            conn.close()
            
            # Return opaque URL (no business data visible)
            persistent_url = f"{base_url}/document/persistent/{link_hash}"
            
            logger.info(f"Generated persistent link {link_hash} for app {app_number}, expires {expires_at}")
            return persistent_url
            
        except Exception as e:
            logger.error(f"Failed to generate persistent link: {e}")
            raise
    
    def resolve_persistent_link(self, link_hash: str) -> Optional[Dict[str, Any]]:
        """
        Securely resolve persistent link by decrypting stored token
        
        Args:
            link_hash: The opaque link hash from the URL
            
        Returns:
            Dict with app_number, doc_id, and metadata, or None if invalid/expired
        """
        try:
            conn = create_secure_connection(self.db_path)
            cursor = conn.execute("""
                SELECT encrypted_token, created_at, access_count, expires_at
                FROM download_links 
                WHERE link_hash = ? AND expires_at > ?
            """, (link_hash, datetime.now()))
            
            result = cursor.fetchone()
            conn.close()
            
            if not result:
                logger.warning(f"Persistent link {link_hash} not found or expired")
                return None
                
            encrypted_token, created_at, access_count, expires_at = result
            
            try:
                # Decrypt token to get original data
                decrypted_data = self.cipher.decrypt(encrypted_token.encode('utf-8')).decode('utf-8')
                token_data = json.loads(decrypted_data)
                
                # Update access tracking
                self._update_access(link_hash)
                
                return {
                    'app_number': token_data['app_number'],
                    'doc_id': token_data['doc_id'],
                    'created_at': created_at,
                    'access_count': access_count + 1,
                    'expires_at': expires_at
                }
                
            except Exception as decrypt_error:
                logger.error(f"Failed to decrypt token for link {link_hash}: {decrypt_error}")
                # Remove corrupted entry
                self._remove_link(link_hash)
                return None
                
        except Exception as e:
            logger.error(f"Error resolving persistent link {link_hash}: {e}")
            return None
    
    def _update_access(self, link_hash: str):
        """Update access tracking for a link"""
        try:
            conn = create_secure_connection(self.db_path)
            conn.execute("""
                UPDATE download_links 
                SET last_accessed = ?, access_count = access_count + 1
                WHERE link_hash = ?
            """, (datetime.now(), link_hash))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to update access tracking for {link_hash}: {e}")
    
    def _remove_link(self, link_hash: str):
        """Remove a corrupted or invalid link"""
        try:
            conn = create_secure_connection(self.db_path)
            conn.execute("DELETE FROM download_links WHERE link_hash = ?", (link_hash,))
            conn.commit()
            conn.close()
            logger.info(f"Removed corrupted link {link_hash}")
        except Exception as e:
            logger.warning(f"Failed to remove link {link_hash}: {e}")
    
    def cleanup_expired_links(self) -> int:
        """
        Clean up expired links from database
        
        Returns:
            Number of links removed
        """
        try:
            conn = create_secure_connection(self.db_path)
            cursor = conn.execute("""
                DELETE FROM download_links 
                WHERE expires_at < ?
            """, (datetime.now(),))
            deleted_count = cursor.rowcount
            conn.commit()
            conn.close()
            
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} expired persistent links")
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error during link cleanup: {e}")
            return 0
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics for monitoring
        
        Returns:
            Dict with cache statistics
        """
        try:
            conn = create_secure_connection(self.db_path)
            
            # Total links
            cursor = conn.execute("SELECT COUNT(*) FROM download_links")
            total_links = cursor.fetchone()[0]
            
            # Active (non-expired) links
            cursor = conn.execute("SELECT COUNT(*) FROM download_links WHERE expires_at > ?", (datetime.now(),))
            active_links = cursor.fetchone()[0]
            
            # Total accesses
            cursor = conn.execute("SELECT SUM(access_count) FROM download_links")
            total_accesses = cursor.fetchone()[0] or 0
            
            # Most accessed link
            cursor = conn.execute("""
                SELECT link_hash, access_count, created_at 
                FROM download_links 
                ORDER BY access_count DESC 
                LIMIT 1
            """)
            most_accessed = cursor.fetchone()
            
            conn.close()
            
            return {
                'total_links': total_links,
                'active_links': active_links,
                'expired_links': total_links - active_links,
                'total_accesses': total_accesses,
                'most_accessed': {
                    'hash': most_accessed[0] if most_accessed else None,
                    'count': most_accessed[1] if most_accessed else 0,
                    'created': most_accessed[2] if most_accessed else None
                } if most_accessed else None,
                'cache_duration_days': self.cache_duration.days,
                'database_path': self.db_path
            }
            
        except Exception as e:
            logger.error(f"Error getting cache stats: {e}")
            return {'error': str(e)}


# Global cache instance
_link_cache = None

def get_link_cache() -> SecureLinkCache:
    """Get global secure link cache instance"""
    global _link_cache
    if _link_cache is None:
        _link_cache = SecureLinkCache()
    return _link_cache