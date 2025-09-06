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
    
    # Database settings
    DATABASE_URL: str = Field(..., env="DATABASE_URL")
    
    # JWT settings
    SECRET_KEY: SecretStr = Field(..., env="SECRET_KEY")
    ALGORITHM: str = Field(default="HS256", env="ALGORITHM")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, env="ACCESS_TOKEN_EXPIRE_MINUTES")
    
    # OpenAI settings
    OPENAI_API_KEY: Optional[SecretStr] = Field(default=None, env="OPENAI_API_KEY")
    
    # Logging settings
    LOG_LEVEL: str = Field(default="INFO", env="LOG_LEVEL")
    
    # Pydantic v2 config
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding='utf-8',
        extra='ignore',  # Ignore extra env vars
        case_sensitive=True,
    )

# Initialize settings
settings = Settings()
