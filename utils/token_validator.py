from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from fastapi import HTTPException, status
from jose import JWTError, jwt, ExpiredSignatureError
from sqlalchemy.orm import Session

from database.models import User
from utils.auth_service import SECRET_KEY, ALGORITHM
from utils.logger import logger
from config import settings

class TokenValidationError(Exception):
    """Custom exception for token validation errors"""
    def __init__(self, message: str, error_type: str):
        self.message = message
        self.error_type = error_type
        super().__init__(message)

class TokenValidator:
    """Handles JWT token validation with detailed error handling"""
    
    @staticmethod
    def decode_token(token: str) -> Dict[str, Any]:
        """
        Decode JWT token and return payload
        
        Args:
            token: JWT token string
            
        Returns:
            Token payload dictionary
            
        Raises:
            TokenValidationError: For various token validation failures
        """
        try:
            # Convert SecretStr to string for JWT decoding
            secret_key_str = SECRET_KEY.get_secret_value() if hasattr(SECRET_KEY, 'get_secret_value') else str(SECRET_KEY)
            payload = jwt.decode(token, secret_key_str, algorithms=[ALGORITHM])
            return payload
            
        except ExpiredSignatureError:
            logger.warning("Token expired during validation")
            raise TokenValidationError(
                message="Token has expired",
                error_type="expired"
            )
            
        except JWTError as e:
            # Handle all other JWT errors (invalid format, signature, etc.)
            error_msg = str(e).lower()
            if "invalid" in error_msg or "malformed" in error_msg:
                logger.warning(f"Invalid token format: {str(e)}")
                raise TokenValidationError(
                    message="Invalid token format",
                    error_type="invalid_format"
                )
            elif "signature" in error_msg:
                logger.warning(f"JWT signature error: {str(e)}")
                raise TokenValidationError(
                    message="Token signature verification failed",
                    error_type="signature_invalid"
                )
            else:
                logger.warning(f"JWT validation error: {str(e)}")
                raise TokenValidationError(
                    message="Token validation failed",
                    error_type="signature_invalid"
                )
            
        except Exception as e:
            logger.error(f"Unexpected token validation error: {str(e)}")
            raise TokenValidationError(
                message="Token validation failed",
                error_type="unknown_error"
            )
    
    @staticmethod
    def validate_token_payload(payload: Dict[str, Any]) -> str:
        """
        Validate token payload structure and extract email
        
        Args:
            payload: Decoded JWT payload
            
        Returns:
            User email from token
            
        Raises:
            TokenValidationError: If payload is invalid
        """
        email = payload.get("sub")
        if not email:
            logger.warning("Token missing subject (email) claim")
            raise TokenValidationError(
                message="Token missing required information",
                error_type="missing_claims"
            )
        
        # Additional payload validation can be added here
        if not isinstance(email, str) or "@" not in email:
            logger.warning(f"Invalid email format in token: {email}")
            raise TokenValidationError(
                message="Invalid token format",
                error_type="invalid_email"
            )
            
        return email
    
    @staticmethod
    def verify_user_exists(db: Session, email: str) -> User:
        """
        Verify user exists in database
        
        Args:
            db: Database session
            email: User email from token
            
        Returns:
            User object
            
        Raises:
            TokenValidationError: If user not found
        """
        user = db.query(User).filter(User.email == email).first()
        if not user:
            logger.warning(f"User not found for token email: {email}")
            raise TokenValidationError(
                message="User not found",
                error_type="user_not_found"
            )
        
        return user
    
    @staticmethod
    def validate_token_complete(token: str, db: Session) -> User:
        """
        Complete token validation pipeline
        
        Args:
            token: JWT token string
            db: Database session
            
        Returns:
            Validated user object
            
        Raises:
            TokenValidationError: For any validation failure
        """
        # Step 1: Decode token
        payload = TokenValidator.decode_token(token)
        
        # Step 2: Validate payload
        email = TokenValidator.validate_token_payload(payload)
        
        # Step 3: Verify user exists
        user = TokenValidator.verify_user_exists(db, email)
        
        # Step 4: Log successful validation
        logger.info(f"Token validated successfully for user: {email}")
        
        return user

def create_token_validation_error(error: TokenValidationError) -> HTTPException:
    """
    Convert TokenValidationError to appropriate HTTPException
    
    Args:
        error: TokenValidationError instance
        
    Returns:
        HTTPException with appropriate status code and message
    """
    error_mapping = {
        "expired": (status.HTTP_401_UNAUTHORIZED, "Token has expired", "Bearer expired"),
        "invalid_format": (status.HTTP_401_UNAUTHORIZED, "Invalid token format", "Bearer error=\"invalid_token\""),
        "signature_invalid": (status.HTTP_401_UNAUTHORIZED, "Invalid token signature", "Bearer error=\"invalid_signature\""),
        "missing_claims": (status.HTTP_401_UNAUTHORIZED, "Token missing required information", "Bearer error=\"invalid_token\""),
        "invalid_email": (status.HTTP_401_UNAUTHORIZED, "Invalid token format", "Bearer error=\"invalid_token\""),
        "user_not_found": (status.HTTP_401_UNAUTHORIZED, "User not found", "Bearer error=\"invalid_token\""),
        "unknown_error": (status.HTTP_500_INTERNAL_SERVER_ERROR, "Token validation failed", None),
    }
    
    status_code, message, auth_header = error_mapping.get(
        error.error_type, 
        (status.HTTP_500_INTERNAL_SERVER_ERROR, "Token validation failed", None)
    )
    
    headers = {"WWW-Authenticate": auth_header} if auth_header else None
    
    return HTTPException(
        status_code=status_code,
        detail={
            "message": message,
            "error_type": error.error_type,
            "timestamp": datetime.utcnow().isoformat()
        },
        headers=headers
    )
