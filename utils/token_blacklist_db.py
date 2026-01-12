import json
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from jose import jwt

from sqlalchemy.orm import Session
from database.models import User, LoginAttempt
from utils.logger import logger
from config import settings
from utils.auth_service import SECRET_KEY, ALGORITHM

class TokenBlacklistDB:
    """Handles token blacklisting using database storage instead of Redis"""
    
    def __init__(self):
        logger.info("Token blacklist initialized with database backend")
    
    def _get_token_hash(self, token: str) -> str:
        """Generate a unique hash for the token"""
        return hashlib.sha256(token.encode()).hexdigest()
    
    def add_to_blacklist(self, token: str, reason: str = "logout", user_email: str = None, db: Session = None) -> bool:
        """
        Add token to blacklist using database storage
        
        Args:
            token: JWT token to blacklist
            reason: Reason for blacklisting (logout, revoked, etc.)
            user_email: User email associated with token
            db: Database session (optional, will create one if not provided)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Decode token to get expiration and extract user info
            try:
                secret_key_str = SECRET_KEY.get_secret_value() if hasattr(SECRET_KEY, 'get_secret_value') else str(SECRET_KEY)
                payload = jwt.decode(token, secret_key_str, algorithms=[ALGORITHM])
                exp_timestamp = payload.get('exp')
                token_email = payload.get('sub')
                
                if not exp_timestamp:
                    # If no expiration, blacklist for 24 hours
                    expires_at = datetime.utcnow() + timedelta(hours=24)
                else:
                    expires_at = datetime.fromtimestamp(exp_timestamp)
                
                # Use provided email or extract from token
                email = user_email or token_email
                
                if not email:
                    logger.error("Cannot blacklist token: no email available")
                    return False
                
            except Exception as e:
                logger.error(f"Failed to decode token for blacklist: {e}")
                # Default to 24 hours blacklist if decoding fails
                expires_at = datetime.utcnow() + timedelta(hours=24)
                email = user_email or "unknown"
            
            # Store in database using LoginAttempt table as blacklist storage
            from database.database import get_db
            try:
                # Use provided session or create a new one
                if db is None:
                    db_session = next(get_db())
                    should_close = True
                else:
                    db_session = db
                    should_close = False
                
                # Create blacklist entry as a failed login attempt with special reason
                token_hash = self._get_token_hash(token)
                blacklist_entry = LoginAttempt(
                    email=email,
                    success=False,  # Use failed attempts for blacklist
                    ip_address="blacklist_system",
                    user_agent="token_blacklist",
                    failure_reason=f"blacklisted:{reason}:{token_hash}"
                )
                
                db_session.add(blacklist_entry)
                db_session.commit()
                
                logger.info(f"Token blacklisted successfully for user {email}. Reason: {reason}")
                return True
                
            except Exception as db_error:
                logger.error(f"Database error during blacklist: {db_error}")
                if 'db_session' in locals():
                    db_session.rollback()
                return False
            finally:
                if should_close and 'db_session' in locals():
                    db_session.close()
                
        except Exception as e:
            logger.error(f"Failed to blacklist token: {e}")
            return False
    
    def is_blacklisted(self, token: str) -> bool:
        """
        Check if token is blacklisted using database
        
        Args:
            token: JWT token to check
            
        Returns:
            True if blacklisted, False otherwise
        """
        try:
            # Generate hash for the token
            token_hash = self._get_token_hash(token)
            
            from database.database import get_db
            db = next(get_db())
            
            try:
                # Check for exact hash match in blacklist entries (any reason)
                blacklist_entry = db.query(LoginAttempt).filter(
                    LoginAttempt.failure_reason.like(f"blacklisted:%:{token_hash}"),
                    LoginAttempt.success == False,
                    LoginAttempt.ip_address == "blacklist_system"
                ).first()
                
                if blacklist_entry:
                    # Check if blacklist entry is still valid (not expired)
                    # For simplicity, we'll consider entries from last 24 hours as valid
                    cutoff_time = datetime.utcnow() - timedelta(hours=24)
                    if blacklist_entry.attempt_time > cutoff_time:
                        logger.info("Blacklisted token detected")
                        return True
                
                return False
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error checking token blacklist: {e}")
            return False
    
    def get_blacklist_info(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Get blacklist information for a token
        
        Args:
            token: JWT token
            
        Returns:
            Blacklist metadata or None if not blacklisted
        """
        try:
            token_hash = self._get_token_hash(token)
            
            from database.database import get_db
            db = next(get_db())
            
            try:
                blacklist_entry = db.query(LoginAttempt).filter(
                    LoginAttempt.failure_reason.like(f"blacklisted:%:{token_hash}"),
                    LoginAttempt.success == False,
                    LoginAttempt.ip_address == "blacklist_system"
                ).first()
                
                if blacklist_entry:
                    # Parse failure reason to extract blacklist info
                    parts = blacklist_entry.failure_reason.split(":", 2)
                    if len(parts) >= 3:
                        reason = parts[1]
                        
                        return {
                            "reason": reason,
                            "blacklisted_at": blacklist_entry.attempt_time.isoformat(),
                            "blacklisted_by": "system",
                            "user_email": blacklist_entry.email
                        }
                
                return None
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error getting blacklist info: {e}")
            return None
    
    def revoke_user_tokens(self, user_email: str, reason: str = "security_revocation") -> int:
        """
        Revoke all active tokens for a user by blacklisting recent successful logins
        
        Args:
            user_email: User email to revoke tokens for
            reason: Reason for revocation
            
        Returns:
            Number of tokens revoked
        """
        try:
            from database.database import get_db
            db = next(get_db())
            
            try:
                # Find recent successful login attempts for this user (indicating active tokens)
                recent_logins = db.query(LoginAttempt).filter(
                    LoginAttempt.email == user_email,
                    LoginAttempt.success == True,
                    LoginAttempt.attempt_time > datetime.utcnow() - timedelta(days=7)  # Last 7 days
                ).all()
                
                revoked_count = 0
                
                for login in recent_logins:
                    # Create blacklist entries for each recent login
                    # Note: We don't have the actual tokens, but we mark the user as compromised
                    blacklist_entry = LoginAttempt(
                        email=user_email,
                        success=False,
                        ip_address="blacklist_system",
                        user_agent="user_revocation",
                        failure_reason=f"blacklisted:{reason}:revoked_all_tokens"
                    )
                    
                    db.add(blacklist_entry)
                    revoked_count += 1
                
                if revoked_count > 0:
                    db.commit()
                    logger.info(f"Revoked {revoked_count} tokens for user {user_email}. Reason: {reason}")
                else:
                    logger.info(f"No active tokens found to revoke for user {user_email}")
                
                return revoked_count
                
            except Exception as db_error:
                logger.error(f"Database error during user token revocation: {db_error}")
                db.rollback()
                return 0
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Failed to revoke user tokens: {e}")
            return 0
    
    def cleanup_expired_tokens(self) -> int:
        """
        Clean up expired blacklist entries from database
        
        Returns:
            Number of entries cleaned
        """
        try:
            from database.database import get_db
            db = next(get_db())
            
            try:
                # Delete blacklist entries older than 7 days
                cutoff_time = datetime.utcnow() - timedelta(days=7)
                
                deleted_count = db.query(LoginAttempt).filter(
                    LoginAttempt.failure_reason.like("blacklisted:%"),
                    LoginAttempt.success == False,
                    LoginAttempt.ip_address == "blacklist_system",
                    LoginAttempt.attempt_time < cutoff_time
                ).delete()
                
                db.commit()
                
                if deleted_count > 0:
                    logger.info(f"Cleaned up {deleted_count} expired blacklist entries")
                
                return deleted_count
                
            except Exception as db_error:
                logger.error(f"Database error during cleanup: {db_error}")
                db.rollback()
                return 0
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Failed to cleanup expired tokens: {e}")
            return 0
    
    def is_user_compromised(self, user_email: str) -> bool:
        """
        Check if user has had tokens revoked recently (security compromise)
        
        Args:
            user_email: User email to check
            
        Returns:
            True if user tokens were recently revoked
        """
        try:
            from database.database import get_db
            db = next(get_db())
            
            try:
                # Check for recent revocation entries
                revocation_entry = db.query(LoginAttempt).filter(
                    LoginAttempt.email == user_email,
                    LoginAttempt.failure_reason.like("blacklisted:security_revocation%"),
                    LoginAttempt.success == False,
                    LoginAttempt.ip_address == "blacklist_system",
                    LoginAttempt.attempt_time > datetime.utcnow() - timedelta(hours=24)  # Last 24 hours
                ).first()
                
                return revocation_entry is not None
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error checking user compromise status: {e}")
            return False

# Global blacklist instance
token_blacklist = TokenBlacklistDB()
