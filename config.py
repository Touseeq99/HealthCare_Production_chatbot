from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, SecretStr
from typing import Optional, Dict, Any

class Settings(BaseSettings):
    # Rate limiting settings
    RATE_LIMIT: int = Field(default=10, env="RATE_LIMIT")
    RATE_LIMIT_WINDOW: int = Field(default=60, env="RATE_LIMIT_WINDOW")
    
    # Database settings
    DATABASE_URL: str = Field(..., env="DATABASE_URL")
    
    # OpenAI settings
    OPENAI_API_KEY: Optional[SecretStr] = Field(default=None, env="OPENAI_API_KEY")
    
    # Logging settings
    LOG_LEVEL: str = Field(default="INFO", env="LOG_LEVEL")
    
    # Supabase settings
    SUPABASE_URL: str = Field(default="", env="SUPABASE_URL")
    SUPABASE_SERVICE_KEY: str = Field(default="", env="SUPABASE_SERVICE_KEY")
    
    # Pydantic v2 config
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding='utf-8',
        extra='ignore',
        case_sensitive=True,
    )

# Initialize settings
settings = Settings()
