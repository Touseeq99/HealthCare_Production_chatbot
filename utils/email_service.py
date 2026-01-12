import secrets
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session

from database.models import User
from config import settings
from utils.logger import logger


class EmailService:
    def __init__(self):
        # Handle optional email settings for testing
        self.api_key = settings.MAILCHIMP_API_KEY.get_secret_value() if settings.MAILCHIMP_API_KEY else None
        self.server_prefix = settings.MAILCHIMP_SERVER_PREFIX
        self.from_email = settings.FROM_EMAIL
        self.frontend_url = settings.FRONTEND_URL
        self.email_enabled = bool(self.api_key and self.server_prefix and self.from_email)

    def _send_email(
        self, 
        to_email: str, 
        subject: str, 
        html_body: str, 
        text_body: Optional[str] = None
    ) -> bool:
        """Send email using Mailchimp Transactional Email (Mandrill)"""
        if not self.email_enabled:
            logger.info(f"Email disabled. Would send to {to_email}: {subject}")
            return True
            
        try:
            # Use Mandrill API directly
            import requests
            
            # Mandrill API endpoint
            url = f"https://mandrillapp.com/api/1.0/messages/send.json"
            
            # Prepare message data
            message = {
                "from_email": self.from_email,
                "to": [{"email": to_email, "type": "to"}],
                "subject": subject,
                "html": html_body
            }
            
            if text_body:
                message["text"] = text_body
            
            # Send request
            response = requests.post(
                url,
                json={
                    "key": f"{self.api_key}-{self.server_prefix}",
                    "message": message
                },
                timeout=30
            )
            
            # Check response
            if response.status_code == 200:
                result = response.json()
                if result and len(result) > 0 and result[0].get("status") in ["sent", "queued"]:
                    logger.info(f"Email sent successfully to {to_email}")
                    return True
                else:
                    logger.error(f"Failed to send email to {to_email}: {result}")
                    return False
            else:
                logger.error(f"HTTP error sending email to {to_email}: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {str(e)}")
            return False

    def generate_verification_token(self) -> str:
        """Generate secure email verification token"""
        return secrets.token_urlsafe(32)

    def generate_reset_token(self) -> str:
        """Generate secure password reset token"""
        return secrets.token_urlsafe(32)

    def send_verification_email(self, user: User, db: Session) -> bool:
        """Send email verification email"""
        try:
            # Generate token and expiry
            token = self.generate_verification_token()
            expires_at = datetime.utcnow() + timedelta(hours=settings.EMAIL_VERIFICATION_EXPIRE_HOURS)
            
            # Update user record
            user.email_verification_token = token
            user.email_verification_expires = expires_at
            db.commit()
            
            # Create verification URL
            verification_url = f"{self.frontend_url}/verify-email?token={token}"
            
            # Email content
            subject = "Verify Your Email - Healthcare Portal"
            html_body = f"""
            <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px;">
                    <h2 style="color: #2c3e50; margin-bottom: 20px;">Welcome to Healthcare Portal</h2>
                    <p style="color: #34495e; line-height: 1.6;">
                        Thank you for registering with our healthcare portal. To complete your registration 
                        and ensure the security of your account, please verify your email address.
                    </p>
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{verification_url}" 
                           style="background-color: #3498db; color: white; padding: 12px 30px; 
                                  text-decoration: none; border-radius: 5px; display: inline-block;">
                            Verify Email Address
                        </a>
                    </div>
                    <p style="color: #7f8c8d; font-size: 14px;">
                        This link will expire in {settings.EMAIL_VERIFICATION_EXPIRE_HOURS} hours.<br>
                        If you didn't create an account, please ignore this email.
                    </p>
                    <hr style="border: 1px solid #ecf0f1; margin: 20px 0;">
                    <p style="color: #95a5a6; font-size: 12px;">
                        This is a secure, automated message from Healthcare Portal.
                    </p>
                </div>
            </body>
            </html>
            """
            
            text_body = f"""
            Welcome to Healthcare Portal
            
            Please verify your email address by clicking this link:
            {verification_url}
            
            This link will expire in {settings.EMAIL_VERIFICATION_EXPIRE_HOURS} hours.
            If you didn't create an account, please ignore this email.
            """
            
            return self._send_email(user.email, subject, html_body, text_body)
            
        except Exception as e:
            logger.error(f"Failed to send verification email to {user.email}: {str(e)}")
            return False

    def send_password_reset_email(self, user: User, db: Session) -> bool:
        """Send password reset email"""
        try:
            # Generate token and expiry
            token = self.generate_reset_token()
            expires_at = datetime.utcnow() + timedelta(hours=settings.PASSWORD_RESET_EXPIRE_HOURS)
            
            # Update user record
            user.password_reset_token = token
            user.password_reset_expires = expires_at
            db.commit()
            
            # Create reset URL
            reset_url = f"{self.frontend_url}/reset-password?token={token}"
            
            # Email content
            subject = "Reset Your Password - Healthcare Portal"
            html_body = f"""
            <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px;">
                    <h2 style="color: #2c3e50; margin-bottom: 20px;">Password Reset Request</h2>
                    <p style="color: #34495e; line-height: 1.6;">
                        We received a request to reset your password for your Healthcare Portal account. 
                        Click the button below to reset your password.
                    </p>
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{reset_url}" 
                           style="background-color: #e74c3c; color: white; padding: 12px 30px; 
                                  text-decoration: none; border-radius: 5px; display: inline-block;">
                            Reset Password
                        </a>
                    </div>
                    <p style="color: #7f8c8d; font-size: 14px;">
                        This link will expire in {settings.PASSWORD_RESET_EXPIRE_HOURS} hours.<br>
                        If you didn't request this password reset, please ignore this email.
                    </p>
                    <hr style="border: 1px solid #ecf0f1; margin: 20px 0;">
                    <p style="color: #95a5a6; font-size: 12px;">
                        This is a secure, automated message from Healthcare Portal.
                    </p>
                </div>
            </body>
            </html>
            """
            
            text_body = f"""
            Password Reset Request - Healthcare Portal
            
            Please reset your password by clicking this link:
            {reset_url}
            
            This link will expire in {settings.PASSWORD_RESET_EXPIRE_HOURS} hours.
            If you didn't request this password reset, please ignore this email.
            """
            
            return self._send_email(user.email, subject, html_body, text_body)
            
        except Exception as e:
            logger.error(f"Failed to send password reset email to {user.email}: {str(e)}")
            return False

    def verify_email_token(self, token: str, db: Session) -> Optional[User]:
        """Verify email token and mark email as verified"""
        try:
            user = db.query(User).filter(
                User.email_verification_token == token,
                User.email_verification_expires > datetime.utcnow()
            ).first()
            
            if user:
                user.email_verified = True
                user.email_verification_token = None
                user.email_verification_expires = None
                db.commit()
                logger.info(f"Email verified for user {user.email}")
                return user
            
            return None
            
        except Exception as e:
            logger.error(f"Error verifying email token: {str(e)}")
            return None

    def verify_password_reset_token(self, token: str, db: Session) -> Optional[User]:
        """Verify password reset token"""
        try:
            user = db.query(User).filter(
                User.password_reset_token == token,
                User.password_reset_expires > datetime.utcnow()
            ).first()
            
            if user:
                logger.info(f"Valid password reset token for user {user.email}")
                return user
            
            return None
            
        except Exception as e:
            logger.error(f"Error verifying password reset token: {str(e)}")
            return None

    def clear_password_reset_token(self, user: User, db: Session) -> None:
        """Clear password reset token after successful reset"""
        try:
            user.password_reset_token = None
            user.password_reset_expires = None
            db.commit()
            logger.info(f"Password reset token cleared for user {user.email}")
        except Exception as e:
            logger.error(f"Error clearing password reset token: {str(e)}")


# Create singleton instance
email_service = EmailService()
