"""
Comprehensive input validation middleware and Pydantic models
"""
import re
from typing import Optional, List, Dict, Any
from fastapi import HTTPException, status, Request
from pydantic import BaseModel, validator, EmailStr, constr
import html

class SecurityValidationMixin:
    """Security-focused validation methods"""
    
    @staticmethod
    def sanitize_html(text: str) -> str:
        """Remove HTML tags and dangerous content"""
        if not text:
            return text
        # Basic HTML sanitization
        text = html.escape(text)
        # Remove script tags and other dangerous patterns
        text = re.sub(r'<script.*?>.*?</script>', '', text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r'javascript:', '', text, flags=re.IGNORECASE)
        text = re.sub(r'on\w+\s*=', '', text, flags=re.IGNORECASE)
        return text.strip()
    
    @staticmethod
    def validate_length(text: str, min_len: int = 1, max_len: int = 10000) -> str:
        """Validate text length"""
        if not text or len(text) < min_len:
            raise ValueError(f"Text must be at least {min_len} characters long")
        if len(text) > max_len:
            raise ValueError(f"Text must not exceed {max_len} characters")
        return text
    
    @staticmethod
    def validate_email_format(email: str) -> str:
        """Enhanced email validation"""
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            raise ValueError("Invalid email format")
        return email.lower().strip()
    
    @staticmethod
    def validate_password_strength(password: str) -> str:
        """Validate password strength"""
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not re.search(r'[A-Z]', password):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r'[a-z]', password):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r'\d', password):
            raise ValueError("Password must contain at least one digit")
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            raise ValueError("Password must contain at least one special character")
        return password

# Enhanced Pydantic Models with Validation

class UserCreateRequest(BaseModel, SecurityValidationMixin):
    email: EmailStr
    password: constr(min_length=8, max_length=128)
    name: constr(min_length=1, max_length=100)
    surname: constr(min_length=1, max_length=100)
    role: constr(pattern=r'^(patient|doctor|admin)$')
    phone: Optional[constr(max_length=20)] = None
    specialization: Optional[constr(max_length=200)] = None
    doctor_register_number: Optional[constr(max_length=50)] = None
    
    @validator('password')
    def validate_password(cls, v):
        return cls.validate_password_strength(v)
    
    @validator('name', 'surname', 'specialization')
    def sanitize_text_fields(cls, v):
        if v:
            return cls.sanitize_html(v)
        return v
    
    @validator('phone', 'doctor_register_number')
    def sanitize_optional_fields(cls, v):
        if v:
            return cls.sanitize_html(v)
        return v

class LoginRequest(BaseModel, SecurityValidationMixin):
    email: EmailStr
    password: constr(min_length=1, max_length=128)
    role: constr(pattern=r'^(patient|doctor|admin)$')
    
    @validator('email')
    def validate_email(cls, v):
        return cls.validate_email_format(v)

class MessageRequest(BaseModel, SecurityValidationMixin):
    message: constr(min_length=1, max_length=10000)
    session_id: Optional[int] = None
    
    @validator('message')
    def sanitize_message(cls, v):
        return cls.sanitize_html(v)
    
    @validator('session_id')
    def validate_session_id(cls, v):
        if v is not None and v <= 0:
            raise ValueError("Session ID must be a positive integer")
        return v

class SessionCreateRequest(BaseModel, SecurityValidationMixin):
    session_name: Optional[constr(max_length=200)] = None
    
    @validator('session_name')
    def sanitize_session_name(cls, v):
        if v:
            return cls.sanitize_html(v)
        return v

class RefreshTokenRequest(BaseModel, SecurityValidationMixin):
    refresh_token: constr(min_length=10, max_length=500)
    
    @validator('refresh_token')
    def validate_token_format(cls, v):
        # Basic JWT token format validation
        if not re.match(r'^[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+\.[A-Za-z0-9-_]*$', v):
            raise ValueError("Invalid token format")
        return v.strip()

class EmailVerificationRequest(BaseModel, SecurityValidationMixin):
    token: constr(min_length=10, max_length=500)
    
    @validator('token')
    def validate_token(cls, v):
        if not re.match(r'^[A-Za-z0-9-_]+$', v):
            raise ValueError("Invalid token format")
        return v.strip()

class PasswordResetRequest(BaseModel, SecurityValidationMixin):
    token: constr(min_length=10, max_length=500)
    new_password: constr(min_length=8, max_length=128)
    
    @validator('new_password')
    def validate_new_password(cls, v):
        return cls.validate_password_strength(v)
    
    @validator('token')
    def validate_token(cls, v):
        if not re.match(r'^[A-Za-z0-9-_]+$', v):
            raise ValueError("Invalid token format")
        return v.strip()

class PasswordResetEmailRequest(BaseModel, SecurityValidationMixin):
    email: EmailStr
    
    @validator('email')
    def validate_email(cls, v):
        return cls.validate_email_format(v)

class ArticleCreateRequest(BaseModel, SecurityValidationMixin):
    title: constr(min_length=1, max_length=500)
    content: constr(min_length=1, max_length=50000)
    status: Optional[constr(pattern=r'^(draft|published|archived)$')] = 'draft'
    
    @validator('title', 'content')
    def sanitize_content(cls, v):
        return cls.sanitize_html(v)

class AdminUserSearchRequest(BaseModel, SecurityValidationMixin):
    email: Optional[EmailStr] = None
    role: Optional[constr(pattern=r'^(patient|doctor|admin)$')] = None
    page: Optional[int] = 1
    limit: Optional[int] = 50
    
    @validator('page', 'limit')
    def validate_pagination(cls, v):
        if v is not None and v <= 0:
            raise ValueError("Page and limit must be positive integers")
        if v is not None and v > 1000:
            raise ValueError("Page and limit must not exceed 1000")
        return v

class TokenRevocationRequest(BaseModel, SecurityValidationMixin):
    user_email: EmailStr
    
    @validator('user_email')
    def validate_email(cls, v):
        return cls.validate_email_format(v)

# Validation Middleware

class ValidationMiddleware:
    """Middleware for comprehensive request validation"""
    
    @staticmethod
    async def validate_request_size(request: Request, max_size_mb: int = 10):
        """Validate request size"""
        content_length = request.headers.get("content-length")
        if content_length:
            size_bytes = int(content_length)
            max_size_bytes = max_size_mb * 1024 * 1024
            if size_bytes > max_size_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"Request too large. Maximum size is {max_size_mb}MB"
                )
    
    @staticmethod
    async def validate_content_type(request: Request, allowed_types: List[str]):
        """Validate content type"""
        content_type = request.headers.get("content-type", "")
        if not any(allowed_type in content_type.lower() for allowed_type in allowed_types):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Unsupported content type. Allowed types: {', '.join(allowed_types)}"
            )
    
    @staticmethod
    async def validate_user_agent(request: Request):
        """Basic user agent validation"""
        user_agent = request.headers.get("user-agent", "")
        if not user_agent or len(user_agent) < 10:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or missing User-Agent header"
            )
    
    @staticmethod
    async def validate_ip_address(request: Request):
        """Basic IP validation (can be enhanced with geo-blocking)"""
        client_ip = request.client.host if request.client else None
        if not client_ip:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unable to determine client IP"
            )
        
        # Basic IP format validation
        ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$|^[0-9a-fA-F:]+$'
        if not re.match(ip_pattern, client_ip):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid IP address format"
            )

# Rate Limiting Validation

class RateLimitValidation:
    """Enhanced rate limiting with user-specific limits"""
    
    @staticmethod
    def get_rate_limit_config(endpoint: str, user_role: str) -> Dict[str, int]:
        """Get rate limit configuration based on endpoint and user role"""
        base_config = {
            "auth": {"patient": 10, "doctor": 20, "admin": 50},
            "chat": {"patient": 30, "doctor": 60, "admin": 100},
            "admin": {"patient": 5, "doctor": 20, "admin": 200},
            "default": {"patient": 15, "doctor": 30, "admin": 75}
        }
        
        return base_config.get(endpoint, base_config["default"]).get(user_role, 15)
    
    @staticmethod
    def validate_rate_limit(current_requests: int, max_requests: int):
        """Validate if rate limit is exceeded"""
        if current_requests >= max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "message": "Rate limit exceeded",
                    "max_requests": max_requests,
                    "retry_after": 60
                },
                headers={"Retry-After": "60"}
            )

# SQL Injection Protection

class SQLInjectionProtection:
    """SQL injection protection utilities"""
    
    @staticmethod
    def detect_sql_injection(text: str) -> bool:
        """Detect potential SQL injection patterns"""
        if not text:
            return False
        
        # Common SQL injection patterns
        sql_patterns = [
            r"(\b(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|EXEC|UNION)\b)",
            r"(--|#|/\*|\*/)",
            r"(\bOR\b.*=.*\bOR\b)",
            r"(\bAND\b.*=.*\bAND\b)",
            r"('.*'|\".*\")\s*(=|LIKE)",
            r"(1\s*=\s*1|1\s*=\s*1\s*--)",
            r"(;\s*(DROP|DELETE|UPDATE|INSERT))"
        ]
        
        for pattern in sql_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False
    
    @staticmethod
    def validate_input_safety(text: str) -> str:
        """Validate input for SQL injection"""
        if SQLInjectionProtection.detect_sql_injection(text):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid input detected"
            )
        return text
