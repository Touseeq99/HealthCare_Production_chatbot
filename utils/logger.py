"""
Production-Ready Logging System
================================
Features:
- JSON structured logging
- Request ID tracking for tracing
- Audit logging for security events
- Performance logging
- Log rotation (30 days)
"""
import logging
import sys
import os
import logging.handlers
import uuid
from pythonjsonlogger import jsonlogger
from datetime import datetime
from typing import Dict, Any, Optional
from contextvars import ContextVar

from config import settings

# Context variable for request tracking
request_id_var: ContextVar[str] = ContextVar('request_id', default='no-request-id')


class RequestIdFilter(logging.Filter):
    """Add request_id to all log records"""
    def filter(self, record):
        record.request_id = request_id_var.get()
        return True


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    """Custom JSON formatter with additional fields"""
    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record['timestamp'] = datetime.utcnow().isoformat()
        log_record['level'] = record.levelname
        log_record['logger'] = record.name
        log_record['request_id'] = getattr(record, 'request_id', 'no-request-id')
        
        # Add file info for errors
        if record.levelno >= logging.ERROR:
            log_record['file'] = record.pathname
            log_record['line'] = record.lineno
            log_record['function'] = record.funcName


def setup_logging() -> logging.Logger:
    """Configure production-ready JSON logging"""
    logger = logging.getLogger()
    logger.handlers.clear()
    
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logger.setLevel(log_level)
    
    # Create logs directory
    log_dir = 'logs'
    os.makedirs(log_dir, exist_ok=True)
    
    # JSON formatter
    formatter = CustomJsonFormatter(
        '%(timestamp)s %(level)s %(name)s %(message)s %(request_id)s',
        json_ensure_ascii=False
    )
    
    # Request ID filter
    request_filter = RequestIdFilter()
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(log_level)
    console_handler.addFilter(request_filter)
    
    # Application log file - rotates daily
    app_handler = logging.handlers.TimedRotatingFileHandler(
        filename=os.path.join(log_dir, 'application.log'),
        when='midnight',
        backupCount=30,
        encoding='utf-8'
    )
    app_handler.setFormatter(formatter)
    app_handler.setLevel(log_level)
    app_handler.addFilter(request_filter)
    
    # Error log file - separate for critical issues
    error_handler = logging.handlers.TimedRotatingFileHandler(
        filename=os.path.join(log_dir, 'error.log'),
        when='midnight',
        backupCount=60,  # Keep errors longer
        encoding='utf-8'
    )
    error_handler.setFormatter(formatter)
    error_handler.setLevel(logging.ERROR)
    error_handler.addFilter(request_filter)
    
    # Security/Audit log file
    audit_handler = logging.handlers.TimedRotatingFileHandler(
        filename=os.path.join(log_dir, 'audit.log'),
        when='midnight',
        backupCount=90,  # Keep audit logs 90 days
        encoding='utf-8'
    )
    audit_handler.setFormatter(formatter)
    audit_handler.setLevel(logging.INFO)
    
    # Add handlers
    logger.addHandler(console_handler)
    logger.addHandler(app_handler)
    logger.addHandler(error_handler)
    
    # Setup audit logger separately
    audit_logger = logging.getLogger('audit')
    audit_logger.addHandler(audit_handler)
    audit_logger.setLevel(logging.INFO)
    audit_logger.propagate = False
    
    # Silence noisy loggers
    for noisy in ["uvicorn", "uvicorn.error", "uvicorn.access", "httpx", "httpcore"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)
    
    return logger


# Initialize logging
logger = setup_logging()


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the specified name"""
    return logging.getLogger(name)


def get_audit_logger() -> logging.Logger:
    """Get the audit logger for security events"""
    return logging.getLogger('audit')


def set_request_id(request_id: str = None) -> str:
    """Set request ID for the current context"""
    rid = request_id or str(uuid.uuid4())[:8]
    request_id_var.set(rid)
    return rid


def get_request_id() -> str:
    """Get current request ID"""
    return request_id_var.get()


# ============== Audit Logging Functions ==============

def log_auth_event(event_type: str, user_id: str = None, email: str = None, 
                   success: bool = True, details: Dict = None):
    """Log authentication events"""
    audit = get_audit_logger()
    audit.info(
        f"AUTH_EVENT: {event_type}",
        extra={
            "event_type": event_type,
            "user_id": user_id,
            "email": email,
            "success": success,
            "details": details or {},
            "request_id": get_request_id()
        }
    )


def log_admin_action(action: str, admin_id: str, target: str, details: Dict = None):
    """Log admin actions for audit trail"""
    audit = get_audit_logger()
    audit.warning(
        f"ADMIN_ACTION: {action}",
        extra={
            "action": action,
            "admin_id": admin_id,
            "target": target,
            "details": details or {},
            "request_id": get_request_id()
        }
    )


def log_data_access(resource: str, user_id: str, action: str, count: int = None):
    """Log data access for compliance"""
    audit = get_audit_logger()
    audit.info(
        f"DATA_ACCESS: {action} on {resource}",
        extra={
            "resource": resource,
            "user_id": user_id,
            "action": action,
            "record_count": count,
            "request_id": get_request_id()
        }
    )


def log_security_event(event_type: str, severity: str, details: Dict):
    """Log security-related events"""
    audit = get_audit_logger()
    log_func = audit.critical if severity == "high" else audit.warning
    log_func(
        f"SECURITY_EVENT: {event_type}",
        extra={
            "event_type": event_type,
            "severity": severity,
            "details": details,
            "request_id": get_request_id()
        }
    )


# ============== Performance Logging ==============

class PerfLogger:
    """Context manager for performance logging"""
    def __init__(self, operation: str, threshold_ms: float = 1000):
        self.operation = operation
        self.threshold_ms = threshold_ms
        self.start_time = None
        self.logger = logging.getLogger('perf')
    
    def __enter__(self):
        import time
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        import time
        duration_ms = (time.time() - self.start_time) * 1000
        
        log_data = {
            "operation": self.operation,
            "duration_ms": round(duration_ms, 2),
            "request_id": get_request_id()
        }
        
        if duration_ms > self.threshold_ms:
            self.logger.warning(f"SLOW_OPERATION: {self.operation}", extra=log_data)
        else:
            self.logger.info(f"PERF: {self.operation}", extra=log_data)
