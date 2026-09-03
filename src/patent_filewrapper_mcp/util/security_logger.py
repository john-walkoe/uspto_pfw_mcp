"""
Enhanced security logging for USPTO Patent File Wrapper MCP

Provides structured JSON logging for security events with rotation policies.
Includes threshold-based alerting for critical security events.
"""
import json
import logging
import logging.handlers
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional
from ..api.helpers import generate_request_id
from ..shared.log_sanitizer import LogSanitizer, SanitizingFilter

# Default log directory — always relative to user home so it works regardless
# of what CWD the host process (e.g. Claude Desktop on Windows) sets at launch.
_DEFAULT_LOG_DIR = str(Path.home() / ".uspto_pfw_mcp" / "logs")


class SecurityLogger:
    """
    Structured security logger with JSON formatting, rotation policies, and alerting
    """

    def __init__(self, log_dir: str = _DEFAULT_LOG_DIR, enable_alerting: bool = True):
        """
        Initialize security logger with rotation and alerting

        Args:
            log_dir: Directory for log files
            enable_alerting: Enable threshold-based alerting for security events
        """
        self.log_dir = log_dir
        self.enable_alerting = enable_alerting
        self._ensure_log_directory()

        # Initialize alerting counters
        self.failure_counts = defaultdict(int)  # Per-IP failure counts
        self.last_reset = datetime.now()
        #: Counter exposed on the health payload, so an operator can tell
        #: "nothing has fired" from "nothing is being delivered" (audit M-17).
        self.alerts_sent = 0
        self.alert_thresholds = {
            'auth_failure': 5,           # 5 auth failures per IP
            'rate_limit_violation': 10,  # 10 rate limit violations per IP
            'validation_error': 20       # 20 validation errors per IP
        }
        self.reset_window = timedelta(hours=1)  # Reset counters every hour

        # Single owner of the 'security' logger: this class. setup_logging()
        # deliberately does not attach handlers here — see config/log_config.py.
        self.logger = logging.getLogger('security')
        self.logger.setLevel(logging.INFO)

        log_file = os.path.join(self.log_dir, 'security.log')
        if not self.logger.handlers:
            # Rotating file handler (10MB max, 10 backups for compliance retention)
            # Same 0600-on-rotation guarantee as the app log (audit L-3):
            # security.log backups carry the client IPs and the audit trail.
            from ..config.log_config import _SecureRotatingFileHandler

            handler = _SecureRotatingFileHandler(
                log_file,
                maxBytes=10 * 1024 * 1024,  # 10MB
                backupCount=10,
                encoding='utf-8'
            )
            handler.setFormatter(JSONFormatter())
            self.logger.addHandler(handler)

        # Sink-level sanitization guarantee: every handler on this logger must
        # carry the SanitizingFilter, whoever created it. The security log gets
        # a sanitizer with mask_ips=False — every secret pattern still applies,
        # but the client IP survives. Masking it to two octets here destroyed
        # the attribution the auth-failure and rate-limit records exist for
        # (and the threshold alerts count by IP).
        for handler in self.logger.handlers:
            if not any(isinstance(f, SanitizingFilter) for f in handler.filters):
                handler.addFilter(SanitizingFilter(LogSanitizer(mask_ips=False)))

        # Owner read/write only
        if hasattr(os, 'chmod'):
            try:
                Path(log_file).touch(exist_ok=True)
                os.chmod(log_file, 0o600)
            except (OSError, PermissionError):
                pass

        # Prevent propagation to avoid duplicate logs
        self.logger.propagate = False

    def _ensure_log_directory(self):
        """Ensure log directory exists"""
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir, exist_ok=True)

    def log_auth_failure(self, endpoint: str, client_ip: str, reason: str, request_id: Optional[str] = None):
        """Log authentication failure"""
        self._log_security_event("auth_failure", {
            "endpoint": endpoint,
            "client_ip": client_ip,
            "reason": reason,
            "request_id": request_id or generate_request_id()
        })

    def log_rate_limit_violation(self, client_ip: str, endpoint: str, request_id: Optional[str] = None):
        """Log rate limit violation"""
        self._log_security_event("rate_limit_violation", {
            "client_ip": client_ip,
            "endpoint": endpoint,
            "request_id": request_id or generate_request_id()
        })

    def log_validation_error(self, endpoint: str, client_ip: str, error_type: str, details: str, request_id: Optional[str] = None):
        """Log validation error"""
        self._log_security_event("validation_error", {
            "endpoint": endpoint,
            "client_ip": client_ip,
            "error_type": error_type,
            "details": details,
            "request_id": request_id or generate_request_id()
        })

    def log_download_access(self, app_number: str, document_id: str, client_ip: str, success: bool, request_id: Optional[str] = None):
        """Log document download access"""
        self._log_security_event("download_access", {
            "app_number": app_number,
            "document_id": document_id,
            "client_ip": client_ip,
            "success": success,
            "request_id": request_id or generate_request_id()
        })

    def log_admin_action(self, actor: str, action: str, target: str, success: bool = True,
                         role: Optional[str] = None, detail: Optional[str] = None,
                         request_id: Optional[str] = None):
        """Log a privileged mcp_users mutation.

        PFW hosts the SHARED paid-tier user file that PTAB and FPD also read,
        so a grant made here is a grant on three servers. Every
        add / set_role / activate / deactivate needs a record naming who made
        it. Emails are masked by the sink filter.
        """
        self._log_security_event("admin_action", {
            "actor": actor,
            "action": action,
            "target": target,
            "role": role,
            "success": success,
            "detail": detail,
            "request_id": request_id or generate_request_id()
        })

    def log_proxy_startup(self, port: int):
        """Log proxy server startup"""
        self._log_security_event("proxy_startup", {
            "port": port,
            "timestamp": time.time()
        })

    def _log_security_event(self, event_type: str, data: Dict[str, Any]):
        """Log a security event with standardized format and trigger alerting"""
        log_entry = {
            "event_type": event_type,
            "timestamp": time.time(),
            "iso_timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            **data
        }

        self.logger.info(json.dumps(log_entry))

        # Check for alerting if enabled
        if self.enable_alerting and event_type in self.alert_thresholds:
            self._check_alert_threshold(event_type, data.get('client_ip', 'unknown'))

    def _check_alert_threshold(self, event_type: str, client_ip: str):
        """Check if alert threshold is exceeded and trigger alert if needed"""
        # Reset counters if window has passed
        if datetime.now() - self.last_reset > self.reset_window:
            self.failure_counts.clear()
            self.last_reset = datetime.now()

        # Increment failure count for this IP and event type
        counter_key = f"{client_ip}:{event_type}"
        self.failure_counts[counter_key] += 1

        # Fire ONCE per key per window, at the crossing. `>=` alerted again on
        # every subsequent event, so one persistent scanner produced an alert
        # per request — an alert storm is how a real signal gets ignored
        # (audit L-22).
        threshold = self.alert_thresholds[event_type]
        if self.failure_counts[counter_key] == threshold:
            self._trigger_security_alert(event_type, client_ip, self.failure_counts[counter_key])
        elif self.failure_counts[counter_key] == threshold * 10:
            # One escalation per order of magnitude, so a sustained attack is
            # still visible without being noisy.
            self._trigger_security_alert(event_type, client_ip, self.failure_counts[counter_key])

    def _trigger_security_alert(self, event_type: str, client_ip: str, count: int):
        """Trigger a security alert for threshold breach"""
        alert_data = {
            "alert_type": "threshold_exceeded",
            "event_type": event_type,
            "client_ip": client_ip,
            "count": count,
            "threshold": self.alert_thresholds[event_type],
            "window_hours": self.reset_window.total_seconds() / 3600,
            "severity": "HIGH" if event_type == "auth_failure" else "MEDIUM"
        }

        # Log the alert
        self._log_security_event("security_alert", alert_data)


        # Also log to standard logger for immediate visibility
        std_logger = logging.getLogger(__name__)
        std_logger.warning(
            f"SECURITY ALERT: {event_type} threshold exceeded for IP {client_ip} "
            f"(count: {count}, threshold: {self.alert_thresholds[event_type]})"
        )

        self._send_alert_notification(alert_data)

    def _send_alert_notification(self, alert_data: Dict[str, Any]) -> None:
        """Deliver an alert somewhere a human or a monitor will see it.

        Detection was write-only before this (audit M-17): thresholds were
        tuned and fired correctly, but the only effect was another line in the
        same local file nobody was known to be reading, so CC7.3 had no
        response leg at all.

        Two config-gated transports, both off by default so nothing changes
        for a deployment that has not opted in:
          PFW_ALERT_WEBHOOK_URL  POST the alert as JSON (Slack-compatible)
          PFW_ALERT_LOG_PATH     append to a SEPARATE file, so alerts are not
                                 buried in the general security log

        Best effort by construction: an alert transport must never be able to
        fail the request that produced the alert.
        """
        alert_log_path = os.getenv("PFW_ALERT_LOG_PATH", "").strip()
        if alert_log_path:
            try:
                with open(alert_log_path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(alert_data) + "\n")
            except Exception as e:
                logging.getLogger(__name__).warning(
                    f"Alert log write failed ({type(e).__name__})"
                )

        webhook_url = os.getenv("PFW_ALERT_WEBHOOK_URL", "").strip()
        if webhook_url:
            try:
                import httpx

                httpx.post(
                    webhook_url,
                    json={
                        "text": (
                            f"PFW security alert: {alert_data['event_type']} "
                            f"threshold exceeded ({alert_data['count']} events)"
                        ),
                        "alert": alert_data,
                    },
                    timeout=float(os.getenv("PFW_ALERT_WEBHOOK_TIMEOUT", "5")),
                )
            except Exception as e:
                # URL only never logged: a webhook URL is itself a credential.
                logging.getLogger(__name__).warning(
                    f"Alert webhook delivery failed ({type(e).__name__})"
                )

        self.alerts_sent += 1


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging"""

    def format(self, record):
        """Format log record as JSON"""
        try:
            # Parse the message if it's already JSON
            if record.msg.startswith('{'):
                log_data = json.loads(record.msg)
            else:
                log_data = {"message": record.msg}

            # Add standard fields
            log_data.update({
                "level": record.levelname,
                "logger": record.name,
                "module": record.module,
                "function": record.funcName,
                "line": record.lineno
            })

            return json.dumps(log_data)
        except Exception:
            # Fallback to standard formatting if JSON parsing fails
            return super().format(record)


# Global security logger instance
security_logger = SecurityLogger()
