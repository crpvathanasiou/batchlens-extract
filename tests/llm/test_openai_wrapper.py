"""Unit tests for the async LLM wrapper using injected fake clients (no network)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from app.exceptions import (
    GuardrailBlockedError,
    ModelOutputParsingError,
    UpstreamServiceError,
)
from app.llm.guardrails import BaseGuardrail, GuardrailResult, MaxPromptLengthGuardrail
from app.llm.openai_wrapper import AsyncOpenAIWrapper


class DummyStructuredResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str
    risk_level: str


class RejectAllGuardrail(BaseGuardrail):
    name = "reject_all"

    def check_input(self, *, prompt: str, model_name: str, temperature: float) -> GuardrailResult:
        return GuardrailResult(
            passed=False,
            reason="Rejected by test guardrail.",
        )


class RejectOutputGuardrail(BaseGuardrail):
    name = "reject_output"

    def check_output(
        self,
        *,
        prompt: str,
        output_text: str,
        model_name: str,
        temperature: float,
    ) -> GuardrailResult:
        return GuardrailResult(
            passed=False,
            reason="Rejected by output test guardrail.",
        )


class FakeTextMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeTextChoice:
    def __init__(self, content: str) -> None:
        self.message = FakeTextMessage(content)


class FakeTextCompletion:
    def __init__(self, content: str) -> None:
        self.choices = [FakeTextChoice(content)]


class FakeStructuredMessage:
    def __init__(self, parsed: Any = None, content: str = "") -> None:
        self.parsed = parsed
        self.content = content


class FakeStructuredChoice:
    def __init__(self, parsed: Any = None, content: str = "") -> None:
        self.message = FakeStructuredMessage(parsed=parsed, content=content)


class FakeStructuredCompletion:
    def __init__(self, parsed: Any = None, content: str = "") -> None:
        self.choices = [FakeStructuredChoice(parsed=parsed, content=content)]


class FakeChatCompletions:
    def __init__(self, text_response: str = "ok") -> None:
        self._text_response = text_response
        self.create_calls = 0

    async def create(self, **kwargs: Any) -> FakeTextCompletion:
        self.create_calls += 1
        return FakeTextCompletion(self._text_response)


class FakeBetaChatCompletions:
    def __init__(self, parsed_response: Any = None, content: str = "") -> None:
        self._parsed_response = parsed_response
        self._content = content

    async def parse(self, **kwargs: Any) -> FakeStructuredCompletion:
        return FakeStructuredCompletion(
            parsed=self._parsed_response,
            content=self._content,
        )


class FakeChat:
    def __init__(self, text_response: str = "ok") -> None:
        self.completions = FakeChatCompletions(text_response=text_response)


class FakeBetaChat:
    def __init__(self, parsed_response: Any = None, content: str = "") -> None:
        self.completions = FakeBetaChatCompletions(
            parsed_response=parsed_response,
            content=content,
        )


class FakeBeta:
    def __init__(self, parsed_response: Any = None, content: str = "") -> None:
        self.chat = FakeBetaChat(
            parsed_response=parsed_response,
            content=content,
        )


class FakeAsyncOpenAIClient:
    def __init__(
        self,
        *,
        text_response: str = "plain text response",
        parsed_response: Any = None,
        structured_content: str = '{"decision":"allow","risk_level":"low"}',
    ) -> None:
        self.chat = FakeChat(text_response=text_response)
        self.beta = FakeBeta(
            parsed_response=parsed_response,
            content=structured_content,
        )


class FakeFailingTextChatCompletions:
    async def create(self, **kwargs: Any) -> FakeTextCompletion:
        raise RuntimeError("text call failed")


class FakeFailingStructuredChatCompletions:
    async def parse(self, **kwargs: Any) -> FakeStructuredCompletion:
        raise RuntimeError("structured parse failed")


class FakeFailingChat:
    def __init__(self) -> None:
        self.completions = FakeFailingTextChatCompletions()


class FakeFailingBetaChat:
    def __init__(self) -> None:
        self.completions = FakeFailingStructuredChatCompletions()


class FakeFailingBeta:
    def __init__(self) -> None:
        self.chat = FakeFailingBetaChat()


class FakeFailingAsyncOpenAIClient:
    def __init__(self) -> None:
        self.chat = FakeFailingChat()
        self.beta = FakeFailingBeta()


class FakeTimeoutThenSucceedChatCompletions:
    def __init__(self, text_response: str = "recovered") -> None:
        self._text_response = text_response
        self.create_calls = 0

    async def create(self, **kwargs: Any) -> FakeTextCompletion:
        self.create_calls += 1
        if self.create_calls == 1:
            raise TimeoutError("simulated timeout")
        return FakeTextCompletion(self._text_response)


class FakeTimeoutThenSucceedChat:
    def __init__(self, text_response: str = "recovered") -> None:
        self.completions = FakeTimeoutThenSucceedChatCompletions(text_response)


class FakeRetryableAsyncOpenAIClient:
    def __init__(self, *, text_response: str = "recovered") -> None:
        self.chat = FakeTimeoutThenSucceedChat(text_response=text_response)
        self.beta = FakeBeta()


@pytest.mark.asyncio
async def test_generate_text_returns_plain_text_result() -> None:
    client = FakeAsyncOpenAIClient(text_response="hello from model")

    wrapper = AsyncOpenAIWrapper(
        client=client,
        default_model="gpt-test",
        default_temperature=0.0,
    )

    result = await wrapper.generate_text(
        prompt="Say hello",
    )

    assert result.model_name == "gpt-test"
    assert result.raw_text == "hello from model"
    assert result.parsed is None
    assert result.attempts == 1


@pytest.mark.asyncio
async def test_generate_structured_returns_parsed_pydantic_object() -> None:
    parsed = DummyStructuredResponse(
        decision="allow",
        risk_level="low",
    )
    client = FakeAsyncOpenAIClient(
        parsed_response=parsed,
        structured_content='{"decision":"allow","risk_level":"low"}',
    )

    wrapper = AsyncOpenAIWrapper(
        client=client,
        default_model="gpt-test",
        default_temperature=0.0,
    )

    result = await wrapper.generate_structured(
        prompt="Classify this message",
        response_schema=DummyStructuredResponse,
    )

    assert result.model_name == "gpt-test"
    assert result.parsed is not None
    assert isinstance(result.parsed, DummyStructuredResponse)
    assert result.parsed.decision == "allow"
    assert result.parsed.risk_level == "low"
    assert result.attempts == 1


@pytest.mark.asyncio
async def test_generate_text_blocks_when_input_guardrail_fails() -> None:
    client = FakeAsyncOpenAIClient()

    wrapper = AsyncOpenAIWrapper(
        client=client,
        default_model="gpt-test",
        default_temperature=0.0,
    )

    with pytest.raises(GuardrailBlockedError):
        await wrapper.generate_text(
            prompt="This should be blocked",
            enforced_guardrails=[RejectAllGuardrail()],
        )


@pytest.mark.asyncio
async def test_generate_text_blocks_when_output_guardrail_fails() -> None:
    client = FakeAsyncOpenAIClient(text_response="model output")

    wrapper = AsyncOpenAIWrapper(
        client=client,
        default_model="gpt-test",
        default_temperature=0.0,
    )

    with pytest.raises(GuardrailBlockedError):
        await wrapper.generate_text(
            prompt="Say hello",
            enforced_guardrails=[RejectOutputGuardrail()],
        )


@pytest.mark.asyncio
async def test_generate_structured_blocks_when_prompt_too_long() -> None:
    client = FakeAsyncOpenAIClient(
        parsed_response=DummyStructuredResponse(decision="allow", risk_level="low")
    )

    wrapper = AsyncOpenAIWrapper(
        client=client,
        default_model="gpt-test",
        default_temperature=0.0,
    )

    with pytest.raises(GuardrailBlockedError):
        await wrapper.generate_structured(
            prompt="x" * 100,
            response_schema=DummyStructuredResponse,
            enforced_guardrails=[MaxPromptLengthGuardrail(max_chars=10)],
        )


@pytest.mark.asyncio
async def test_generate_structured_raises_parsing_error_when_parsed_is_none() -> None:
    client = FakeAsyncOpenAIClient(
        parsed_response=None,
        structured_content="",
    )

    wrapper = AsyncOpenAIWrapper(
        client=client,
        default_model="gpt-test",
        default_temperature=0.0,
    )

    with pytest.raises(ModelOutputParsingError):
        await wrapper.generate_structured(
            prompt="Return structured output",
            response_schema=DummyStructuredResponse,
        )


@pytest.mark.asyncio
async def test_generate_text_raises_upstream_error_on_transport_failure() -> None:
    client = FakeFailingAsyncOpenAIClient()

    wrapper = AsyncOpenAIWrapper(
        client=client,
        default_model="gpt-test",
        default_temperature=0.0,
        max_retries=0,
    )

    with pytest.raises(UpstreamServiceError):
        await wrapper.generate_text(
            prompt="Hello",
        )


@pytest.mark.asyncio
async def test_generate_structured_raises_parsing_error_on_unexpected_failure() -> None:
    client = FakeFailingAsyncOpenAIClient()

    wrapper = AsyncOpenAIWrapper(
        client=client,
        default_model="gpt-test",
        default_temperature=0.0,
        max_retries=0,
    )

    with pytest.raises(ModelOutputParsingError):
        await wrapper.generate_structured(
            prompt="Classify",
            response_schema=DummyStructuredResponse,
        )


@pytest.mark.asyncio
async def test_generate_text_retries_after_timeout_then_succeeds() -> None:
    client = FakeRetryableAsyncOpenAIClient(text_response="recovered")

    wrapper = AsyncOpenAIWrapper(
        client=client,
        default_model="gpt-test",
        default_temperature=0.0,
        max_retries=1,
    )

    result = await wrapper.generate_text(prompt="Retry me")

    assert result.raw_text == "recovered"
    assert result.attempts == 2
    assert client.chat.completions.create_calls == 2
