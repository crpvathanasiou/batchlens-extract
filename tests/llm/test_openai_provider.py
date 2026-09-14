"""Tests for OpenAI provider construction (no network calls)."""

from openai import AsyncOpenAI

from app.llm.openai_provider import create_async_openai_client


def test_create_async_openai_client_returns_async_openai_instance() -> None:
    client = create_async_openai_client(api_key="test-key-not-real", timeout_seconds=15.0)
    assert isinstance(client, AsyncOpenAI)
    assert client.max_retries == 0
