"""Feature configuration, loaded only at an enabled composition boundary."""

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DocumentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCUMENT_", env_file=".env", extra="ignore")
    region: str = Field(min_length=1)
    bucket: str = Field(min_length=3)
    table: str = Field(min_length=1)
    queue_url: str = Field(min_length=1)
    dlq_url: str = Field(min_length=1)
    cognito_pool_id: str = Field(min_length=1)
    cognito_client_id: str = Field(min_length=1)
    origin: str = Field(pattern=r"^https://[^/]+$")
    prefix: str = "documents"
    max_pdf_mib: int = Field(default=25, ge=1, le=100)

    @property
    def max_pdf_bytes(self) -> int:
        return self.max_pdf_mib * 1024 * 1024

    max_blocks: int = Field(default=100_000, ge=1)
    max_json_bytes: int = Field(default=64 * 1024 * 1024, ge=1024)
    max_pages: int = Field(default=200, ge=1, le=200)
    job_workers: int = Field(default=2, ge=1, le=8)
    active_jobs: int = Field(default=2, ge=1, le=8)
    page_workers: int = Field(default=1, ge=1, le=4)
    sdk_io_concurrency: int = Field(default=4, ge=1, le=32)
    poll_seconds: int = Field(default=30, ge=10, le=300)
    lease_seconds: int = Field(default=180, ge=120, le=900)
    max_failures: int = Field(default=8, ge=1, le=20)
    max_job_seconds: int = Field(default=86400, ge=300, le=172800)
    retention_days: int = Field(default=30, ge=8, le=365)
    upload_seconds: int = Field(default=300, ge=60, le=900)

    @model_validator(mode="after")
    def check_prefix(self) -> "DocumentSettings":
        if not self.prefix.strip("/") or ".." in self.prefix.split("/"):
            raise ValueError("INVALID_DOCUMENT_PREFIX")
        return self


def load_document_settings() -> DocumentSettings:
    """Let BaseSettings resolve required values from environment; validate them normally."""
    return DocumentSettings.model_validate({})
