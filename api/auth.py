from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.database import get_db
from database.models import User
from utils.hash_password import get_password_hash
from utils.auth_service import create_access_token, authenticate_user, ACCESS_TOKEN_EXPIRE_MINUTES
from utils.auth_dependencies import get_current_user
from utils.refresh_token_service import refresh_token_service
from utils.token_blacklist_db import token_blacklist
from utils.logger import logger
from utils.email_service import email_service
from utils.validation import (
    UserCreateRequest, LoginRequest, RefreshTokenRequest,
    EmailVerificationRequest, PasswordResetRequest, PasswordResetEmailRequest,
    TokenRevocationRequest, ValidationMiddleware, SQLInjectionProtection,
    RateLimitValidation
)
from config import settings
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from utils.rate_limit_handler import rate_limit_exceeded_handler

# Pydantic models (keeping for backward compatibility)
class LoginResponse(BaseModel):
    success: bool
    token: str
    refresh_token: str
    token_type: str
    expires_in: int
    refresh_expires_in: int
    user: dict

class RefreshTokenResponse(BaseModel):
    success: bool
    token: str
    token_type: str
    expires_in: int
    refresh_token: Optional[str] = None
    refresh_expires_in: Optional[int] = None

class TokenResponse(BaseModel):
    success: bool
    token: str
    token_type: str
    expires_in: int
    user: Optional[dict] = None

# Legacy models for compatibility
class UserCreate(BaseModel):
    email: str
    password: str
    name: str
    surname: str
    role: str
    phone: Optional[str] = None
    specialization: Optional[str] = None
    doctor_register_number: Optional[str] = None

class UserResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    user: Optional[dict] = None
    token: Optional[str] = None
    email_verification_required: Optional[bool] = None


# Initialize rate limiter for auth endpoints
limiter = Limiter(key_func=get_remote_address)

# API Endpoints

router = APIRouter()

@router.post("/signup", response_model=UserResponse)
@limiter.limit(f"{settings.RATE_LIMIT}/minute")
async def register(request: Request, user: UserCreateRequest, db: Session = Depends(get_db)):
    # Enhanced validation
    await ValidationMiddleware.validate_request_size(request, 5)  # 5MB limit
    await ValidationMiddleware.validate_content_type(request, ["application/json"])
    await ValidationMiddleware.validate_user_agent(request)
    await ValidationMiddleware.validate_ip_address(request)
    
    # SQL injection protection
    SQLInjectionProtection.validate_input_safety(user.email)
    SQLInjectionProtection.validate_input_safety(user.name)
    SQLInjectionProtection.validate_input_safety(user.surname)
    
    # Check if user already exists (optimized query)
    existing_user = db.query(User).filter(User.email == user.email.lower()).first()
    if existing_user:
        return {
            "success": False,
            "message": "Email already registered"
        }
    
    try:
        # Create new user
        hashed_password = get_password_hash(user.password)
        db_user = User(
            email=user.email.lower(),
            hashed_password=hashed_password,
            name=user.name,
            surname=user.surname,
            role=user.role,
            phone=user.phone,
            specialization=user.specialization,
            doctor_register_number=user.doctor_register_number,
            email_verified=True  # Auto-verify for current version (TODO: Re-enable email verification in next version)
        )
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        
        # Email verification temporarily disabled for current version
        # TODO: Re-enable email verification in next version
        # email_sent = email_service.send_verification_email(db_user, db)
        
        # Generate JWT token (email verification skipped for now)
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": db_user.email, "role": db_user.role}, 
            expires_delta=access_token_expires
        )
        
        # Prepare response
        return {
            "success": True,
            "message": "Registration successful! You can now login.",
            "user": {
                "id": str(db_user.id),
                "email": db_user.email,
                "name": db_user.name,
                "surname": db_user.surname,
                "role": db_user.role,
                "phone": db_user.phone,
                "specialization": db_user.specialization,
                "doctor_register_number": db_user.doctor_register_number,
                "email_verified": db_user.email_verified
            },
            "token": access_token,
            "email_verification_required": False  # Temporarily disabled
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Registration error: {str(e)}")
        return {
            "success": False,
            "message": "Registration failed. Please try again."
        }

@router.post("/token", response_model=LoginResponse)
@limiter.limit(f"{settings.RATE_LIMIT}/minute")
async def login_for_access_token(
    request: Request,
    login_data: LoginRequest, 
    db: Session = Depends(get_db)
):
    # Enhanced validation
    await ValidationMiddleware.validate_request_size(request, 1)  # 1MB limit
    await ValidationMiddleware.validate_content_type(request, ["application/json"])
    await ValidationMiddleware.validate_user_agent(request)
    await ValidationMiddleware.validate_ip_address(request)
    
    # SQL injection protection
    SQLInjectionProtection.validate_input_safety(login_data.email)
    SQLInjectionProtection.validate_input_safety(login_data.role)
    
    try:
        # Extract IP and user agent
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")
        
        user = authenticate_user(db, login_data.email.lower(), login_data.password, login_data.role, ip_address, user_agent)
        if not user:
            # This should not be reached due to the exception in authenticate_user
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"message": "Authentication failed"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Email verification temporarily disabled for current version
        # TODO: Re-enable email verification in next version
        # if not user.email_verified and user.role != "admin":
        #     return {
        #         "success": False,
        #         "message": "Please verify your email address before logging in. Check your inbox for the verification link.",
        #         "error_type": "email_not_verified"
        #     }
        
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": user.email, "role": user.role}, 
            expires_delta=access_token_expires
        )
        
        # Create refresh token
        refresh_token_obj = refresh_token_service.create_refresh_token(
            db, user, ip_address, user_agent
        )
        
        # Log successful login
        logger.info(
            "User logged in successfully",
            extra={
                "email": user.email,
                "role": user.role,
                "client_ip": ip_address,
            },
        )
        
        return {
            "success": True,
            "token": access_token,
            "refresh_token": refresh_token_obj.token,
            "token_type": "bearer",
            "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,  # Convert to seconds
            "refresh_expires_in": settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,  # Convert to seconds
            "user": {
                "email": user.email,
                "name": user.name,
                "role": user.role
            }
        }
        
    except HTTPException as http_exc:
        # Re-raise HTTP exceptions
        raise http_exc
    except Exception as e:
        logger.error(
            "Login error",
            extra={
                "error": str(e),
                "email": login_data.email,
                "client_ip": request.client.host if request.client else None,
            },
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "An error occurred during login"}
        )

@router.post("/refresh-token", response_model=RefreshTokenResponse)
@limiter.limit(f"{settings.RATE_LIMIT * 2}/minute")
async def refresh_access_token(
    request: Request,
    refresh_data: RefreshTokenRequest,
    db: Session = Depends(get_db)
):
    """Refresh access token using refresh token"""
    try:
        # Extract IP and user agent
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")
        
        # Validate refresh token
        refresh_token_obj, user = refresh_token_service.validate_refresh_token(
            db, refresh_data.refresh_token
        )
        
        if not refresh_token_obj or not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "message": "Invalid or expired refresh token",
                    "error_type": "invalid_refresh_token"
                }
            )
        
        # Create new access token
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        new_access_token = create_access_token(
            data={"sub": user.email, "role": user.role},
            expires_delta=access_token_expires
        )
        
        logger.info(f"Access token refreshed for user {user.email}")
        
        return {
            "success": True,
            "token": new_access_token,
            "token_type": "bearer",
            "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,  # Convert to seconds
            "refresh_token": refresh_data.refresh_token,  # Return same refresh token
            "refresh_expires_in": int((refresh_token_obj.expires_at - datetime.utcnow()).total_seconds())
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token refresh error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Token refresh failed"}
        )

@router.post("/logout")
@limiter.limit(f"{settings.RATE_LIMIT * 2}/minute")
async def logout(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Logout user and blacklist current token + revoke refresh tokens"""
    try:
        # Extract token from Authorization header
        auth_header = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "No token provided"}
            )
        
        access_token = auth_header.split(" ")[1]
        
        # Blacklist access token
        token_success = token_blacklist.add_to_blacklist(access_token, "logout", current_user.email, db)
        
        # Revoke all refresh tokens for this user
        revoked_count = refresh_token_service.revoke_all_user_tokens(db, current_user.id)
        
        if token_success and revoked_count > 0:
            logger.info(f"User {current_user.email} logged out successfully - {revoked_count} refresh tokens revoked")
            return {
                "success": True,
                "message": "Logout successful",
                "revoked_refresh_tokens": revoked_count,
                "timestamp": datetime.utcnow().isoformat()
            }
        else:
            logger.warning(f"Partial logout for user {current_user.email} - access_token_blacklisted: {token_success}, refresh_tokens_revoked: {revoked_count}")
            return {
                "success": True,
                "message": "Logout completed with some issues",
                "access_token_blacklisted": token_success,
                "revoked_refresh_tokens": revoked_count,
                "timestamp": datetime.utcnow().isoformat()
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Logout error for user {current_user.email}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Logout failed"}
        )

@router.post("/revoke-refresh-token")
@limiter.limit(f"{settings.RATE_LIMIT * 2}/minute")
async def revoke_refresh_token(
    request: Request,
    refresh_data: RefreshTokenRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Revoke a specific refresh token"""
    try:
        # Validate the refresh token belongs to current user
        refresh_token_obj, user = refresh_token_service.validate_refresh_token(
            db, refresh_data.refresh_token
        )
        
        if not refresh_token_obj or user.id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"message": "Invalid refresh token"}
            )
        
        # Revoke the refresh token
        success = refresh_token_service.revoke_refresh_token(db, refresh_data.refresh_token)
        
        if success:
            logger.info(f"Refresh token revoked for user {current_user.email}")
            return {
                "success": True,
                "message": "Refresh token revoked successfully"
            }
        else:
            return {
                "success": False,
                "message": "Refresh token not found or already revoked"
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Refresh token revocation error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Failed to revoke refresh token"}
        )

@router.post("/revoke-tokens/{user_email}")
@limiter.limit(f"{settings.RATE_LIMIT}/minute")
async def revoke_user_tokens(
    request: Request, 
    user_email: str, 
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Revoke all tokens for a specific user (admin only)"""
    try:
        # Only admin can revoke tokens
        if current_user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"message": "Admin access required"}
            )
        
        # Verify target user exists
        target_user = db.query(User).filter(User.email == user_email).first()
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "User not found"}
            )
        
        # Cannot revoke admin tokens unless you're super admin
        if target_user.role == "admin" and current_user.email != user_email:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"message": "Cannot revoke admin tokens"}
            )
        
        # Revoke all tokens for the user
        revoked_count = token_blacklist.revoke_user_tokens(user_email, "admin_revocation")
        
        logger.warning(f"Admin {current_user.email} revoked {revoked_count} tokens for user {user_email}")
        
        return {
            "success": True,
            "message": f"Revoked {revoked_count} active tokens for {user_email}",
            "revoked_count": revoked_count,
            "target_user": user_email,
            "revoked_by": current_user.email,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token revocation error for {user_email}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Token revocation failed"}
        )

@router.post("/cleanup-blacklist")
@limiter.limit(f"{settings.RATE_LIMIT}/hour")
async def cleanup_blacklist(
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """Clean up expired blacklist entries (admin only)"""
    try:
        # Only admin can cleanup blacklist
        if current_user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"message": "Admin access required"}
            )
        
        # Clean up expired entries
        cleaned_count = token_blacklist.cleanup_expired_tokens()
        
        logger.info(f"Admin {current_user.email} cleaned up {cleaned_count} expired blacklist entries")
        
        return {
            "success": True,
            "message": f"Cleaned up {cleaned_count} expired blacklist entries",
            "cleaned_count": cleaned_count,
            "cleaned_by": current_user.email,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Blacklist cleanup error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Blacklist cleanup failed"}
        )

@router.get("/verify-token")
@limiter.limit(f"{settings.RATE_LIMIT * 2}/minute")
async def verify_token(request: Request, current_user: User = Depends(get_current_user)):
    return {"status": "valid", "user": current_user.email}
