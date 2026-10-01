"""Unit tests for the async LLM wrapper using injected fake clients (no network)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from app.exceptions import (
    GuardrailBlockedError,
    ModelOutputParsingError,
    UpstreamServiceError,
)
from app.llm.guardrails import BaseGuardrail, GuardrailResult, MaxPromptLengthGuardrail
from app.llm.openai_wrapper import AsyncOpenAIWrapper, strict_json_schema_response_format
from app.page_classification.page_classification_schemas import MaterialEquipmentResponse


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
    def __init__(self, content: str, *, refusal: str | None = None) -> None:
        self.content = content
        self.refusal = refusal


class FakeTextChoice:
    def __init__(self, content: str, *, refusal: str | None = None) -> None:
        self.message = FakeTextMessage(content, refusal=refusal)


class FakeTextCompletion:
    def __init__(self, content: str, *, refusal: str | None = None) -> None:
        self.choices = [FakeTextChoice(content, refusal=refusal)]


class FakeChatCompletions:
    def __init__(
        self,
        text_response: str = "ok",
        *,
        structured_content: str | None = None,
        structured_refusal: str | None = None,
        raise_on_structured: Exception | None = None,
    ) -> None:
        self._text_response = text_response
        self._structured_content = structured_content
        self._structured_refusal = structured_refusal
        self._raise_on_structured = raise_on_structured
        self.create_calls = 0
        self.last_kwargs: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> FakeTextCompletion:
        self.create_calls += 1
        self.last_kwargs = dict(kwargs)
        if "response_format" in kwargs:
            if self._raise_on_structured is not None:
                raise self._raise_on_structured
            content = (
                self._text_response
                if self._structured_content is None
                else self._structured_content
            )
            return FakeTextCompletion(content, refusal=self._structured_refusal)
        return FakeTextCompletion(self._text_response)


class FakeChat:
    def __init__(
        self,
        text_response: str = "ok",
        *,
        structured_content: str | None = None,
        structured_refusal: str | None = None,
        raise_on_structured: Exception | None = None,
    ) -> None:
        self.completions = FakeChatCompletions(
            text_response=text_response,
            structured_content=structured_content,
            structured_refusal=structured_refusal,
            raise_on_structured=raise_on_structured,
        )


class FakeAsyncOpenAIClient:
    def __init__(
        self,
        *,
        text_response: str = "plain text response",
        structured_content: str = '{"decision":"allow","risk_level":"low"}',
        structured_refusal: str | None = None,
        raise_on_structured: Exception | None = None,
    ) -> None:
        self.chat = FakeChat(
            text_response=text_response,
            structured_content=structured_content,
            structured_refusal=structured_refusal,
            raise_on_structured=raise_on_structured,
        )


class FakeFailingTextChatCompletions:
    async def create(self, **kwargs: Any) -> FakeTextCompletion:
        raise RuntimeError("text call failed")


class FakeFailingChat:
    def __init__(self) -> None:
        self.completions = FakeFailingTextChatCompletions()


class FakeFailingAsyncOpenAIClient:
    def __init__(self) -> None:
        self.chat = FakeFailingChat()


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
    client = FakeAsyncOpenAIClient(
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
        system_prompt="Be precise.",
    )

    assert result.model_name == "gpt-test"
    assert result.parsed is not None
    assert isinstance(result.parsed, DummyStructuredResponse)
    assert result.parsed.decision == "allow"
    assert result.parsed.risk_level == "low"
    assert result.raw_text == '{"decision":"allow","risk_level":"low"}'
    assert result.attempts == 1
    assert client.chat.completions.last_kwargs is not None
    assert client.chat.completions.last_kwargs["messages"] == [
        {"role": "system", "content": "Be precise."},
        {"role": "user", "content": "Classify this message"},
    ]
    assert client.chat.completions.last_kwargs["temperature"] == 0.0
    assert client.chat.completions.last_kwargs["model"] == "gpt-test"
    response_format = client.chat.completions.last_kwargs["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "DummyStructuredResponse"
    assert response_format["json_schema"]["strict"] is True
    assert response_format["json_schema"]["schema"] == DummyStructuredResponse.model_json_schema(
        mode="validation"
    )
    assert response_format == strict_json_schema_response_format(DummyStructuredResponse)


def test_strict_json_schema_response_format_matches_pydantic_and_avoids_private_sdk() -> None:
    import app.llm.openai_wrapper as wrapper_module

    source = Path(wrapper_module.__file__).read_text(encoding="utf-8")
    assert "openai.lib._" not in source
    assert "type_to_response_format_param" not in source
    assert not hasattr(wrapper_module, "type_to_response_format_param")

    payload = strict_json_schema_response_format(MaterialEquipmentResponse)
    assert payload["type"] == "json_schema"
    assert payload["json_schema"]["name"] == "MaterialEquipmentResponse"
    assert payload["json_schema"]["strict"] is True
    assert payload["json_schema"]["schema"] == MaterialEquipmentResponse.model_json_schema(
        mode="validation"
    )
    asset = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "src"
            / "app"
            / "page_classification"
            / "json_schemas"
            / "01-materials-equipment.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert payload["json_schema"]["schema"] == asset


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
    client = FakeAsyncOpenAIClient()

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
async def test_generate_structured_raises_parsing_error_when_content_empty() -> None:
    client = FakeAsyncOpenAIClient(structured_content="")

    wrapper = AsyncOpenAIWrapper(
        client=client,
        default_model="gpt-test",
        default_temperature=0.0,
    )

    with pytest.raises(ModelOutputParsingError) as raised:
        await wrapper.generate_structured(
            prompt="Return structured output",
            response_schema=DummyStructuredResponse,
        )
    assert raised.value.raw_text == ""
    assert raised.value.structured_output_error is not None
    assert raised.value.structured_output_error["stage"] == "empty_content"


@pytest.mark.asyncio
async def test_generate_structured_preserves_raw_text_on_malformed_json() -> None:
    raw = "{not-json"
    client = FakeAsyncOpenAIClient(structured_content=raw)
    wrapper = AsyncOpenAIWrapper(
        client=client,
        default_model="gpt-test",
        default_temperature=0.0,
    )

    with pytest.raises(ModelOutputParsingError) as raised:
        await wrapper.generate_structured(
            prompt="Classify",
            response_schema=DummyStructuredResponse,
        )
    assert raised.value.raw_text == raw
    assert raised.value.model_name == "gpt-test"
    assert raised.value.attempts == 1
    assert raised.value.latency_ms is not None
    assert raised.value.structured_output_error is not None
    assert raised.value.structured_output_error["stage"] == "json_decode"
    assert raised.value.structured_output_error["error_type"] == "JSONDecodeError"
    assert raised.value.structured_output_error["validation_errors"] == []
    decode_error = raised.value.structured_output_error["decode_error"]
    assert decode_error["msg"]
    assert isinstance(decode_error["lineno"], int)
    assert isinstance(decode_error["colno"], int)
    assert isinstance(decode_error["pos"], int)
    assert raised.value.refusal_text is None


@pytest.mark.asyncio
async def test_generate_structured_preserves_raw_text_on_schema_validation() -> None:
    raw = json.dumps({"decision": "allow", "risk_level": 7})
    client = FakeAsyncOpenAIClient(structured_content=raw)
    wrapper = AsyncOpenAIWrapper(
        client=client,
        default_model="gpt-test",
        default_temperature=0.0,
    )

    with pytest.raises(ModelOutputParsingError) as raised:
        await wrapper.generate_structured(
            prompt="Classify",
            response_schema=DummyStructuredResponse,
        )
    assert raised.value.raw_text == raw
    assert raised.value.structured_output_error is not None
    assert raised.value.structured_output_error["stage"] == "schema_validation"
    assert raised.value.structured_output_error["error_type"] == "ValidationError"
    errors = raised.value.structured_output_error["validation_errors"]
    assert isinstance(errors, list) and errors
    assert "loc" in errors[0]
    assert "type" in errors[0]
    assert "msg" in errors[0]
    assert "input" not in errors[0]
    assert "risk_level" in errors[0]["loc"]
    assert raised.value.refusal_text is None


@pytest.mark.asyncio
async def test_generate_structured_preserves_exact_refusal_text() -> None:
    refusal = "I cannot classify this document because it requests prohibited content."
    client = FakeAsyncOpenAIClient(structured_content="", structured_refusal=refusal)
    wrapper = AsyncOpenAIWrapper(
        client=client,
        default_model="gpt-test",
        default_temperature=0.0,
    )

    with pytest.raises(ModelOutputParsingError) as raised:
        await wrapper.generate_structured(
            prompt="Classify",
            response_schema=DummyStructuredResponse,
        )
    assert raised.value.refusal_text == refusal
    assert raised.value.raw_text is None or raised.value.raw_text == ""
    assert raised.value.structured_output_error is not None
    assert raised.value.structured_output_error["stage"] == "refusal"


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

    with pytest.raises(ModelOutputParsingError) as raised:
        await wrapper.generate_structured(
            prompt="Classify",
            response_schema=DummyStructuredResponse,
        )
    assert raised.value.raw_text is None
    assert raised.value.refusal_text is None
    assert raised.value.structured_output_error is not None
    assert raised.value.structured_output_error["stage"] == "provider_response_unavailable"


@pytest.mark.asyncio
async def test_generate_structured_timeout_raises_upstream_without_raw_text() -> None:
    client = FakeAsyncOpenAIClient(raise_on_structured=TimeoutError("timed out"))
    wrapper = AsyncOpenAIWrapper(
        client=client,
        default_model="gpt-test",
        default_temperature=0.0,
        max_retries=0,
    )

    with pytest.raises(UpstreamServiceError):
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
