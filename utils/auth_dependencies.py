from typing import Optional
from datetime import datetime
from fastapi import HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database.database import get_db
from database.models import User
from utils.auth_service import SECRET_KEY, ALGORITHM
from utils.token_validator import TokenValidator, create_token_validation_error, TokenValidationError
from utils.token_blacklist_db import token_blacklist
from utils.logger import logger

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

class TokenData(BaseModel):
    email: Optional[str] = None

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    """Enhanced user authentication with detailed error handling and blacklist checking"""
    try:
        # Step 1: Check if token is blacklisted
        if token_blacklist.is_blacklisted(token):
            logger.warning("Attempted to use blacklisted token")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "message": "Token has been revoked",
                    "error_type": "token_revoked",
                    "timestamp": datetime.utcnow().isoformat()
                },
                headers={"WWW-Authenticate": 'Bearer error="invalid_token"'}
            )
        
        # Step 2: Validate token using enhanced validator
        user = TokenValidator.validate_token_complete(token, db)
        
        return user
        
    except TokenValidationError as e:
        # Convert custom validation error to HTTP exception
        raise create_token_validation_error(e)
    except HTTPException:
        # Let HTTP exceptions bubble up
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_current_user: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "message": "Authentication failed",
                "error_type": "internal_error"
            }
        )

async def get_current_active_user(current_user: User = Depends(get_current_user)):
    """Get current active user (can be extended with user status checks)"""
    # Add user status validation here if needed
    # For example: if not current_user.is_active:
    return current_user
