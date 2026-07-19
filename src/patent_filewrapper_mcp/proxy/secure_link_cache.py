"""
Secure SQLite persistent link cache for USPTO document downloads

Provides encrypted persistent download links that work for configurable duration
while keeping all sensitive data encrypted and API keys secure.

Key management is owned by shared/fernet_key_store.py (audit F7/M1): DPAPI
on Windows, systemd-creds (user+machine bound) on Linux, 0600 data-dir file
as last resort.
"""


import hashlib
import secrets
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from ..util.database import create_secure_connection
from ..shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)


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
            # Hardened data dir (0700), migrating any legacy project-root
            # copy (audit L14)
            from ..shared.fernet_key_store import migrate_data_file
            self.db_path = str(migrate_data_file("proxy_link_cache.db"))

        # Key management is owned by shared/fernet_key_store.py (audit F7/M1):
        # DPAPI on Windows, systemd-creds on Linux, 0600 data-dir file last
        from ..shared.fernet_key_store import get_or_create_fernet
        self.cipher = get_or_create_fernet("PROXY_ENCRYPTION_KEY", ".proxy_encryption_key")
        self._init_database()

    def _init_database(self):
        """Initialize SQLite database with encrypted storage design"""
        try:
            conn = create_secure_connection(self.db_path)
            try:
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
            finally:
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
            # Using 24 hex chars (~96 bits of entropy) for collision resistance
            link_hash = hashlib.sha256(encrypted_token.encode('utf-8')).hexdigest()[:24]

            # Calculate expiration time
            expires_at = datetime.now() + self.cache_duration

            # Store in database (only encrypted data, no plaintext)
            conn = create_secure_connection(self.db_path)
            try:
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
            finally:
                conn.close()

            # Return opaque URL (no business data visible)
            persistent_url = f"{base_url}/document/persistent/{link_hash}"

            # Truncated hash only — the full hash is the credential (Lesson 43)
            logger.info(f"Generated persistent link {link_hash[:8]}... for app {app_number}, expires {expires_at}")
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
            try:
                cursor = conn.execute("""
                    SELECT encrypted_token, created_at, access_count, expires_at
                    FROM download_links
                    WHERE link_hash = ? AND expires_at > ?
                """, (link_hash, datetime.now()))

                result = cursor.fetchone()
            finally:
                conn.close()

            if not result:
                logger.warning(f"Persistent link {link_hash[:8]}... not found or expired")
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
                logger.error(f"Failed to decrypt token for link {link_hash[:8]}...: {type(decrypt_error).__name__}")
                # Remove corrupted entry
                self._remove_link(link_hash)
                return None

        except Exception as e:
            logger.error(f"Error resolving persistent link {link_hash[:8]}...: {e}")
            return None

    def _update_access(self, link_hash: str):
        """Update access tracking for a link"""
        try:
            conn = create_secure_connection(self.db_path)
            try:
                conn.execute("""
                    UPDATE download_links
                    SET last_accessed = ?, access_count = access_count + 1
                    WHERE link_hash = ?
                """, (datetime.now(), link_hash))
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"Failed to update access tracking for {link_hash[:8]}...: {e}")

    def _remove_link(self, link_hash: str):
        """Remove a corrupted or invalid link"""
        try:
            conn = create_secure_connection(self.db_path)
            try:
                conn.execute("DELETE FROM download_links WHERE link_hash = ?", (link_hash,))
                conn.commit()
            finally:
                conn.close()
            logger.info(f"Removed corrupted link {link_hash[:8]}...")
        except Exception as e:
            logger.warning(f"Failed to remove link {link_hash[:8]}...: {e}")

    def cleanup_expired_links(self) -> int:
        """
        Clean up expired links from database

        Returns:
            Number of links removed
        """
        try:
            conn = create_secure_connection(self.db_path)
            try:
                cursor = conn.execute("""
                    DELETE FROM download_links
                    WHERE expires_at < ?
                """, (datetime.now(),))
                deleted_count = cursor.rowcount
                conn.commit()
            finally:
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
            try:

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

            finally:
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
