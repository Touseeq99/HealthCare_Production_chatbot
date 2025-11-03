import time
from fastapi import FastAPI, Request, HTTPException, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from typing import Dict, Any
import memcache
import os
from utils.logger import logger, setup_logging
from config import settings
from api import (auth, patient_chat, admin, doctor_chat, evidence)
from dotenv import load_dotenv

load_dotenv()
# Initialize logging
setup_logging()

# Initialize memcached for rate limiting and account lockout
mc = memcache.Client(['127.0.0.1:11211'], debug=0)

# Initialize FastAPI with rate limiting
app = FastAPI(
    title="MedChat API",  
    description="API for MedChat application",
    version="1.0.0"
)

# Rate limiter
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

allowed = os.getenv("ALLOWED_ORIGIN")
# Configure CORS
origins = [allowed
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["authentication"])
app.include_router(evidence.router)
app.include_router(admin.router, prefix="/api/admin", tags=["admin"]) 
app.include_router(patient_chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(doctor_chat.router , prefix="/api/chat", tags=["chat"])

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Middleware to log all requests and responses"""
    start_time = time.time()
    
    response = await call_next(request)
     
    process_time = (time.time() - start_time) * 1000
    formatted_process_time = f"{process_time:.2f}ms"
    
    logger.info(
        "Request completed",
        extra={
            "path": request.url.path, 
            "method": request.method,
            "status_code": response.status_code,
            "process_time": formatted_process_time,
            "client_ip": request.client.host if request.client else None,
        },
    )
    
    return response

@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check() -> Dict[str, str]:
    """Health check endpoint"""
    try:
        # Add database health check
        # db_status = "healthy" if check_db_connection() else "unhealthy"
        return {
            "status": "healthy",
            "timestamp": time.time(),
            # "database": db_status
        }
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service Unavailable"
        )

@app.get("/", tags=["Root"])
@limiter.limit(f"{settings.RATE_LIMIT}/minute")
async def read_root(request: Request):
    """Root endpoint with rate limiting"""
    return {"message": "Welcome to the MedChat API"}
