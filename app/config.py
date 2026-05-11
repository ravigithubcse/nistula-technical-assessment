"""
Application Configuration Module
Author: Ravikumar

Centralizes all application settings using Pydantic Settings.
Loads configuration from environment variables with sensible defaults.
Never hardcode secrets - always use environment variables.
"""

import os
from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    
    Design Decision (Ravikumar):
    - Using Pydantic Settings for automatic type validation and .env file loading
    - All sensitive values (API keys) are loaded from env, never hardcoded
    - Using Field() with descriptions for better documentation and validation
    """
    
    # =============================================================================
    # CLAUDE API CONFIGURATION
    # =============================================================================
    claude_api_key: str = Field(
        ...,  # Required field - will raise error if not provided
        description="Anthropic Claude API key for AI-generated replies",
        alias="CLAUDE_API_KEY"
    )
    claude_model: str = Field(
        default="claude-sonnet-4-20250514",
        description="Claude model identifier for generating responses",
        alias="CLAUDE_MODEL"
    )
    
    # =============================================================================
    # APPLICATION CONFIGURATION
    # =============================================================================
    environment: str = Field(
        default="development",
        description="Application environment: development, staging, or production",
        alias="ENVIRONMENT"
    )
    host: str = Field(
        default="0.0.0.0",
        description="Host to bind the FastAPI server",
        alias="HOST"
    )
    port: int = Field(
        default=8000,
        description="Port to run the FastAPI server",
        alias="PORT"
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL",
        alias="LOG_LEVEL"
    )
    
    # =============================================================================
    # DATABASE CONFIGURATION (PostgreSQL)
    # =============================================================================
    database_url: Optional[str] = Field(
        default=None,
        description="Full PostgreSQL connection URL (overrides individual params if set)",
        alias="DATABASE_URL"
    )
    db_host: str = Field(
        default="localhost",
        description="PostgreSQL host",
        alias="DB_HOST"
    )
    db_port: int = Field(
        default=5432,
        description="PostgreSQL port",
        alias="DB_PORT"
    )
    db_name: str = Field(
        default="nistula_db",
        description="PostgreSQL database name",
        alias="DB_NAME"
    )
    db_user: str = Field(
        default="nistula_user",
        description="PostgreSQL username",
        alias="DB_USER"
    )
    db_password: str = Field(
        default="nistula_password",
        description="PostgreSQL password",
        alias="DB_PASSWORD"
    )
    
    class Config:
        """Pydantic configuration for loading .env file."""
        env_file = ".env"
        env_file_encoding = "utf-8"
        # Allow both upper and lower case env var names
        case_sensitive = False
    
    def get_database_url(self) -> str:
        """
        Returns the PostgreSQL connection URL.
        
        Priority: DATABASE_URL env var > constructed from individual params
        This allows flexibility - users can provide a full URL or individual parts.
        """
        if self.database_url:
            return self.database_url
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache()
def get_settings() -> Settings:
    """
    Returns cached Settings instance.
    
    Design Decision (Ravikumar):
    - Using @lru_cache to avoid reloading .env file on every request
    - Settings are loaded once at startup and reused throughout the application lifecycle
    - This improves performance in high-throughput scenarios
    """
    return Settings()
