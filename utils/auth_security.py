from datetime import datetime, timedelta
from typing import Optional, Tuple
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
import time
import redis

from database.models import User, LoginAttempt
from utils.hash_password import verify_password, get_password_hash
from utils.logger import logger
from config import settings

# Initialize Redis with error handling
try:
    redis_client = redis.from_url(
        settings.REDIS_CONNECTION_STRING,
        decode_responses=True
    )
    # Test connection
    redis_client.ping()
    REDIS_AVAILABLE = True
    logger.info("Redis connection established successfully")
except Exception as e:
    redis_client = None
    REDIS_AVAILABLE = False
    logger.warning(f"Redis connection failed: {e}. Using database fallback for account locking.")

def get_failed_login_key(email: str) -> str:
    """Generate a key for tracking failed login attempts"""
    return f"login_failures:{email}"

def is_account_locked(email: str) -> Tuple[bool, int]:
    """Check if account is locked and return remaining lock time"""
    if not settings.ENABLE_ACCOUNT_LOCKING:
        return False, 0  # Locking disabled
    
    # Try Redis first
    if REDIS_AVAILABLE:
        try:
            lock_key = f"account_lock:{email}"
            lock_until = redis_client.get(lock_key)
            if lock_until and float(lock_until) > time.time():
                return True, int(float(lock_until) - time.time())
            return False, 0
        except Exception as e:
            logger.error(f"Error checking account lock in Redis for {email}: {e}")
    
    return False, 0  # No cache available

def record_failed_login(email: str):
    """Record a failed login attempt and lock account if threshold is reached"""
    if not settings.ENABLE_ACCOUNT_LOCKING:
        return 1  # Locking disabled, return dummy count
    
    # Try Redis first
    if REDIS_AVAILABLE:
        try:
            key = get_failed_login_key(email)
            failures = redis_client.get(key)
            failures = int(failures) if failures else 0
            failures += 1
            
            if failures >= settings.MAX_LOGIN_ATTEMPTS:
                # Lock the account
                lock_until = time.time() + settings.LOCKOUT_TIME
                redis_client.setex(f"account_lock:{email}", settings.LOCKOUT_TIME, lock_until)
                logger.warning(f"Account locked for {email} after {failures} failed attempts")
                # Reset the failure counter
                redis_client.delete(key)
            else:
                # Store the failure count with expiration
                redis_client.setex(key, settings.LOCKOUT_TIME, failures)
            
            return failures
        except Exception as e:
            logger.error(f"Error recording failed login in Redis for {email}: {e}")
    
    logger.warning(f"Redis unavailable - cannot track failed login for {email}")
    return 1  # Return dummy count to prevent errors

def clear_login_attempts(email: str):
    """Clear failed login attempts for a successful login"""
    if not settings.ENABLE_ACCOUNT_LOCKING:
        return  # Locking disabled
    
    # Try Redis first
    if REDIS_AVAILABLE:
        try:
            redis_client.delete(get_failed_login_key(email))
            redis_client.delete(f"account_lock:{email}")
            return
        except Exception as e:
            logger.error(f"Error clearing login attempts in Redis for {email}: {e}")

# Database-based fallback functions
def is_account_locked_db(db: Session, email: str) -> Tuple[bool, int]:
    """Check if account is locked using database fallback"""
    if not settings.ENABLE_ACCOUNT_LOCKING:
        return False, 0  # Locking disabled
    
    try:
        # Count recent failed attempts within lockout window
        lockout_cutoff = datetime.utcnow() - timedelta(seconds=settings.LOCKOUT_TIME)
        recent_failures = db.query(LoginAttempt).filter(
            LoginAttempt.email == email,
            LoginAttempt.success == False,
            LoginAttempt.attempt_time > lockout_cutoff
        ).count()
        
        if recent_failures >= settings.MAX_LOGIN_ATTEMPTS:
            # Find the last failure time to calculate remaining lock time
            last_failure = db.query(LoginAttempt).filter(
                LoginAttempt.email == email,
                LoginAttempt.success == False
            ).order_by(LoginAttempt.attempt_time.desc()).first()
            
            if last_failure:
                lock_until = last_failure.attempt_time + timedelta(seconds=settings.LOCKOUT_TIME)
                remaining_seconds = int((lock_until - datetime.utcnow()).total_seconds())
                if remaining_seconds > 0:
                    return True, remaining_seconds
        
        return False, 0
    except Exception as e:
        logger.error(f"Error checking account lock in database for {email}: {e}")
        return False, 0

def record_failed_login_db(db: Session, email: str, ip_address: str = None, user_agent: str = None, failure_reason: str = None):
    """Record failed login attempt in database"""
    try:
        login_attempt = LoginAttempt(
            email=email,
            success=False,
            ip_address=ip_address,
            user_agent=user_agent,
            failure_reason=failure_reason
        )
        db.add(login_attempt)
        db.commit()
        
        # Check if this attempt should lock the account
        locked, remaining = is_account_locked_db(db, email)
        if locked:
            logger.warning(f"Account locked for {email} after too many failed attempts")
        
        return 1  # Return count for compatibility
    except Exception as e:
        logger.error(f"Error recording failed login in database for {email}: {e}")
        db.rollback()
        return 1

def clear_login_attempts_db(db: Session, email: str):
    """Clear failed login attempts in database (mark recent failures as cleared)"""
    try:
        # Delete recent failed attempts for this email
        lockout_cutoff = datetime.utcnow() - timedelta(seconds=settings.LOCKOUT_TIME)
        db.query(LoginAttempt).filter(
            LoginAttempt.email == email,
            LoginAttempt.success == False,
            LoginAttempt.attempt_time > lockout_cutoff
        ).delete()
        db.commit()
    except Exception as e:
        logger.error(f"Error clearing login attempts in database for {email}: {e}")
        db.rollback()

def record_successful_login_db(db: Session, email: str, ip_address: str = None, user_agent: str = None):
    """Record successful login attempt in database"""
    try:
        login_attempt = LoginAttempt(
            email=email,
            success=True,
            ip_address=ip_address,
            user_agent=user_agent
        )
        db.add(login_attempt)
        db.commit()
    except Exception as e:
        logger.error(f"Error recording successful login in database for {email}: {e}")
        db.rollback()
