"""OpenAI AsyncOpenAI client construction for the starter LLM capability.

Owns SDK construction and configuration sourced from application settings /
environment. The generic wrapper never constructs this client itself.
"""

from __future__ import annotations

from openai import AsyncOpenAI


def create_async_openai_client(
    *,
    api_key: str,
    timeout_seconds: float,
) -> AsyncOpenAI:
    """Build an `AsyncOpenAI` client for injection into the LLM wrapper.

    Retries are disabled at the SDK layer (`max_retries=0`) so the wrapper
    owns retry policy explicitly.
    """
    return AsyncOpenAI(
        api_key=api_key,
        timeout=timeout_seconds,
        max_retries=0,
    )
