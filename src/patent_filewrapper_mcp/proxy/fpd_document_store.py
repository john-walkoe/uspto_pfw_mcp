"""
FPD Document Store for centralized proxy integration

Stores metadata for FPD petition documents to enable centralized downloads
through PFW proxy. This allows FPD MCP to register documents and have them
available through PFW's unified download infrastructure.
"""

import sqlite3
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path
from ..util.database import create_secure_connection

logger = logging.getLogger(__name__)


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
            db_path: Path to SQLite database (default: fpd_documents.db in project root)
        """
        if db_path:
            self.db_path = db_path
        else:
            # Use absolute path in project root for consistent location
            project_root = Path(__file__).parent.parent.parent.parent
            self.db_path = str(project_root / "fpd_documents.db")

        self._init_database()

    def _init_database(self):
        """Initialize SQLite database with FPD document storage schema"""
        try:
            conn = create_secure_connection(self.db_path)
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
            conn.execute("""
                INSERT OR REPLACE INTO fpd_documents
                (petition_id, document_identifier, download_url, api_key, application_number, enhanced_filename, registered_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                petition_id,
                document_identifier,
                download_url,
                api_key,
                application_number,
                enhanced_filename,
                datetime.now()
            ))
            conn.commit()
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
            cursor = conn.execute("""
                SELECT download_url, api_key, application_number, enhanced_filename, registered_at
                FROM fpd_documents
                WHERE petition_id = ? AND document_identifier = ?
            """, (petition_id, document_identifier))

            result = cursor.fetchone()
            conn.close()

            if not result:
                logger.warning(
                    f"FPD document not found: petition_id={petition_id}, "
                    f"doc_id={document_identifier}"
                )
                return None

            download_url, api_key, application_number, enhanced_filename, registered_at = result

            return {
                'petition_id': petition_id,
                'document_identifier': document_identifier,
                'download_url': download_url,
                'api_key': api_key,
                'application_number': application_number,
                'enhanced_filename': enhanced_filename,
                'registered_at': registered_at
            }

        except Exception as e:
            logger.error(f"Error retrieving FPD document: {e}")
            return None

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
