import time
import uuid
from fastapi import FastAPI, Request, HTTPException, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from utils.rate_limit_handler import rate_limit_exceeded_handler
from typing import Dict, Any
import os
from utils.logger import logger, setup_logging, set_request_id, get_request_id
from utils.error_handler import (
    AppException, 
    app_exception_handler, 
    http_exception_handler, 
    unhandled_exception_handler
)
from config import settings
from api import (auth, patient_chat_v2, admin, doctor_chat_v2, evidence, article)
from dotenv import load_dotenv

load_dotenv()
# Initialize logging
setup_logging()


# Initialize FastAPI with rate limiting
app = FastAPI(
    title="MedChat API",  
    description="API for MedChat application",
    version="1.0.0"
)

# Rate limiter
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

# Register Global Exception Handlers
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

allowed = os.getenv("ALLOWED_ORIGIN")
# Configure CORS
origins = [allowed]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://metamedmd.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"], 
    expose_headers=["*"]
)

@app.middleware("http")
async def context_middleware(request: Request, call_next):
    """Middleware to set request ID and log performance"""
    start_time = time.time()
    
    # Extract or generate Request ID
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
    set_request_id(request_id)
    request.state.request_id = request_id
    
    # Process request
    response = await call_next(request)
    
    # Calculate performance
    process_time = (time.time() - start_time) * 1000
    formatted_process_time = f"{process_time:.2f}ms"
    
    # Log request completion with structured data
    logger.info(
        "Request completed",
        extra={
            "path": request.url.path, 
            "method": request.method,
            "status_code": response.status_code,
            "process_time": formatted_process_time,
            "client_ip": request.client.host if request.client else "unknown",
            "request_id": request_id
        },
    )
    
    # Attach Request ID to response headers
    response.headers["X-Request-ID"] = request_id
    return response

# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["authentication"])
app.include_router(evidence.router)
app.include_router(admin.router, prefix="/api/admin", tags=["admin"]) 
app.include_router(article.router, prefix="/api", tags=["articles"])
app.include_router(patient_chat_v2.router, prefix="/api", tags=["chat"])
app.include_router(doctor_chat_v2.router, prefix="/api", tags=["chat"])

@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check() -> Dict[str, str]:
    """Health check endpoint"""
    try:
        return {
            "status": "healthy",
            "timestamp": time.time(),
            "version": "1.0.0",
            "environment": os.getenv("ENV", "production")
        }
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}", extra={"request_id": get_request_id()})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service Unavailable"
        )

@app.get("/", tags=["Root"])
@limiter.limit(f"{settings.RATE_LIMIT}/minute")
async def read_root(request: Request):
    """Root endpoint with rate limiting"""
    return {"message": "Welcome to the MedChat API"}
