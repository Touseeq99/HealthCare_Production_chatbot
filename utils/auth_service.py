from datetime import datetime, timedelta
from typing import Optional
from fastapi import HTTPException, status, Request
from sqlalchemy.orm import Session
from jose import JWTError, jwt

from database.models import User, LoginAttempt
from utils.auth_security import is_account_locked, record_failed_login, clear_login_attempts, is_account_locked_db, record_failed_login_db, clear_login_attempts_db, record_successful_login_db, REDIS_AVAILABLE
from utils.hash_password import verify_password
from utils.logger import logger
from config import settings

# JWT Configuration from settings
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = settings.REFRESH_TOKEN_EXPIRE_DAYS

__all__ = ['create_access_token', 'authenticate_user', 'ACCESS_TOKEN_EXPIRE_MINUTES', 'REFRESH_TOKEN_EXPIRE_DAYS']

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    # Convert SecretStr to string for JWT encoding
    secret_key_str = SECRET_KEY.get_secret_value() if hasattr(SECRET_KEY, 'get_secret_value') else str(SECRET_KEY)
    encoded_jwt = jwt.encode(to_encode, secret_key_str, algorithm=ALGORITHM)
    return encoded_jwt

def authenticate_user(db: Session, email: str, password: str, role: str, ip_address: str = None, user_agent: str = None):
    # Check if account is locked (try Redis, then database)
    locked = False
    remaining = 0
    
    if REDIS_AVAILABLE:
        locked, remaining = is_account_locked(email)
    else:
        locked, remaining = is_account_locked_db(db, email)
    
    if locked:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail={
                "message": "Account locked due to too many failed login attempts",
                "retry_after_seconds": remaining
            }
        )

    user = db.query(User).filter(User.email == email, User.role == role).first()
    if not user:
        # Record failed attempt even if user doesn't exist (prevents user enumeration)
        if REDIS_AVAILABLE:
            record_failed_login(email)
        else:
            record_failed_login_db(db, email, ip_address, user_agent, "user_not_found")
        return False
        
    if not verify_password(password, user.hashed_password):
        # Record failed attempt
        if REDIS_AVAILABLE:
            failures = record_failed_login(email)
            remaining_attempts = settings.MAX_LOGIN_ATTEMPTS - (failures - 1)
        else:
            record_failed_login_db(db, email, ip_address, user_agent, "invalid_password")
            # Check if account is now locked
            locked, remaining = is_account_locked_db(db, email)
            if locked:
                remaining_attempts = 0
            else:
                # Count recent failures to determine remaining attempts
                lockout_cutoff = datetime.utcnow() - timedelta(seconds=settings.LOCKOUT_TIME)
                recent_failures = db.query(LoginAttempt).filter(
                    LoginAttempt.email == email,
                    LoginAttempt.success == False,
                    LoginAttempt.attempt_time > lockout_cutoff
                ).count()
                remaining_attempts = max(0, settings.MAX_LOGIN_ATTEMPTS - recent_failures)
        
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "message": "Incorrect email or password",
                "remaining_attempts": remaining_attempts,
                "account_locked": remaining_attempts <= 0
            }
        )
    
    # Clear failed attempts on successful login
    if REDIS_AVAILABLE:
        clear_login_attempts(email)
    else:
        clear_login_attempts_db(db, email)
        record_successful_login_db(db, email, ip_address, user_agent)
    
    return user
