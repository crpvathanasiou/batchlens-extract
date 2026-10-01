"""Shared application errors for reusable starter capabilities."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base application error."""


class GuardrailBlockedError(AppError):
    """Raised when a guardrail blocks a request or response."""


class ModelOutputParsingError(AppError):
    """Raised when model output cannot be parsed into the expected schema."""

    def __init__(
        self,
        message: str,
        *,
        raw_text: str | None = None,
        refusal_text: str | None = None,
        model_name: str | None = None,
        attempts: int | None = None,
        latency_ms: float | None = None,
        structured_output_error: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.raw_text = raw_text
        self.refusal_text = refusal_text
        self.model_name = model_name
        self.attempts = attempts
        self.latency_ms = latency_ms
        self.structured_output_error = structured_output_error


class UpstreamServiceError(AppError):
    """Raised for upstream provider failures."""
