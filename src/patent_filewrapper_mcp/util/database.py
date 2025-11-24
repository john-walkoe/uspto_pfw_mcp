"""
Database utilities with security enhancements for SQLite connections.

Provides secure connection management with proper timeouts and security PRAGMAs.
"""
import sqlite3
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def create_secure_connection(db_path: str, timeout: float = 30.0) -> sqlite3.Connection:
    """
    Create a secure SQLite connection with timeouts and security PRAGMAs.

    Args:
        db_path: Path to SQLite database file
        timeout: Connection timeout in seconds (default: 30.0)

    Returns:
        Configured SQLite connection

    Raises:
        sqlite3.OperationalError: If connection fails
    """
    try:
        # Create connection with timeout and thread safety
        conn = sqlite3.connect(
            db_path,
            timeout=timeout,
            check_same_thread=False
        )

        # Configure security and performance PRAGMAs
        conn.execute("PRAGMA busy_timeout = 30000")  # 30 second busy timeout
        conn.execute("PRAGMA journal_mode = WAL")    # Write-Ahead Logging for concurrency
        conn.execute("PRAGMA synchronous = NORMAL")  # Balanced performance/safety
        conn.execute("PRAGMA foreign_keys = ON")     # Enable foreign key constraints
        conn.execute("PRAGMA temp_store = MEMORY")   # Keep temp tables in memory

        # Test connection
        conn.execute("SELECT 1").fetchone()

        logger.debug(f"Secure SQLite connection established: {db_path}")
        return conn

    except sqlite3.OperationalError as e:
        logger.error(f"Failed to create secure SQLite connection to {db_path}: {e}")
        raise
