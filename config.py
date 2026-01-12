from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, SecretStr
from typing import Optional, Dict, Any

class Settings(BaseSettings):
    # Rate limiting settings
    RATE_LIMIT: int = Field(default=10, env="RATE_LIMIT")  # requests per minute
    RATE_LIMIT_WINDOW: int = Field(default=60, env="RATE_LIMIT_WINDOW")  # in seconds
    
    # Account lockout settings
    MAX_LOGIN_ATTEMPTS: int = Field(default=3, env="MAX_LOGIN_ATTEMPTS")
    LOCKOUT_TIME: int = Field(default=120, env="LOCKOUT_TIME")  # 2 minutes in seconds
    ENABLE_ACCOUNT_LOCKING: bool = Field(default=True, env="ENABLE_ACCOUNT_LOCKING")
    
    # Redis settings
    REDIS_URL: str = Field(default="redis://localhost:6379", env="REDIS_URL")
    REDIS_PASSWORD: Optional[str] = Field(default=None, env="REDIS_PASSWORD")
    
    # Render-specific Redis settings
    @property
    def REDIS_CONNECTION_STRING(self) -> str:
        """Get Redis connection string for deployment"""
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_URL.replace('redis://', '')}"
        return self.REDIS_URL
    
    # Database settings
    DATABASE_URL: str = Field(..., env="DATABASE_URL")
    
    # JWT settings
    SECRET_KEY: SecretStr = Field(..., env="SECRET_KEY")
    ALGORITHM: str = Field(default="HS256", env="ALGORITHM")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, env="ACCESS_TOKEN_EXPIRE_MINUTES")
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7, env="REFRESH_TOKEN_EXPIRE_DAYS")  # 7 days
    REFRESH_TOKEN_MAX_COUNT: int = Field(default=5, env="REFRESH_TOKEN_MAX_COUNT")  # Max active refresh tokens per user
    
    # OpenAI settings
    OPENAI_API_KEY: Optional[SecretStr] = Field(default=None, env="OPENAI_API_KEY")
    
    # Mailchimp email settings (optional for testing)
    MAILCHIMP_API_KEY: Optional[SecretStr] = Field(default=None, env="MAILCHIMP_API_KEY")
    MAILCHIMP_SERVER_PREFIX: Optional[str] = Field(default=None, env="MAILCHIMP_SERVER_PREFIX")
    FROM_EMAIL: Optional[str] = Field(default=None, env="FROM_EMAIL")
    FRONTEND_URL: str = Field(default="http://localhost:3000", env="FRONTEND_URL")
    
    # Email settings
    EMAIL_VERIFICATION_EXPIRE_HOURS: int = Field(default=24, env="EMAIL_VERIFICATION_EXPIRE_HOURS")
    PASSWORD_RESET_EXPIRE_HOURS: int = Field(default=2, env="PASSWORD_RESET_EXPIRE_HOURS")
    
    # Logging settings
    LOG_LEVEL: str = Field(default="INFO", env="LOG_LEVEL")
    
    # Cache settings
    CACHE_ENABLED: bool = Field(default=True, env="CACHE_ENABLED")
    CACHE_DEFAULT_TTL: int = Field(default=300, env="CACHE_DEFAULT_TTL")  # 5 minutes
    CACHE_MAX_MEMORY_MB: int = Field(default=256, env="CACHE_MAX_MEMORY_MB")  # Redis max memory
    
    # Pydantic v2 config
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding='utf-8',
        extra='ignore',  # Ignore extra env vars
        case_sensitive=True,
    )

# Initialize settings
settings = Settings()
