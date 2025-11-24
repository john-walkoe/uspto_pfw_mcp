"""
PTAB Document Store for centralized proxy integration

Stores metadata for PTAB proceeding documents to enable centralized downloads
through PFW proxy when PTAB moves to USPTO Open Data Portal. This allows
future PTAB MCP to register documents and have them available through PFW's
unified download infrastructure.

Architecture: Follows the same pattern as FPD integration for consistency.
"""

import sqlite3
import logging
import re
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path
from ..util.database import create_secure_connection

logger = logging.getLogger(__name__)


class PTABDocumentStore:
    """
    Storage for PTAB proceeding document metadata

    Features:
    - Register PTAB documents for centralized proxy downloads
    - Store USPTO API download URLs and credentials
    - Track registration timestamps and proceeding metadata
    - Enable unified download experience across USPTO MCPs
    - Support for multiple proceeding types (IPR, PGR, CBM, DER)
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize PTAB document store

        Args:
            db_path: Path to SQLite database (default: ptab_documents.db in project root)
        """
        if db_path:
            self.db_path = db_path
        else:
            # Use absolute path in project root for consistent location
            project_root = Path(__file__).parent.parent.parent.parent
            self.db_path = str(project_root / "ptab_documents.db")

        self._init_database()

    def _init_database(self):
        """Initialize SQLite database with PTAB document storage schema"""
        try:
            conn = create_secure_connection(self.db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ptab_documents (
                    proceeding_number TEXT NOT NULL,
                    document_identifier TEXT NOT NULL,
                    download_url TEXT NOT NULL,
                    api_key TEXT NOT NULL,
                    patent_number TEXT,
                    application_number TEXT,
                    proceeding_type TEXT,
                    document_type TEXT,
                    enhanced_filename TEXT,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (proceeding_number, document_identifier)
                )
            """)

            # Create index for efficient lookups
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_proceeding_number ON ptab_documents(proceeding_number)
            """)

            # Create index for patent number cross-references
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_patent_number ON ptab_documents(patent_number)
            """)

            # Create index for application number cross-references
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ptab_application_number ON ptab_documents(application_number)
            """)

            # Create index for proceeding type filtering
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_proceeding_type ON ptab_documents(proceeding_type)
            """)

            conn.commit()
            conn.close()
            logger.info(f"Initialized PTAB document store database: {self.db_path}")

        except Exception as e:
            logger.error(f"Failed to initialize PTAB document store: {e}")
            raise

    def register_document(
        self,
        proceeding_number: str,
        document_identifier: str,
        download_url: str,
        api_key: str,
        patent_number: Optional[str] = None,
        application_number: Optional[str] = None,
        proceeding_type: Optional[str] = None,
        document_type: Optional[str] = None,
        enhanced_filename: Optional[str] = None
    ) -> bool:
        """
        Register PTAB document for centralized proxy downloads

        Args:
            proceeding_number: PTAB proceeding number (AIA Trial: 'IPR2025-00895', Appeal: '2025000950')
            document_identifier: Document identifier from PTAB API
            download_url: Full USPTO API download URL for the document
            api_key: USPTO API key for authentication
            patent_number: Patent number being challenged (for cross-reference)
            application_number: Application number (for PFW cross-reference)
            proceeding_type: Type of proceeding (IPR, PGR, CBM, DER)
            document_type: Type of document (petition, response, decision, etc.)
            enhanced_filename: Enhanced human-readable filename

        Returns:
            True if registration successful
        """
        try:
            conn = create_secure_connection(self.db_path)
            conn.execute("""
                INSERT OR REPLACE INTO ptab_documents
                (proceeding_number, document_identifier, download_url, api_key, 
                 patent_number, application_number, proceeding_type, document_type,
                 enhanced_filename, registered_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                proceeding_number,
                document_identifier,
                download_url,
                api_key,
                patent_number,
                application_number,
                proceeding_type,
                document_type,
                enhanced_filename,
                datetime.now()
            ))
            conn.commit()
            conn.close()

            logger.info(
                f"Registered PTAB document: proceeding={proceeding_number}, "
                f"doc_id={document_identifier}, patent={patent_number}, "
                f"app_number={application_number}, type={proceeding_type}, "
                f"enhanced_filename={enhanced_filename}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to register PTAB document: {e}")
            return False

    def get_document(
        self,
        proceeding_number: str,
        document_identifier: str
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve PTAB document metadata for download

        Args:
            proceeding_number: PTAB proceeding number (AIA Trial: 'IPR2025-00895', Appeal: '2025000950')
            document_identifier: Document identifier

        Returns:
            Dict with download_url, api_key, and metadata, or None if not found
        """
        try:
            conn = create_secure_connection(self.db_path)
            cursor = conn.execute("""
                SELECT download_url, api_key, patent_number, application_number, 
                       proceeding_type, document_type, enhanced_filename, registered_at
                FROM ptab_documents
                WHERE proceeding_number = ? AND document_identifier = ?
            """, (proceeding_number, document_identifier))

            result = cursor.fetchone()
            conn.close()

            if not result:
                logger.warning(
                    f"PTAB document not found: proceeding={proceeding_number}, "
                    f"doc_id={document_identifier}"
                )
                return None

            (download_url, api_key, patent_number, application_number, 
             proceeding_type, document_type, enhanced_filename, registered_at) = result

            return {
                'proceeding_number': proceeding_number,
                'document_identifier': document_identifier,
                'download_url': download_url,
                'api_key': api_key,
                'patent_number': patent_number,
                'application_number': application_number,
                'proceeding_type': proceeding_type,
                'document_type': document_type,
                'enhanced_filename': enhanced_filename,
                'registered_at': registered_at
            }

        except Exception as e:
            logger.error(f"Error retrieving PTAB document: {e}")
            return None

    def is_ptab_proceeding_number(self, identifier: str) -> bool:
        """
        Check if identifier matches PTAB proceeding number pattern

        PTAB proceeding numbers have formats:
        - AIA Trials: IPR2025-00895, PGR2025-00456, CBM2025-00789, DER2025-00012
        - Appeals: 2025000950 (10-digit numeric)

        Args:
            identifier: String to check

        Returns:
            True if matches PTAB proceeding pattern
        """
        # AIA Trials: TYPE[4-digit-year]-[5-digit-number]
        aia_trial_pattern = r'^(IPR|PGR|CBM|DER)\d{4}-\d{5}$'
        if re.match(aia_trial_pattern, identifier.upper()):
            return True
        
        # Appeals: 10-digit numeric (e.g., 2025000950)
        appeal_pattern = r'^\d{10}$'
        if re.match(appeal_pattern, identifier):
            return True
        
        return False

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get PTAB document store statistics

        Returns:
            Dict with statistics about registered documents
        """
        try:
            conn = create_secure_connection(self.db_path)

            # Total documents
            cursor = conn.execute("SELECT COUNT(*) FROM ptab_documents")
            total_documents = cursor.fetchone()[0]

            # Unique proceedings
            cursor = conn.execute("SELECT COUNT(DISTINCT proceeding_number) FROM ptab_documents")
            unique_proceedings = cursor.fetchone()[0]

            # Documents by proceeding type
            cursor = conn.execute("""
                SELECT proceeding_type, COUNT(*) 
                FROM ptab_documents 
                WHERE proceeding_type IS NOT NULL
                GROUP BY proceeding_type
            """)
            by_type = dict(cursor.fetchall())

            # Documents with patent numbers
            cursor = conn.execute(
                "SELECT COUNT(*) FROM ptab_documents WHERE patent_number IS NOT NULL"
            )
            with_patent_numbers = cursor.fetchone()[0]

            # Documents with application numbers
            cursor = conn.execute(
                "SELECT COUNT(*) FROM ptab_documents WHERE application_number IS NOT NULL"
            )
            with_app_numbers = cursor.fetchone()[0]

            # Most recent registration
            cursor = conn.execute("""
                SELECT proceeding_number, document_identifier, proceeding_type, registered_at
                FROM ptab_documents
                ORDER BY registered_at DESC
                LIMIT 1
            """)
            most_recent = cursor.fetchone()

            conn.close()

            return {
                'total_documents': total_documents,
                'unique_proceedings': unique_proceedings,
                'by_proceeding_type': by_type,
                'with_patent_numbers': with_patent_numbers,
                'with_application_numbers': with_app_numbers,
                'most_recent': {
                    'proceeding_number': most_recent[0] if most_recent else None,
                    'document_identifier': most_recent[1] if most_recent else None,
                    'proceeding_type': most_recent[2] if most_recent else None,
                    'registered_at': most_recent[3] if most_recent else None
                } if most_recent else None,
                'database_path': self.db_path
            }

        except Exception as e:
            logger.error(f"Error getting PTAB document store stats: {e}")
            return {'error': str(e)}

    def get_documents_by_patent(self, patent_number: str) -> list[Dict[str, Any]]:
        """
        Get all PTAB documents for a specific patent number
        
        Useful for cross-MCP workflows between PTAB and PFW.
        
        Args:
            patent_number: Patent number to search for
            
        Returns:
            List of document metadata dicts
        """
        try:
            conn = create_secure_connection(self.db_path)
            cursor = conn.execute("""
                SELECT proceeding_number, document_identifier, proceeding_type, 
                       document_type, enhanced_filename, registered_at
                FROM ptab_documents
                WHERE patent_number = ?
                ORDER BY registered_at DESC
            """, (patent_number,))
            
            results = cursor.fetchall()
            conn.close()
            
            return [
                {
                    'proceeding_number': row[0],
                    'document_identifier': row[1],
                    'proceeding_type': row[2],
                    'document_type': row[3],
                    'enhanced_filename': row[4],
                    'registered_at': row[5],
                    'patent_number': patent_number
                }
                for row in results
            ]
            
        except Exception as e:
            logger.error(f"Error getting PTAB documents by patent: {e}")
            return []

    def get_documents_by_application(self, application_number: str) -> list[Dict[str, Any]]:
        """
        Get all PTAB documents for a specific application number
        
        Useful for cross-MCP workflows between PTAB and PFW.
        
        Args:
            application_number: Application number to search for
            
        Returns:
            List of document metadata dicts
        """
        try:
            conn = create_secure_connection(self.db_path)
            cursor = conn.execute("""
                SELECT proceeding_number, document_identifier, proceeding_type, 
                       document_type, enhanced_filename, registered_at, patent_number
                FROM ptab_documents
                WHERE application_number = ?
                ORDER BY registered_at DESC
            """, (application_number,))
            
            results = cursor.fetchall()
            conn.close()
            
            return [
                {
                    'proceeding_number': row[0],
                    'document_identifier': row[1],
                    'proceeding_type': row[2],
                    'document_type': row[3],
                    'enhanced_filename': row[4],
                    'registered_at': row[5],
                    'patent_number': row[6],
                    'application_number': application_number
                }
                for row in results
            ]
            
        except Exception as e:
            logger.error(f"Error getting PTAB documents by application: {e}")
            return []


# Global store instance
_ptab_store = None


def get_ptab_store() -> PTABDocumentStore:
    """Get global PTAB document store instance"""
    global _ptab_store
    if _ptab_store is None:
        _ptab_store = PTABDocumentStore()
    return _ptab_store