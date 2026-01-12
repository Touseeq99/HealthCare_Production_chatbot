from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.database import get_db
from database.models import User
from utils.hash_password import get_password_hash
from utils.email_service import email_service
from utils.logger import logger
from config import settings
from slowapi import Limiter
from slowapi.util import get_remote_address

# Pydantic models
class EmailVerificationRequest(BaseModel):
    token: str

class PasswordResetRequest(BaseModel):
    email: str

class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str

class EmailResendRequest(BaseModel):
    email: str

class BaseResponse(BaseModel):
    success: bool
    message: str

class UserResponse(BaseModel):
    success: bool
    message: str
    email_verified: Optional[bool] = None

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

router = APIRouter()

@router.post("/verify-email", response_model=UserResponse)
@limiter.limit(f"{settings.RATE_LIMIT}/minute")
async def verify_email(
    request: Request,
    verification_data: EmailVerificationRequest,
    db: Session = Depends(get_db)
):
    """
    Email verification temporarily disabled for current version.
    TODO: Re-enable email verification in next version.
    """
    return {
        "success": False,
        "message": "Email verification is temporarily disabled. All users are automatically verified.",
        "email_verified": None
    }

@router.post("/resend-verification", response_model=BaseResponse)
@limiter.limit(f"{settings.RATE_LIMIT}/minute")
async def resend_verification_email(
    request: Request,
    resend_data: EmailResendRequest,
    db: Session = Depends(get_db)
):
    """
    Email verification temporarily disabled for current version.
    TODO: Re-enable email verification in next version.
    """
    return {
        "success": False,
        "message": "Email verification is temporarily disabled. All users are automatically verified."
    }

@router.post("/request-password-reset", response_model=BaseResponse)
@limiter.limit(f"{settings.RATE_LIMIT}/minute")
async def request_password_reset(
    request: Request,
    reset_data: PasswordResetRequest,
    db: Session = Depends(get_db)
):
    """Request password reset"""
    try:
        user = db.query(User).filter(User.email == reset_data.email).first()
        
        if not user:
            return {
                "success": False,
                "message": "No account found with this email address"
            }
        
        # Send password reset email
        email_sent = email_service.send_password_reset_email(user, db)
        
        if email_sent:
            logger.info(f"Password reset email sent to {user.email}")
            return {
                "success": True,
                "message": "Password reset link has been sent to your email"
            }
        else:
            return {
                "success": False,
                "message": "Failed to send password reset email"
            }
            
    except Exception as e:
        logger.error(f"Password reset request error: {str(e)}")
        return {
            "success": False,
            "message": "Failed to process password reset request"
        }

@router.post("/reset-password", response_model=BaseResponse)
@limiter.limit(f"{settings.RATE_LIMIT}/minute")
async def reset_password(
    request: Request,
    reset_data: PasswordResetConfirm,
    db: Session = Depends(get_db)
):
    """Reset password using token"""
    try:
        # Verify token
        user = email_service.verify_password_reset_token(reset_data.token, db)
        
        if not user:
            return {
                "success": False,
                "message": "Invalid or expired reset token"
            }
        
        # Update password
        user.hashed_password = get_password_hash(reset_data.new_password)
        user.updated_at = datetime.utcnow()
        
        # Clear reset token
        email_service.clear_password_reset_token(user, db)
        
        logger.info(f"Password reset successfully for user {user.email}")
        return {
            "success": True,
            "message": "Password reset successfully"
        }
        
    except Exception as e:
        logger.error(f"Password reset error: {str(e)}")
        return {
            "success": False,
            "message": "Password reset failed"
        }

@router.get("/check-verification/{email}", response_model=UserResponse)
@limiter.limit(f"{settings.RATE_LIMIT * 2}/minute")
async def check_email_verification(
    request: Request,
    email: str,
    db: Session = Depends(get_db)
):
    """Check if email is verified"""
    try:
        user = db.query(User).filter(User.email == email).first()
        
        if not user:
            return {
                "success": False,
                "message": "No account found with this email address"
            }
        
        return {
            "success": True,
            "message": "Email verification status retrieved",
            "email_verified": user.email_verified
        }
        
    except Exception as e:
        logger.error(f"Check verification error: {str(e)}")
        return {
            "success": False,
            "message": "Failed to check email verification status"
        }
