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
from typing import Dict, Any, Optional
from ..api.helpers import generate_request_id


class SecurityLogger:
    """
    Structured security logger with JSON formatting, rotation policies, and alerting
    """
    
    def __init__(self, log_dir: str = "logs", enable_alerting: bool = True):
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
        self.alert_thresholds = {
            'auth_failure': 5,           # 5 auth failures per IP
            'rate_limit_violation': 10,  # 10 rate limit violations per IP
            'validation_error': 20       # 20 validation errors per IP
        }
        self.reset_window = timedelta(hours=1)  # Reset counters every hour
        
        # Create security logger
        self.logger = logging.getLogger('security')
        self.logger.setLevel(logging.INFO)
        
        # Remove existing handlers to avoid duplicates
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)
        
        # Create rotating file handler (10MB max, 5 backups)
        log_file = os.path.join(self.log_dir, 'security.log')
        handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5
        )
        
        # Set JSON formatter
        handler.setFormatter(JSONFormatter())
        self.logger.addHandler(handler)
        
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
        
        # Check threshold
        threshold = self.alert_thresholds[event_type]
        if self.failure_counts[counter_key] >= threshold:
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
        
        # Future enhancement: send email/slack notification here
        # self._send_alert_notification(alert_data)


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