import pytest
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from jose import jwt

# Import app directly from main.py
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from database.models import User, LoginAttempt
from utils.token_validator import TokenValidator, TokenValidationError, create_token_validation_error
from utils.token_blacklist_db import TokenBlacklistDB
from utils.auth_service import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, create_access_token
from config import settings

# Test Client
client = TestClient(app)

class TestTokenValidator:
    """Test suite for TokenValidator class"""
    
    def setup_method(self):
        """Setup test data"""
        self.secret_key = "test_secret_key"
        self.algorithm = "HS256"
        self.test_email = "test@example.com"
        self.test_payload = {
            "sub": self.test_email,
            "role": "patient",
            "exp": int((datetime.utcnow() + timedelta(hours=1)).timestamp())
        }
        self.valid_token = jwt.encode(self.test_payload, self.secret_key, self.algorithm)
    
    @patch('utils.token_validator.SECRET_KEY')
    def test_decode_token_valid(self, mock_secret):
        """Test decoding a valid token"""
        mock_secret.get_secret_value.return_value = self.secret_key
        mock_secret.__str__ = Mock(return_value=self.secret_key)
        
        payload = TokenValidator.decode_token(self.valid_token)
        
        assert payload["sub"] == self.test_email
        assert payload["role"] == "patient"
    
    @patch('utils.token_validator.SECRET_KEY')
    def test_decode_token_expired(self, mock_secret):
        """Test decoding an expired token"""
        # Create expired token
        expired_payload = self.test_payload.copy()
        expired_payload["exp"] = int((datetime.utcnow() - timedelta(hours=1)).timestamp())
        expired_token = jwt.encode(expired_payload, self.secret_key, self.algorithm)
        
        mock_secret.get_secret_value.return_value = self.secret_key
        mock_secret.__str__ = Mock(return_value=self.secret_key)
        
        with pytest.raises(TokenValidationError) as exc_info:
            TokenValidator.decode_token(expired_token)
        
        assert exc_info.value.error_type == "expired"
        assert "expired" in str(exc_info.value).lower()
    
    @patch('utils.token_validator.SECRET_KEY')
    def test_decode_token_invalid_signature(self, mock_secret):
        """Test decoding token with invalid signature"""
        mock_secret.get_secret_value.return_value = "wrong_secret"
        mock_secret.__str__ = Mock(return_value="wrong_secret")
        
        with pytest.raises(TokenValidationError) as exc_info:
            TokenValidator.decode_token(self.valid_token)
        
        assert exc_info.value.error_type == "signature_invalid"
    
    def test_decode_token_malformed(self):
        """Test decoding a malformed token"""
        malformed_token = "this.is.not.a.valid.jwt"
        
        with pytest.raises(TokenValidationError) as exc_info:
            TokenValidator.decode_token(malformed_token)
        
        assert exc_info.value.error_type == "invalid_format"
    
    def test_validate_token_payload_valid(self):
        """Test validating a valid token payload"""
        email = TokenValidator.validate_token_payload(self.test_payload)
        assert email == self.test_email
    
    def test_validate_token_payload_missing_email(self):
        """Test validating payload without email"""
        invalid_payload = {"role": "patient"}
        
        with pytest.raises(TokenValidationError) as exc_info:
            TokenValidator.validate_token_payload(invalid_payload)
        
        assert exc_info.value.error_type == "missing_claims"
    
    def test_validate_token_payload_invalid_email(self):
        """Test validating payload with invalid email format"""
        invalid_payload = {"sub": "invalid_email", "role": "patient"}
        
        with pytest.raises(TokenValidationError) as exc_info:
            TokenValidator.validate_token_payload(invalid_payload)
        
        assert exc_info.value.error_type == "invalid_email"
    
    @patch('utils.token_validator.TokenValidator.verify_user_exists')
    @patch('utils.token_validator.TokenValidator.validate_token_payload')
    @patch('utils.token_validator.TokenValidator.decode_token')
    def test_validate_token_complete_success(self, mock_decode, mock_validate, mock_verify):
        """Test complete token validation pipeline"""
        mock_decode.return_value = self.test_payload
        mock_validate.return_value = self.test_email
        mock_verify.return_value = Mock(spec=User)
        
        mock_db = Mock(spec=Session)
        result = TokenValidator.validate_token_complete(self.valid_token, mock_db)
        
        assert result is not None
        mock_decode.assert_called_once_with(self.valid_token)
        mock_validate.assert_called_once_with(self.test_payload)
        mock_verify.assert_called_once_with(mock_db, self.test_email)

class TestTokenBlacklistDB:
    """Test suite for TokenBlacklistDB class"""
    
    def setup_method(self):
        """Setup test data"""
        self.blacklist = TokenBlacklistDB()
        self.test_token = "test.jwt.token"
        self.test_email = "test@example.com"
    
    @patch('utils.token_blacklist_db.get_db')
    @patch('utils.token_blacklist_db.jwt')
    def test_add_to_blacklist_success(self, mock_jwt, mock_get_db):
        """Test successfully adding token to blacklist"""
        # Mock database session
        mock_db = Mock()
        mock_get_db.return_value = iter([mock_db])  # Make it an iterator for context manager
        
        # Mock JWT decode
        mock_jwt.decode.return_value = {
            "sub": self.test_email,
            "exp": int(time.time() + 3600)
        }
        
        result = self.blacklist.add_to_blacklist(self.test_token, "logout", self.test_email)
        
        assert result is True
        mock_db.add.assert_called()
        mock_db.commit.assert_called()
    
    @patch('utils.token_blacklist_db.get_db')
    def test_add_to_blacklist_db_error(self, mock_get_db):
        """Test adding token to blacklist when database fails"""
        mock_db = Mock()
        mock_db.commit.side_effect = Exception("Database error")
        mock_get_db.return_value = iter([mock_db])
        
        result = self.blacklist.add_to_blacklist(self.test_token, "logout", self.test_email)
        
        assert result is False
    
    @patch('utils.token_blacklist_db.get_db')
    def test_is_blacklisted_true(self, mock_get_db):
        """Test checking if token is blacklisted - returns True"""
        # Mock database query result
        mock_entry = Mock()
        mock_entry.attempt_time = datetime.utcnow()
        
        mock_query = Mock()
        mock_query.filter.return_value.first.return_value = mock_entry
        
        mock_db = Mock()
        mock_db.query.return_value = mock_query
        mock_get_db.return_value = iter([mock_db])
        
        result = self.blacklist.is_blacklisted(self.test_token)
        
        assert result is True
    
    @patch('utils.token_blacklist_db.get_db')
    def test_is_blacklisted_false(self, mock_get_db):
        """Test checking if token is blacklisted - returns False"""
        # Mock database query result - no entry found
        mock_query = Mock()
        mock_query.filter.return_value.first.return_value = None
        
        mock_db = Mock()
        mock_db.query.return_value = mock_query
        mock_get_db.return_value = iter([mock_db])
        
        result = self.blacklist.is_blacklisted(self.test_token)
        
        assert result is False
    
    @patch('utils.token_blacklist_db.get_db')
    def test_revoke_user_tokens(self, mock_get_db):
        """Test revoking all tokens for a user"""
        # Mock recent login attempts
        mock_login1 = Mock()
        mock_login2 = Mock()
        
        mock_db = Mock()
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_login1, mock_login2]
        mock_get_db.return_value = iter([mock_db])
        
        result = self.blacklist.revoke_user_tokens(self.test_email, "security_revocation")
        
        assert result == 2  # Two tokens revoked
        assert mock_db.add.call_count == 2
        mock_db.commit.assert_called()
    
    @patch('utils.token_blacklist_db.get_db')
    def test_cleanup_expired_tokens(self, mock_get_db):
        """Test cleaning up expired blacklist entries"""
        mock_db = Mock()
        mock_db.query.return_value.filter.return_value.delete.return_value = 5
        mock_get_db.return_value = iter([mock_db])
        
        result = self.blacklist.cleanup_expired_tokens()
        
        assert result == 5
        mock_db.commit.assert_called()

class TestAuthEndpoints:
    """Test suite for authentication endpoints"""
    
    def setup_method(self):
        """Setup test data"""
        self.test_user = {
            "email": "test@example.com",
            "password": "testpassword123",
            "name": "Test",
            "surname": "User",
            "role": "patient"
        }
    
    @patch('api.auth.authenticate_user')
    @patch('api.auth.create_access_token')
    @patch('api.auth.get_db')
    def test_login_success(self, mock_get_db, mock_create_token, mock_authenticate):
        """Test successful login"""
        # Mock dependencies
        mock_db = Mock()
        mock_get_db.return_value = mock_db
        
        mock_user = Mock(spec=User)
        mock_user.email = self.test_user["email"]
        mock_user.name = self.test_user["name"]
        mock_user.role = self.test_user["role"]
        mock_authenticate.return_value = mock_user
        
        mock_create_token.return_value = "test_jwt_token"
        
        # Make request
        response = client.post("/api/auth/token", json=self.test_user)
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["token"] == "test_jwt_token"
        assert data["user"]["email"] == self.test_user["email"]
    
    def test_login_invalid_credentials(self):
        """Test login with invalid credentials"""
        invalid_user = self.test_user.copy()
        invalid_user["password"] = "wrongpassword"
        
        response = client.post("/api/auth/token", json=invalid_user)
        
        # Should return 401 due to invalid credentials
        assert response.status_code == 401
    
    @patch('api.auth.get_current_user')
    def test_verify_token_success(self, mock_get_user):
        """Test token verification success"""
        mock_user = Mock(spec=User)
        mock_user.email = self.test_user["email"]
        mock_get_user.return_value = mock_user
        
        response = client.get("/api/auth/verify-token", headers={
            "Authorization": "Bearer valid_token"
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "valid"
        assert data["user"] == self.test_user["email"]
    
    def test_verify_token_no_token(self):
        """Test token verification without token"""
        response = client.get("/api/auth/verify-token")
        
        assert response.status_code == 401
    
    @patch('api.auth.get_current_user')
    @patch('api.auth.token_blacklist')
    def test_logout_success(self, mock_blacklist, mock_get_user):
        """Test successful logout"""
        mock_user = Mock(spec=User)
        mock_user.email = self.test_user["email"]
        mock_get_user.return_value = mock_user
        
        mock_blacklist.add_to_blacklist.return_value = True
        
        response = client.post("/api/auth/logout", headers={
            "Authorization": "Bearer valid_token"
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "Logout successful" in data["message"]
    
    def test_logout_no_token(self):
        """Test logout without token"""
        response = client.post("/api/auth/logout")
        
        assert response.status_code == 401

class TestTokenValidationErrors:
    """Test suite for token validation error handling"""
    
    def test_create_token_validation_error_expired(self):
        """Test creating HTTP exception for expired token"""
        error = TokenValidationError("Token expired", "expired")
        http_exception = create_token_validation_error(error)
        
        assert http_exception.status_code == 401
        assert "expired" in http_exception.detail["message"]
        assert http_exception.detail["error_type"] == "expired"
    
    def test_create_token_validation_error_invalid_signature(self):
        """Test creating HTTP exception for invalid signature"""
        error = TokenValidationError("Invalid signature", "signature_invalid")
        http_exception = create_token_validation_error(error)
        
        assert http_exception.status_code == 401
        assert "signature" in http_exception.detail["message"]
        assert http_exception.detail["error_type"] == "signature_invalid"
    
    def test_create_token_validation_error_user_not_found(self):
        """Test creating HTTP exception for user not found"""
        error = TokenValidationError("User not found", "user_not_found")
        http_exception = create_token_validation_error(error)
        
        assert http_exception.status_code == 401
        assert "not found" in http_exception.detail["message"]
        assert http_exception.detail["error_type"] == "user_not_found"

class TestIntegrationFlow:
    """Integration tests for complete authentication flow"""
    
    def setup_method(self):
        """Setup integration test data"""
        self.base_url = "/api/auth"
    
    @patch('api.auth.authenticate_user')
    @patch('api.auth.create_access_token')
    @patch('api.auth.get_db')
    @patch('api.auth.get_current_user')
    @patch('api.auth.token_blacklist')
    def test_complete_auth_flow(self, mock_blacklist, mock_get_user, mock_get_db, mock_create_token, mock_authenticate):
        """Test complete authentication flow: login -> verify -> logout"""
        # Setup mocks
        mock_db = Mock()
        mock_get_db.return_value = mock_db
        
        mock_user = Mock(spec=User)
        mock_user.email = "test@example.com"
        mock_user.name = "Test"
        mock_user.role = "patient"
        mock_authenticate.return_value = mock_user
        mock_get_user.return_value = mock_user
        
        mock_create_token.return_value = "test_jwt_token"
        mock_blacklist.add_to_blacklist.return_value = True
        
        # Step 1: Login
        login_response = client.post(f"{self.base_url}/token", json={
            "email": "test@example.com",
            "password": "password123",
            "role": "patient"
        })
        
        assert login_response.status_code == 200
        token = login_response.json()["token"]
        
        # Step 2: Verify token
        verify_response = client.get(f"{self.base_url}/verify-token", headers={
            "Authorization": f"Bearer {token}"
        })
        
        assert verify_response.status_code == 200
        assert verify_response.json()["status"] == "valid"
        
        # Step 3: Logout
        logout_response = client.post(f"{self.base_url}/logout", headers={
            "Authorization": f"Bearer {token}"
        })
        
        assert logout_response.status_code == 200
        assert logout_response.json()["success"] is True

if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v", "--tb=short"])
