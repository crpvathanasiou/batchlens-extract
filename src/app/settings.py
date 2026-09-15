"""Validated application configuration for the FastAPI production starter foundation."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnvironment = Literal["local", "dev", "staging", "prod"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Application settings loaded from environment variables and an optional `.env` file.

    Invalid values raise `pydantic.ValidationError` at construction; there is no
    silent fallback.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    document_conversion_enabled: bool = False

    app_env: AppEnvironment = "local"
    app_version: str = Field(default="0.1.0", min_length=1)
    log_level: LogLevel = "INFO"

    # Optional LLM / OpenAI settings. Absent key keeps the app startable without OpenAI.
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_MODEL")
    openai_timeout_seconds: float = Field(default=20.0, alias="OPENAI_TIMEOUT_SECONDS", gt=0)
    openai_max_retries: int = Field(default=2, alias="OPENAI_MAX_RETRIES", ge=0)

    @field_validator("app_env", mode="before")
    @classmethod
    def _normalize_app_env(cls, value: object) -> object:
        if isinstance(value, str):
            return value.lower()
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        if isinstance(value, str):
            return value.upper()
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached default settings instance.

    Used only when `create_app()` receives no injected settings.
    """
    return Settings()
