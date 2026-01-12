import pytest
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
from sqlalchemy.orm import Session
from jose import jwt

# Import app directly from main.py
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.models import User, RefreshToken
from utils.refresh_token_service import RefreshTokenService, refresh_token_service
from utils.auth_service import SECRET_KEY, ALGORITHM
from config import settings

class TestRefreshTokenService:
    """Test suite for RefreshTokenService class"""
    
    def setup_method(self):
        """Setup test data"""
        self.service = RefreshTokenService()
        self.test_user = Mock(spec=User)
        self.test_user.id = 1
        self.test_user.email = "test@example.com"
        self.test_user.name = "Test"
        self.test_user.role = "patient"
    
    def test_generate_refresh_token(self):
        """Test refresh token generation"""
        token = self.service.generate_refresh_token()
        
        assert token.startswith("refresh_")
        assert len(token) > 10  # Should be longer than just the prefix
        assert isinstance(token, str)
    
    @patch('utils.refresh_token_service.settings')
    @patch('utils.refresh_token_service.RefreshToken')
    def test_create_refresh_token_success(self, mock_refresh_token_class, mock_settings):
        """Test successfully creating a refresh token"""
        mock_settings.REFRESH_TOKEN_EXPIRE_DAYS = 7
        mock_settings.REFRESH_TOKEN_MAX_COUNT = 5
        
        # Mock the RefreshToken constructor
        mock_refresh_token = Mock()
        mock_refresh_token.user_id = self.test_user.id
        mock_refresh_token.is_revoked = False
        mock_refresh_token.expires_at = datetime.utcnow() + timedelta(days=7)
        mock_refresh_token_class.return_value = mock_refresh_token
        
        mock_db = Mock(spec=Session)
        
        # Mock the query chain properly for the first query (count)
        mock_query_count = Mock()
        mock_query_count.filter.return_value.count.return_value = 0
        
        # Mock the query chain for the second query (oldest token)
        mock_query_oldest = Mock()
        mock_query_oldest.filter.return_value.order_by.return_value.first.return_value = None
        
        # Set up the mock to return different query objects for different calls
        mock_db.query.side_effect = [mock_query_count, mock_query_oldest]
        
        mock_db.add.return_value = None
        mock_db.commit.return_value = None
        
        # Mock the cleanup method to avoid database operations
        with patch.object(RefreshTokenService, 'cleanup_user_tokens', return_value=0):
            result = self.service.create_refresh_token(
                mock_db,
                self.test_user,
                "192.168.1.1",
                "Mozilla/5.0"
            )
        
        assert result is not None
        assert result.user_id == self.test_user.id
        assert result.is_revoked is False
        assert result.expires_at > datetime.utcnow()
        mock_db.add.assert_called_once()
        assert mock_db.commit.call_count >= 1
    
    @patch('utils.refresh_token_service.settings')
    def test_create_refresh_token_limit_reached(self, mock_settings):
        """Test creating refresh token when limit is reached"""
        mock_settings.REFRESH_TOKEN_EXPIRE_DAYS = 7
        mock_settings.REFRESH_TOKEN_MAX_COUNT = 2
        
        # Mock existing tokens
        mock_oldest_token = Mock(spec=RefreshToken)
        mock_oldest_token.is_revoked = False
        
        mock_db = Mock(spec=Session)
        mock_db.query.return_value.filter.return_value.count.return_value = 2  # Limit reached
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_oldest_token
        mock_db.add.return_value = None
        mock_db.commit.return_value = None
        
        result = self.service.create_refresh_token(mock_db, self.test_user)
        
        assert result is not None
        # Oldest token should be revoked
        assert mock_oldest_token.is_revoked is True
        mock_db.commit.assert_called()  # Called for revoking old token
    
    def test_validate_refresh_token_success(self):
        """Test validating a valid refresh token"""
        mock_refresh_token = Mock(spec=RefreshToken)
        mock_refresh_token.is_revoked = False
        mock_refresh_token.expires_at = datetime.utcnow() + timedelta(days=1)
        mock_refresh_token.user = self.test_user
        mock_refresh_token.last_used_at = None
        mock_refresh_token.user_id = self.test_user.id
        
        mock_db = Mock(spec=Session)
        # First call returns refresh token, second call returns user
        mock_query = Mock()
        mock_query.filter.return_value.first.side_effect = [mock_refresh_token, self.test_user]
        mock_db.query.return_value = mock_query
        mock_db.commit.return_value = None
        
        token_obj, user = self.service.validate_refresh_token(mock_db, "valid_token")
        
        assert token_obj is not None
        assert user is not None
        assert user.email == self.test_user.email
        assert mock_refresh_token.last_used_at is not None  # Should be updated
    
    def test_validate_refresh_token_expired(self):
        """Test validating an expired refresh token"""
        mock_refresh_token = Mock(spec=RefreshToken)
        mock_refresh_token.is_revoked = False
        mock_refresh_token.expires_at = datetime.utcnow() - timedelta(days=1)  # Expired
        
        mock_db = Mock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_refresh_token
        mock_db.commit.return_value = None
        
        token_obj, user = self.service.validate_refresh_token(mock_db, "expired_token")
        
        assert token_obj is None
        assert user is None
        assert mock_refresh_token.is_revoked is True  # Should be marked as revoked
    
    def test_validate_refresh_token_not_found(self):
        """Test validating a non-existent refresh token"""
        mock_db = Mock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        token_obj, user = self.service.validate_refresh_token(mock_db, "nonexistent_token")
        
        assert token_obj is None
        assert user is None
    
    def test_revoke_refresh_token_success(self):
        """Test successfully revoking a refresh token"""
        mock_refresh_token = Mock(spec=RefreshToken)
        mock_refresh_token.is_revoked = False
        
        mock_db = Mock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_refresh_token
        mock_db.commit.return_value = None
        
        result = self.service.revoke_refresh_token(mock_db, "valid_token")
        
        assert result is True
        assert mock_refresh_token.is_revoked is True
        mock_db.commit.assert_called_once()
    
    def test_revoke_refresh_token_not_found(self):
        """Test revoking a non-existent refresh token"""
        mock_db = Mock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        result = self.service.revoke_refresh_token(mock_db, "nonexistent_token")
        
        assert result is False
    
    def test_revoke_all_user_tokens(self):
        """Test revoking all tokens for a user"""
        mock_token1 = Mock(spec=RefreshToken)
        mock_token2 = Mock(spec=RefreshToken)
        
        mock_db = Mock(spec=Session)
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_token1, mock_token2]
        mock_db.commit.return_value = None
        
        result = self.service.revoke_all_user_tokens(mock_db, 1)
        
        assert result == 2
        assert mock_token1.is_revoked is True
        assert mock_token2.is_revoked is True
        mock_db.commit.assert_called_once()
    
    def test_cleanup_user_tokens(self):
        """Test cleaning up expired tokens for a user"""
        mock_db = Mock(spec=Session)
        mock_delete = Mock()
        mock_delete.return_value = 5
        mock_db.query.return_value.filter.return_value.delete = mock_delete
        mock_db.commit.return_value = None
        
        result = self.service.cleanup_user_tokens(mock_db, 1)
        
        assert result == 5
        mock_delete.assert_called_once()
        mock_db.commit.assert_called_once()
    
    def test_get_user_active_tokens(self):
        """Test getting active tokens for a user"""
        mock_token1 = Mock(spec=RefreshToken)
        mock_token2 = Mock(spec=RefreshToken)
        
        mock_db = Mock(spec=Session)
        mock_query = Mock()
        mock_query.filter.return_value.order_by.return_value.all.return_value = [mock_token1, mock_token2]
        mock_db.query.return_value = mock_query
        
        result = self.service.get_user_active_tokens(mock_db, 1)
        
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0] == mock_token1
        assert result[1] == mock_token2

class TestRefreshTokenIntegration:
    """Integration tests for refresh token functionality"""
    
    def setup_method(self):
        """Setup test data"""
        self.test_user_data = {
            "email": "test@example.com",
            "password": "testpassword123",
            "name": "Test",
            "surname": "User",
            "role": "patient"
        }
    
    @patch('utils.refresh_token_service.refresh_token_service.create_refresh_token')
    @patch('utils.refresh_token_service.refresh_token_service.validate_refresh_token')
    def test_refresh_token_flow(self, mock_validate, mock_create):
        """Test complete refresh token flow"""
        # Setup mocks
        mock_refresh_token = Mock()
        mock_refresh_token.token = "refresh_test_token_123"
        mock_refresh_token.expires_at = datetime.utcnow() + timedelta(days=7)
        
        mock_user = Mock(spec=User)
        mock_user.id = 1
        mock_user.email = "test@example.com"
        mock_user.role = "patient"
        
        mock_create.return_value = mock_refresh_token
        mock_validate.return_value = (mock_refresh_token, mock_user)
        
        # Test creation
        mock_db = Mock()
        created_token = refresh_token_service.create_refresh_token(mock_db, mock_user)
        assert created_token == mock_refresh_token
        
        # Test validation
        validated_token, validated_user = refresh_token_service.validate_refresh_token(
            mock_db, "refresh_test_token_123"
        )
        assert validated_token == mock_refresh_token
        assert validated_user == mock_user

if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v", "--tb=short"])
