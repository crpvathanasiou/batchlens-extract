"""Shared application errors for reusable starter capabilities."""


class AppError(Exception):
    """Base application error."""


class GuardrailBlockedError(AppError):
    """Raised when a guardrail blocks a request or response."""


class ModelOutputParsingError(AppError):
    """Raised when model output cannot be parsed into the expected schema."""


class UpstreamServiceError(AppError):
    """Raised for upstream provider failures."""
