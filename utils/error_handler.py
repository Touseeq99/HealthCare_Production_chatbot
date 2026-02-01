"""
Centralized Error Handling for Production
==========================================
Provides consistent error responses, logging, and exception handling.
"""
import logging
import traceback
import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from functools import wraps

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


# ============== Custom Exception Classes ==============

class AppException(Exception):
    """Base exception for all application errors"""
    def __init__(
        self, 
        message: str, 
        status_code: int = 500, 
        error_code: str = "INTERNAL_ERROR",
        details: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.details = details or {}
        super().__init__(self.message)


class AuthenticationError(AppException):
    """Authentication failed"""
    def __init__(self, message: str = "Authentication failed", details: Dict = None):
        super().__init__(message, status.HTTP_401_UNAUTHORIZED, "AUTH_ERROR", details)


class AuthorizationError(AppException):
    """User doesn't have permission"""
    def __init__(self, message: str = "Access denied", details: Dict = None):
        super().__init__(message, status.HTTP_403_FORBIDDEN, "FORBIDDEN", details)


class NotFoundError(AppException):
    """Resource not found"""
    def __init__(self, resource: str = "Resource", details: Dict = None):
        super().__init__(f"{resource} not found", status.HTTP_404_NOT_FOUND, "NOT_FOUND", details)


class ValidationError(AppException):
    """Input validation failed"""
    def __init__(self, message: str = "Validation failed", details: Dict = None):
        super().__init__(message, status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", details)


class RateLimitError(AppException):
    """Rate limit exceeded"""
    def __init__(self, message: str = "Too many requests", details: Dict = None):
        super().__init__(message, status.HTTP_429_TOO_MANY_REQUESTS, "RATE_LIMITED", details)


class ExternalServiceError(AppException):
    """External service (OpenAI, Pinecone) failed"""
    def __init__(self, service: str, message: str = "Service unavailable", details: Dict = None):
        super().__init__(
            f"{service}: {message}", 
            status.HTTP_503_SERVICE_UNAVAILABLE, 
            "EXTERNAL_SERVICE_ERROR", 
            {"service": service, **(details or {})}
        )


class DatabaseError(AppException):
    """Database operation failed"""
    def __init__(self, message: str = "Database error", details: Dict = None):
        super().__init__(message, status.HTTP_500_INTERNAL_SERVER_ERROR, "DB_ERROR", details)


# ============== Error Response Builder ==============

def build_error_response(
    request_id: str,
    status_code: int,
    error_code: str,
    message: str,
    details: Optional[Dict] = None,
    path: Optional[str] = None
) -> Dict[str, Any]:
    """Build a standardized error response"""
    return {
        "error": {
            "request_id": request_id,
            "code": error_code,
            "message": message,
            "details": details or {},
            "timestamp": datetime.utcnow().isoformat(),
            "path": path
        }
    }


# ============== Exception Handlers ==============

async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Handle custom application exceptions"""
    request_id = getattr(request.state, 'request_id', str(uuid.uuid4())[:8])
    
    logger.error(
        f"AppException: {exc.error_code}",
        extra={
            "request_id": request_id,
            "error_code": exc.error_code,
            "message": exc.message,
            "status_code": exc.status_code,
            "path": str(request.url.path),
            "method": request.method,
            "details": exc.details
        }
    )
    
    return JSONResponse(
        status_code=exc.status_code,
        content=build_error_response(
            request_id=request_id,
            status_code=exc.status_code,
            error_code=exc.error_code,
            message=exc.message,
            details=exc.details,
            path=str(request.url.path)
        )
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handle FastAPI HTTP exceptions"""
    request_id = getattr(request.state, 'request_id', str(uuid.uuid4())[:8])
    
    logger.warning(
        f"HTTPException: {exc.status_code}",
        extra={
            "request_id": request_id,
            "status_code": exc.status_code,
            "detail": exc.detail,
            "path": str(request.url.path)
        }
    )
    
    return JSONResponse(
        status_code=exc.status_code,
        content=build_error_response(
            request_id=request_id,
            status_code=exc.status_code,
            error_code="HTTP_ERROR",
            message=str(exc.detail),
            path=str(request.url.path)
        )
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unhandled exceptions - CRITICAL for production"""
    request_id = getattr(request.state, 'request_id', str(uuid.uuid4())[:8])
    
    # Log FULL traceback for debugging
    logger.critical(
        f"UNHANDLED EXCEPTION: {type(exc).__name__}",
        extra={
            "request_id": request_id,
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "path": str(request.url.path),
            "method": request.method,
            "traceback": traceback.format_exc()
        },
        exc_info=True
    )
    
    # Return generic message to user (don't expose internals)
    return JSONResponse(
        status_code=500,
        content=build_error_response(
            request_id=request_id,
            status_code=500,
            error_code="INTERNAL_ERROR",
            message="An unexpected error occurred. Please try again later.",
            details={"support_reference": request_id},
            path=str(request.url.path)
        )
    )


# ============== Decorator for Service Functions ==============

def handle_errors(service_name: str = "Service"):
    """Decorator to wrap service functions with error handling"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except AppException:
                raise  # Re-raise our custom exceptions
            except HTTPException:
                raise  # Re-raise HTTP exceptions
            except Exception as e:
                logger.error(
                    f"{service_name} error in {func.__name__}: {str(e)}",
                    exc_info=True
                )
                raise ExternalServiceError(
                    service=service_name,
                    message=f"Operation failed: {str(e)}"
                )
        return wrapper
    return decorator


# ============== Utility Functions ==============

def safe_get(data: Dict, *keys, default=None):
    """Safely get nested dictionary values"""
    for key in keys:
        if isinstance(data, dict):
            data = data.get(key, default)
        else:
            return default
    return data
