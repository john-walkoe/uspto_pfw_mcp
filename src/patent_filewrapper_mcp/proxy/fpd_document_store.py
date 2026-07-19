"""
FPD Document Store for centralized proxy integration

Stores metadata for FPD petition documents to enable centralized downloads
through PFW proxy. This allows FPD MCP to register documents and have them
available through PFW's unified download infrastructure.

Key management is owned by shared/fernet_key_store.py (audit F7/M1): DPAPI
on Windows, systemd-creds (user+machine bound) on Linux, 0600 data-dir file
as last resort.
"""


from datetime import datetime
from typing import Optional, Dict, Any

from cryptography.fernet import Fernet

from ..util.database import create_secure_connection
from ..shared.safe_logger import get_safe_logger
from ..shared.fernet_key_store import get_or_create_fernet, migrate_data_file

logger = get_safe_logger(__name__)


_fernet_cipher: Optional[Fernet] = None


def _cipher() -> Fernet:
    global _fernet_cipher
    if _fernet_cipher is None:
        _fernet_cipher = get_or_create_fernet("FPD_DOCSTORE_KEY", ".fpd_docstore_key")
    return _fernet_cipher


def _encrypt_api_key(api_key: str) -> str:
    """Encrypt an API key before storing in SQLite."""
    return _cipher().encrypt(api_key.encode("utf-8")).decode("utf-8")


def _decrypt_api_key(encrypted: str) -> str:
    """Decrypt an API key retrieved from SQLite."""
    return _cipher().decrypt(encrypted.encode("utf-8")).decode("utf-8")


def _sanitize_filename(raw: Optional[str]) -> Optional[str]:
    """
    Remove characters from enhanced_filename that could cause header injection
    in Content-Disposition or X-Enhanced-Filename response headers.

    Strips CR/LF and all control characters (0x00-0x1F and 0x7F).
    """
    if not raw:
        return raw
    return "".join(ch for ch in raw if ord(ch) >= 32 and ord(ch) != 127)


class FPDDocumentStore:
    """
    Storage for FPD petition document metadata

    Features:
    - Register FPD documents for centralized proxy downloads
    - Store USPTO API download URLs and credentials
    - Track registration timestamps and application numbers
    - Enable unified download experience across USPTO MCPs
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize FPD document store

        Args:
            db_path: Path to SQLite database (default: fpd_documents.db in
                the hardened data dir — audit L14)
        """
        if db_path:
            self.db_path = db_path
        else:
            self.db_path = str(migrate_data_file("fpd_documents.db"))

        self._init_database()

    def _init_database(self):
        """Initialize SQLite database with FPD document storage schema"""
        try:
            conn = create_secure_connection(self.db_path)
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS fpd_documents (
                        petition_id TEXT NOT NULL,
                        document_identifier TEXT NOT NULL,
                        download_url TEXT NOT NULL,
                        api_key TEXT NOT NULL,
                        application_number TEXT,
                        enhanced_filename TEXT,
                        registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (petition_id, document_identifier)
                    )
                """)

                # Create index for efficient lookups
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_petition_id ON fpd_documents(petition_id)
                """)

                # Create index for application number cross-references
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_application_number ON fpd_documents(application_number)
                """)

                conn.commit()
            finally:
                conn.close()
            logger.info(f"Initialized FPD document store database: {self.db_path}")

        except Exception as e:
            logger.error(f"Failed to initialize FPD document store: {e}")
            raise

    def register_document(
        self,
        petition_id: str,
        document_identifier: str,
        download_url: str,
        api_key: str,
        application_number: Optional[str] = None,
        enhanced_filename: Optional[str] = None
    ) -> bool:
        """
        Register FPD document for centralized proxy downloads

        Args:
            petition_id: Unique petition UUID from FPD
            document_identifier: Document identifier (e.g., 'ABC123')
            download_url: Full USPTO API download URL for the document
            api_key: USPTO API key for authentication
            application_number: Optional application number for cross-reference
            enhanced_filename: Optional enhanced human-readable filename

        Returns:
            True if registration successful
        """
        try:
            conn = create_secure_connection(self.db_path)
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO fpd_documents
                    (petition_id, document_identifier, download_url, api_key, application_number, enhanced_filename, registered_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    petition_id,
                    document_identifier,
                    download_url,
                    _encrypt_api_key(api_key),
                    application_number,
                    _sanitize_filename(enhanced_filename),
                    datetime.now()
                ))
                conn.commit()
            finally:
                conn.close()

            logger.info(
                f"Registered FPD document: petition_id={petition_id}, "
                f"doc_id={document_identifier}, app_number={application_number}, "
                f"enhanced_filename={enhanced_filename}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to register FPD document: {e}")
            return False

    def get_document(
        self,
        petition_id: str,
        document_identifier: str
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve FPD document metadata for download

        Args:
            petition_id: Petition UUID
            document_identifier: Document identifier

        Returns:
            Dict with download_url, api_key, and metadata, or None if not found
        """
        try:
            conn = create_secure_connection(self.db_path)
            try:
                cursor = conn.execute("""
                    SELECT download_url, api_key, application_number, enhanced_filename, registered_at
                    FROM fpd_documents
                    WHERE petition_id = ? AND document_identifier = ?
                """, (petition_id, document_identifier))

                result = cursor.fetchone()
            finally:
                conn.close()

            if not result:
                logger.warning(
                    f"FPD document not found: petition_id={petition_id}, "
                    f"doc_id={document_identifier}"
                )
                return None

            download_url, encrypted_key, application_number, enhanced_filename, registered_at = result

            return {
                'petition_id': petition_id,
                'document_identifier': document_identifier,
                'download_url': download_url,
                'api_key': _decrypt_api_key(encrypted_key),
                'application_number': application_number,
                'enhanced_filename': enhanced_filename,
                'registered_at': registered_at
            }

        except Exception as e:
            logger.error(f"Error retrieving FPD document: {e}")
            return None

    def cleanup_expired_documents(self, max_age_days: int = 7) -> int:
        """Delete registrations older than max_age_days (audit L8): rows hold
        encrypted API keys and should not accumulate indefinitely. Mirrors
        SecureLinkCache.cleanup_expired_links; 7 days matches the persistent
        link lifetime."""
        try:
            conn = create_secure_connection(self.db_path)
            try:
                cursor = conn.execute(
                    "DELETE FROM fpd_documents WHERE registered_at < datetime('now', ?)",
                    (f"-{int(max_age_days)} days",),
                )
                deleted = cursor.rowcount
                conn.commit()
            finally:
                conn.close()
            if deleted > 0:
                logger.info(f"Cleaned up {deleted} expired FPD document registration(s)")
            return deleted
        except Exception as e:
            logger.error(f"Error during FPD document cleanup: {e}")
            return 0

    def is_fpd_petition_id(self, identifier: str) -> bool:
        """
        Check if identifier matches FPD petition UUID pattern

        FPD petition IDs are UUIDs with format: 8-4-4-4-12 hex digits
        Example: 550e8400-e29b-41d4-a716-446655440000

        Args:
            identifier: String to check

        Returns:
            True if matches UUID pattern
        """
        import re
        # UUID v4 pattern
        uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        return bool(re.match(uuid_pattern, identifier.lower()))

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get FPD document store statistics

        Returns:
            Dict with statistics about registered documents
        """
        try:
            conn = create_secure_connection(self.db_path)
            try:

                # Total documents
                cursor = conn.execute("SELECT COUNT(*) FROM fpd_documents")
                total_documents = cursor.fetchone()[0]

                # Unique petitions
                cursor = conn.execute("SELECT COUNT(DISTINCT petition_id) FROM fpd_documents")
                unique_petitions = cursor.fetchone()[0]

                # Documents with application numbers
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM fpd_documents WHERE application_number IS NOT NULL"
                )
                with_app_numbers = cursor.fetchone()[0]

                # Most recent registration
                cursor = conn.execute("""
                    SELECT petition_id, document_identifier, registered_at
                    FROM fpd_documents
                    ORDER BY registered_at DESC
                    LIMIT 1
                """)
                most_recent = cursor.fetchone()

            finally:
                conn.close()

            return {
                'total_documents': total_documents,
                'unique_petitions': unique_petitions,
                'with_application_numbers': with_app_numbers,
                'most_recent': {
                    'petition_id': most_recent[0] if most_recent else None,
                    'document_identifier': most_recent[1] if most_recent else None,
                    'registered_at': most_recent[2] if most_recent else None
                } if most_recent else None,
                'database_path': self.db_path
            }

        except Exception as e:
            logger.error(f"Error getting FPD document store stats: {e}")
            return {'error': str(e)}


# Global store instance
_fpd_store = None


def get_fpd_store() -> FPDDocumentStore:
    """Get global FPD document store instance"""
    global _fpd_store
    if _fpd_store is None:
        _fpd_store = FPDDocumentStore()
    return _fpd_store
