from fastapi import HTTPException, status, Request
from slowapi.errors import RateLimitExceeded
from utils.logger import logger

def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """Custom handler for rate limit exceeded errors"""
    logger.warning(
        "Rate limit exceeded",
        extra={
            "path": request.url.path,
            "method": request.method,
            "client_ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent"),
        }
    )
    
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "message": "Rate limit exceeded. Please try again later.",
            "retry_after": 60,  # Suggest retry after 1 minute
            "limit": exc.detail if hasattr(exc, 'detail') else "Too many requests"
        }
    )
