# Test Configuration for pytest
import pytest
import sys
import os
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

# Add the parent directory to the path so we can import our modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

@pytest.fixture(scope="session")
def test_settings():
    """Test configuration settings"""
    return {
        "SECRET_KEY": "test_secret_key_for_testing_only",
        "ALGORITHM": "HS256", 
        "ACCESS_TOKEN_EXPIRE_MINUTES": 30,
        "RATE_LIMIT": 10,
        "REDIS_CONNECTION_STRING": "redis://localhost:6379/1",  # Test DB
        "ENABLE_ACCOUNT_LOCKING": True,
        "MAX_LOGIN_ATTEMPTS": 3,
        "LOCKOUT_TIME": 120
    }

@pytest.fixture
def mock_redis():
    """Mock Redis client for testing"""
    mock_client = Mock()
    mock_client.ping.return_value = True
    mock_client.get.return_value = None
    mock_client.setex.return_value = True
    mock_client.delete.return_value = True
    return mock_client

@pytest.fixture
def mock_db_session():
    """Mock database session"""
    session = Mock()
    session.query.return_value.filter.return_value.first.return_value = None
    session.query.return_value.filter.return_value.count.return_value = 0
    session.query.return_value.filter.return_value.all.return_value = []
    session.add.return_value = None
    session.commit.return_value = None
    session.rollback.return_value = None
    session.close.return_value = None
    return session

@pytest.fixture
def test_user():
    """Test user object"""
    user = Mock()
    user.id = 1
    user.email = "test@example.com"
    user.name = "Test"
    user.surname = "User"
    user.role = "patient"
    user.hashed_password = "$2b$12$test_hash"
    return user

@pytest.fixture
def valid_jwt_token():
    """Generate a valid JWT token for testing"""
    from jose import jwt
    
    payload = {
        "sub": "test@example.com",
        "role": "patient",
        "exp": int((datetime.utcnow() + timedelta(hours=1)).timestamp())
    }
    
    return jwt.encode(payload, "test_secret_key_for_testing_only", "HS256")

@pytest.fixture
def expired_jwt_token():
    """Generate an expired JWT token for testing"""
    from jose import jwt
    
    payload = {
        "sub": "test@example.com", 
        "role": "patient",
        "exp": int((datetime.utcnow() - timedelta(hours=1)).timestamp())
    }
    
    return jwt.encode(payload, "test_secret_key_for_testing_only", "HS256")

@pytest.fixture(autouse=True)
def mock_settings(test_settings):
    """Automatically mock settings for all tests"""
    with patch('config.settings', **test_settings):
        with patch('config.settings.SECRET_KEY', test_settings["SECRET_KEY"]):
            with patch('config.settings.ALGORITHM', test_settings["ALGORITHM"]):
                with patch('config.settings.ACCESS_TOKEN_EXPIRE_MINUTES', test_settings["ACCESS_TOKEN_EXPIRE_MINUTES"]):
                    yield

# Test markers
pytest_plugins = []

def pytest_configure(config):
    """Configure pytest markers"""
    config.addinivalue_line(
        "markers", "unit: mark test as a unit test"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as an integration test"
    )
    config.addinivalue_line(
        "markers", "auth: mark test as authentication related"
    )
    config.addinivalue_line(
        "markers", "token: mark test as token validation related"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
