"""
Logging configuration for USPTO Patent File Wrapper MCP with file-based audit trail.

Security Features:
- RotatingFileHandler with 10MB max size, 5 backups
- Separate security log file (10 backups for longer retention)
- File permissions set to 600 (owner read/write only) on Unix
- Persistent audit trail for forensic analysis
- SafeLogger integration for automatic sensitive data sanitization
"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path

from ..shared.log_sanitizer import SanitizingFilter


def setup_logging(log_level: str = "INFO") -> None:
    """
    Configure logging for USPTO Patent File Wrapper MCP with file-based audit trail.

    Creates two log files in ~/.uspto_pfw_mcp/logs/:
    - patent_filewrapper_mcp.log: General application logs (10MB max, 5 backups)
    - security.log: Security events only (10MB max, 10 backups for compliance)

    File permissions are set to 600 (owner read/write only) on Unix for security.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    # Create logs directory with secure permissions.
    # LOG_DIR env var overrides the default (useful for Docker volume mounts).
    _log_dir_env = os.environ.get("LOG_DIR", "").strip()
    logs_dir = Path(_log_dir_env) if _log_dir_env else Path.home() / ".uspto_pfw_mcp" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Set directory permissions to 700 (owner only) on Unix
    if hasattr(os, 'chmod'):
        try:
            os.chmod(logs_dir, 0o700)
        except (OSError, PermissionError) as e:
            print(f"Warning: Could not set directory permissions: {e}", file=sys.stderr)

    # Retention is env-configurable (defaults: 10MB, 5 backups)
    max_bytes = int(os.getenv("PFW_LOG_MAX_BYTES", str(10 * 1024 * 1024)))
    backup_count = int(os.getenv("PFW_LOG_BACKUP_COUNT", "5"))

    # Application log file with rotation
    app_log_file = logs_dir / "patent_filewrapper_mcp.log"
    file_handler = logging.handlers.RotatingFileHandler(
        app_log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))

    # NOTE: the 'security' logger and security.log are owned exclusively by
    # util.security_logger.SecurityLogger (JSON format, SanitizingFilter,
    # 10 backups). Attaching a second handler here caused duplicate writes
    # and an unfiltered-handler hazard (audit C1) — do not re-add one.
    security_log_file = logs_dir / "security.log"

    # Console handler for stderr
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))

    # Sink-level sanitization guarantee: every record is scrubbed at the
    # handler regardless of which logger emitted it (library loggers included)
    sanitizing_filter = SanitizingFilter()
    for _sink in (file_handler, console_handler):
        _sink.addFilter(sanitizing_filter)

    # Configure root logger with all handlers
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Add handlers
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Set file permissions to 600 (owner read/write only) - CRITICAL SECURITY
    if hasattr(os, 'chmod'):
        for log_file in [app_log_file, security_log_file]:
            try:
                log_file.touch(exist_ok=True)
                os.chmod(log_file, 0o600)
            except (OSError, PermissionError) as e:
                print(f"Warning: Could not set file permissions on {log_file}: {e}", file=sys.stderr)

    # Log initialization success
    logger = logging.getLogger(__name__)
    logger.info(f"Logging initialized - Application log: {app_log_file}")
    logger.info(f"Security log: {security_log_file}")

    # Suppress noisy libraries (Safe: Only configuring log levels, not logging data)
    # uvicorn.access included: access lines contain request paths, and
    # /document/persistent/{hash} paths embed the link credential
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_log_files() -> dict:
    """
    Get the paths to the log files.

    Returns:
        Dictionary with 'app_log' and 'security_log' paths
    """
    _log_dir_env = os.environ.get("LOG_DIR", "").strip()
    logs_dir = Path(_log_dir_env) if _log_dir_env else Path.home() / ".uspto_pfw_mcp" / "logs"
    return {
        'app_log': logs_dir / "patent_filewrapper_mcp.log",
        'security_log': logs_dir / "security.log",
        'logs_dir': logs_dir
    }


def clear_logs() -> None:
    """
    Clear all log files (useful for testing).

    WARNING: This will delete all log history.
    """
    log_files = get_log_files()
    for log_file in [log_files['app_log'], log_files['security_log']]:
        if log_file.exists():
            log_file.unlink()
    print("Log files cleared.", file=sys.stderr)


def get_log_level() -> str:
    """
    Get the current logging level.

    Returns:
        Current logging level as string
    """
    return logging.getLevelName(logging.getLogger().level)


def set_log_level(level: str) -> None:
    """
    Set the logging level dynamically.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    logging.getLogger().setLevel(getattr(logging, level.upper(), logging.INFO))
