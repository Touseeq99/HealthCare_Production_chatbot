from datetime import datetime, timedelta
from typing import Optional, Tuple
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from jose import JWTError, jwt
import secrets
import string

from database.models import User, RefreshToken
from utils.auth_service import SECRET_KEY, ALGORITHM
from utils.logger import logger
from config import settings

class RefreshTokenService:
    """Service for managing refresh tokens"""
    
    @staticmethod
    def generate_refresh_token() -> str:
        """Generate a secure random refresh token"""
        # Generate a cryptographically secure random token
        alphabet = string.ascii_letters + string.digits
        token = ''.join(secrets.choice(alphabet) for _ in range(64))
        return f"refresh_{token}"
    
    @staticmethod
    def create_refresh_token(
        db: Session, 
        user: User, 
        ip_address: str = None, 
        user_agent: str = None
    ) -> RefreshToken:
        """
        Create a new refresh token for a user
        
        Args:
            db: Database session
            user: User object
            ip_address: Client IP address
            user_agent: Client user agent
            
        Returns:
            RefreshToken object
        """
        try:
            # Clean up old/expired tokens for this user
            RefreshTokenService.cleanup_user_tokens(db, user.id)
            
            # Check if user has too many active refresh tokens
            active_tokens = db.query(RefreshToken).filter(
                RefreshToken.user_id == user.id,
                RefreshToken.is_revoked == False,
                RefreshToken.expires_at > datetime.utcnow()
            ).count()
            
            if active_tokens >= settings.REFRESH_TOKEN_MAX_COUNT:
                # Revoke oldest token
                oldest_token = db.query(RefreshToken).filter(
                    RefreshToken.user_id == user.id,
                    RefreshToken.is_revoked == False
                ).order_by(RefreshToken.created_at).first()
                
                if oldest_token:
                    oldest_token.is_revoked = True
                    db.commit()
                    logger.info(f"Revoked oldest refresh token for user {user.email} due to limit")
            
            # Create new refresh token
            token_string = RefreshTokenService.generate_refresh_token()
            expires_at = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
            
            refresh_token = RefreshToken(
                token=token_string,
                user_id=user.id,
                expires_at=expires_at,
                ip_address=ip_address,
                user_agent=user_agent
            )
            
            db.add(refresh_token)
            db.commit()
            
            logger.info(f"Created refresh token for user {user.email}")
            return refresh_token
            
        except Exception as e:
            logger.error(f"Failed to create refresh token for user {user.email}: {e}")
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create refresh token"
            )
    
    @staticmethod
    def validate_refresh_token(db: Session, token: str) -> Tuple[Optional[RefreshToken], Optional[User]]:
        """
        Validate a refresh token and return the token and user
        
        Args:
            db: Database session
            token: Refresh token string
            
        Returns:
            Tuple of (RefreshToken, User) or (None, None) if invalid
        """
        try:
            # Find the refresh token
            refresh_token = db.query(RefreshToken).filter(
                RefreshToken.token == token,
                RefreshToken.is_revoked == False
            ).first()
            
            if not refresh_token:
                logger.warning("Refresh token not found or revoked")
                return None, None
            
            # Check if token is expired
            if refresh_token.expires_at < datetime.utcnow():
                logger.warning(f"Refresh token expired for user {refresh_token.user.email}")
                # Mark as revoked
                refresh_token.is_revoked = True
                db.commit()
                return None, None
            
            # Get the user
            user = db.query(User).filter(User.id == refresh_token.user_id).first()
            if not user:
                logger.error(f"User not found for refresh token: {refresh_token.user_id}")
                return None, None
            
            # Update last used timestamp
            refresh_token.last_used_at = datetime.utcnow()
            db.commit()
            
            return refresh_token, user
            
        except Exception as e:
            logger.error(f"Error validating refresh token: {e}")
            return None, None
    
    @staticmethod
    def revoke_refresh_token(db: Session, token: str) -> bool:
        """
        Revoke a specific refresh token
        
        Args:
            db: Database session
            token: Refresh token string
            
        Returns:
            True if revoked, False if not found
        """
        try:
            refresh_token = db.query(RefreshToken).filter(
                RefreshToken.token == token,
                RefreshToken.is_revoked == False
            ).first()
            
            if refresh_token:
                refresh_token.is_revoked = True
                db.commit()
                logger.info(f"Revoked refresh token for user {refresh_token.user.email}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error revoking refresh token: {e}")
            db.rollback()
            return False
    
    @staticmethod
    def revoke_all_user_tokens(db: Session, user_id: int) -> int:
        """
        Revoke all refresh tokens for a user
        
        Args:
            db: Database session
            user_id: User ID
            
        Returns:
            Number of tokens revoked
        """
        try:
            tokens = db.query(RefreshToken).filter(
                RefreshToken.user_id == user_id,
                RefreshToken.is_revoked == False
            ).all()
            
            revoked_count = 0
            for token in tokens:
                token.is_revoked = True
                revoked_count += 1
            
            db.commit()
            logger.info(f"Revoked {revoked_count} refresh tokens for user ID {user_id}")
            return revoked_count
            
        except Exception as e:
            logger.error(f"Error revoking all user tokens: {e}")
            db.rollback()
            return 0
    
    @staticmethod
    def cleanup_user_tokens(db: Session, user_id: int) -> int:
        """
        Clean up expired and revoked tokens for a user
        
        Args:
            db: Database session
            user_id: User ID
            
        Returns:
            Number of tokens cleaned up
        """
        try:
            # Delete expired and revoked tokens older than 30 days
            cutoff_time = datetime.utcnow() - timedelta(days=30)
            
            deleted_count = db.query(RefreshToken).filter(
                RefreshToken.user_id == user_id,
                RefreshToken.expires_at < cutoff_time
            ).delete()
            
            db.commit()
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error cleaning up user tokens: {e}")
            db.rollback()
            return 0
    
    @staticmethod
    def cleanup_all_expired_tokens(db: Session) -> int:
        """
        Clean up all expired refresh tokens
        
        Args:
            db: Database session
            
        Returns:
            Number of tokens cleaned up
        """
        try:
            # Delete expired tokens older than 7 days
            cutoff_time = datetime.utcnow() - timedelta(days=7)
            
            deleted_count = db.query(RefreshToken).filter(
                RefreshToken.expires_at < cutoff_time
            ).delete()
            
            db.commit()
            logger.info(f"Cleaned up {deleted_count} expired refresh tokens")
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error cleaning up expired tokens: {e}")
            db.rollback()
            return 0
    
    @staticmethod
    def get_user_active_tokens(db: Session, user_id: int) -> list:
        """
        Get all active refresh tokens for a user
        
        Args:
            db: Database session
            user_id: User ID
            
        Returns:
            List of RefreshToken objects
        """
        try:
            return db.query(RefreshToken).filter(
                RefreshToken.user_id == user_id,
                RefreshToken.is_revoked == False,
                RefreshToken.expires_at > datetime.utcnow()
            ).order_by(RefreshToken.created_at.desc()).all()
            
        except Exception as e:
            logger.error(f"Error getting user active tokens: {e}")
            return []

# Global refresh token service instance
refresh_token_service = RefreshTokenService()
