"""
Application configuration using Pydantic Settings.
Centralized configuration management for ForaGo Backend.
"""

from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator


class Settings(BaseSettings):
    """Application settings."""

    # Environment
    environment: str = Field(default="development", alias="ENVIRONMENT")
    data_source_mode: str = Field(default="mock", alias="DATA_SOURCE_MODE")

    # Database
    db_host: str = Field(default="localhost", alias="DB_HOST")
    db_port: int = Field(default=5432, alias="DB_PORT")
    db_name: str = Field(default="forago", alias="DB_NAME")
    db_user: str = Field(default="postgres", alias="DB_USER")
    db_password: str = Field(default="postgres", alias="DB_PASSWORD")
    db_ssl_mode: str = Field(default="", alias="DB_SSL_MODE")
    db_ssl: str = Field(default="", alias="DB_SSL")
    db_statement_cache_size: int = Field(default=0, alias="DB_STATEMENT_CACHE_SIZE")
    db_pool_min_size: int = Field(default=5)
    db_pool_max_size: int = Field(default=20)
    db_command_timeout: int = Field(default=60)

    # JWT / Auth
    jwt_secret_key: Optional[str] = Field(default=None, alias="JWT_SECRET_KEY")
    jwt_public_key: Optional[str] = Field(default=None, alias="JWT_PUBLIC_KEY")
    jwt_public_key_file: Optional[str] = Field(default=None, alias="JWT_PUBLIC_KEY_FILE")
    jwt_algorithms: str = Field(default="HS256", alias="JWT_ALGORITHMS")
    jwt_issuer: Optional[str] = Field(default=None, alias="JWT_ISSUER")
    jwt_audience: Optional[str] = Field(default=None, alias="JWT_AUDIENCE")
    jwt_jwks_url: Optional[str] = Field(default=None, alias="JWT_JWKS_URL")

    # Supabase
    supabase_url: Optional[str] = Field(default=None, alias="SUPABASE_URL")
    supabase_key: Optional[str] = Field(default=None, alias="SUPABASE_KEY")
    supabase_jwt_audience: str = Field(default="authenticated", alias="SUPABASE_JWT_AUDIENCE")

    # CORS
    cors_origins: str = Field(default="", alias="CORS_ORIGINS")

    # R2 / Storage
    r2_account_id: Optional[str] = Field(default=None, alias="R2_ACCOUNT_ID")
    r2_access_key_id: Optional[str] = Field(default=None, alias="R2_ACCESS_KEY_ID")
    r2_secret_access_key: Optional[str] = Field(default=None, alias="R2_SECRET_ACCESS_KEY")
    r2_bucket_name: Optional[str] = Field(default=None, alias="R2_BUCKET_NAME")

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="allow",
    )

    @field_validator("environment", mode="before")
    @classmethod
    def normalize_environment(cls, v: str) -> str:
        """Normalize environment name."""
        return v.lower() if v else "development"

    @field_validator("data_source_mode", mode="before")
    @classmethod
    def normalize_data_source_mode(cls, v: str) -> str:
        """Normalize data source mode."""
        return v.lower() if v else "mock"

    def get_parsed_jwt_algorithms(self) -> List[str]:
        """Parse JWT algorithms from config."""
        algorithms = [
            item.strip().upper()
            for item in self.jwt_algorithms.split(",")
            if item.strip()
        ]
        return algorithms or ["HS256"]

    def get_parsed_cors_origins(self) -> List[str]:
        """Parse CORS origins from config."""
        if not self.cors_origins.strip():
            return [
                "http://localhost",
                "http://127.0.0.1",
                "https://forago.app",
            ]

        origins = [
            item.strip()
            for item in self.cors_origins.split(",")
            if item.strip()
        ]
        return origins or [
            "http://localhost",
            "http://127.0.0.1",
            "https://forago.app",
        ]

    def is_production(self) -> bool:
        """Check if running in production."""
        return self.environment in {"production", "prod"}

    def validate_startup(self) -> None:
        """Validate configuration at startup."""
        if self.is_production() and self.data_source_mode != "db":
            raise RuntimeError(
                "Production requires DATA_SOURCE_MODE=db "
                f"(got {self.data_source_mode})"
            )


# Create global settings instance
settings = Settings()
