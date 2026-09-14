"""Async LLM wrapper for plain-text and structured OpenAI chat completions.

Ported from a working reference implementation. Orchestrates retries, timeouts,
guardrails, and typed results. Does not construct `AsyncOpenAI` or read API keys;
the async client is injected by the caller (tests use fakes; production uses
`create_async_openai_client`).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Generic, Protocol, TypeVar, cast

from openai import APIError, APITimeoutError
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from app.exceptions import (
    GuardrailBlockedError,
    ModelOutputParsingError,
    UpstreamServiceError,
)
from app.llm.guardrails import BaseGuardrail


def _empty_notes() -> list[dict[str, Any]]:
    return []


# -----------------------------------------------------------------------------
# Protocols
# -----------------------------------------------------------------------------
# Enable type-safe injection of either a real AsyncOpenAI client or test fakes.


class ChatCompletionsCreateProtocol(Protocol):
    async def create(self, **kwargs: Any) -> Any: ...


class ChatCompletionsParseProtocol(Protocol):
    async def parse(self, **kwargs: Any) -> Any: ...


class ChatCompletionsProtocol(Protocol):
    @property
    def completions(self) -> ChatCompletionsCreateProtocol: ...


class BetaChatCompletionsProtocol(Protocol):
    @property
    def completions(self) -> ChatCompletionsParseProtocol: ...


class BetaProtocol(Protocol):
    @property
    def chat(self) -> BetaChatCompletionsProtocol: ...


class AsyncOpenAIClientProtocol(Protocol):
    @property
    def chat(self) -> ChatCompletionsProtocol: ...

    @property
    def beta(self) -> BetaProtocol: ...


T = TypeVar("T", bound=BaseModel)


@dataclass
class LLMCallResult(Generic[T]):
    """Unified result for every LLM call."""

    model_name: str
    raw_text: str
    parsed: T | None = None
    guardrail_notes: list[dict[str, Any]] = field(default_factory=_empty_notes)
    raw_response: Any = None
    latency_ms: float = 0.0
    attempts: int = 1


class AsyncOpenAIWrapper:
    """Async orchestration wrapper around an injected OpenAI-compatible client."""

    def __init__(
        self,
        *,
        client: AsyncOpenAIClientProtocol,
        default_model: str,
        default_temperature: float = 0.0,
        timeout_seconds: float = 20.0,
        max_retries: int = 2,
    ) -> None:
        self.client = client
        self.default_model = default_model
        self.default_temperature = default_temperature
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    async def generate_text(
        self,
        *,
        prompt: str,
        model_name: str | None = None,
        temperature: float | None = None,
        enforced_guardrails: Sequence[BaseGuardrail] | None = None,
        system_prompt: str | None = None,
    ) -> LLMCallResult[BaseModel]:
        model = model_name or self.default_model
        temp = self.default_temperature if temperature is None else temperature
        guardrails = list(enforced_guardrails or [])

        guardrail_notes = self._run_input_guardrails(
            prompt=prompt,
            model_name=model,
            temperature=temp,
            guardrails=guardrails,
        )

        start = time.perf_counter()
        last_error: Exception | None = None
        messages = self._build_messages(
            system_prompt=system_prompt,
            user_prompt=prompt,
        )

        for attempt in range(1, self.max_retries + 2):
            try:
                response = await asyncio.wait_for(
                    self.client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=temp,
                    ),
                    timeout=self.timeout_seconds,
                )

                raw_text = self._extract_chat_text(response)

                guardrail_notes.extend(
                    self._run_output_guardrails(
                        prompt=prompt,
                        output_text=raw_text,
                        model_name=model,
                        temperature=temp,
                        guardrails=guardrails,
                    )
                )

                latency_ms = round((time.perf_counter() - start) * 1000, 2)

                return LLMCallResult(
                    model_name=model,
                    raw_text=raw_text,
                    parsed=None,
                    guardrail_notes=guardrail_notes,
                    raw_response=response,
                    latency_ms=latency_ms,
                    attempts=attempt,
                )

            except (TimeoutError, APITimeoutError, APIError) as exc:
                last_error = exc
                if attempt > self.max_retries:
                    raise UpstreamServiceError(
                        f"OpenAI text request failed after {attempt} attempt(s): {exc}"
                    ) from exc
                await asyncio.sleep(0.5 * attempt)

            except Exception as exc:
                if isinstance(exc, GuardrailBlockedError | UpstreamServiceError):
                    raise
                raise UpstreamServiceError(
                    f"OpenAI text request failed with unexpected upstream error: {exc}"
                ) from exc

        raise UpstreamServiceError(f"OpenAI text request failed: {last_error}")

    async def generate_structured(
        self,
        *,
        prompt: str,
        response_schema: type[T],
        model_name: str | None = None,
        temperature: float | None = None,
        enforced_guardrails: Sequence[BaseGuardrail] | None = None,
        system_prompt: str | None = None,
    ) -> LLMCallResult[T]:
        """Strict structured path using SDK-native structured parsing."""
        model = model_name or self.default_model
        temp = self.default_temperature if temperature is None else temperature
        guardrails = list(enforced_guardrails or [])

        logical_prompt = self._compose_logical_prompt(
            system_prompt=system_prompt,
            user_prompt=prompt,
        )

        guardrail_notes = self._run_input_guardrails(
            prompt=logical_prompt,
            model_name=model,
            temperature=temp,
            guardrails=guardrails,
        )

        start = time.perf_counter()
        last_error: Exception | None = None

        messages = self._build_messages(
            system_prompt=system_prompt,
            user_prompt=prompt,
        )

        for attempt in range(1, self.max_retries + 2):
            try:
                completion = await asyncio.wait_for(
                    self.client.beta.chat.completions.parse(
                        model=model,
                        messages=messages,
                        temperature=temp,
                        response_format=response_schema,
                    ),
                    timeout=self.timeout_seconds,
                )

                message = completion.choices[0].message
                parsed = message.parsed
                raw_text = message.content or ""

                if parsed is None:
                    raise ModelOutputParsingError(
                        f"Structured response parsing returned None for schema "
                        f"'{response_schema.__name__}'."
                    )

                guardrail_notes.extend(
                    self._run_output_guardrails(
                        prompt=logical_prompt,
                        output_text=raw_text,
                        model_name=model,
                        temperature=temp,
                        guardrails=guardrails,
                    )
                )

                latency_ms = round((time.perf_counter() - start) * 1000, 2)

                return LLMCallResult[T](
                    model_name=model,
                    raw_text=raw_text,
                    parsed=parsed,
                    guardrail_notes=guardrail_notes,
                    raw_response=completion,
                    latency_ms=latency_ms,
                    attempts=attempt,
                )

            except (TimeoutError, APITimeoutError, APIError) as exc:
                last_error = exc
                if attempt > self.max_retries:
                    raise UpstreamServiceError(
                        f"OpenAI structured request failed after {attempt} attempt(s): {exc}"
                    ) from exc
                await asyncio.sleep(0.5 * attempt)

            except Exception as exc:
                if isinstance(exc, GuardrailBlockedError | ModelOutputParsingError):
                    raise

                raise ModelOutputParsingError(
                    f"Structured parsing failed for schema '{response_schema.__name__}': {exc}"
                ) from exc

        raise UpstreamServiceError(f"OpenAI structured request failed: {last_error}")

    def _run_input_guardrails(
        self,
        *,
        prompt: str,
        model_name: str,
        temperature: float,
        guardrails: Sequence[BaseGuardrail],
    ) -> list[dict[str, Any]]:
        notes: list[dict[str, Any]] = []

        for guardrail in guardrails:
            result = guardrail.check_input(
                prompt=prompt,
                model_name=model_name,
                temperature=temperature,
            )
            notes.append(
                {
                    "guardrail": guardrail.name,
                    "stage": "input",
                    "passed": result.passed,
                    "reason": result.reason,
                    "metadata": result.metadata,
                }
            )
            if not result.passed:
                raise GuardrailBlockedError(
                    f"Input guardrail '{guardrail.name}' blocked the request: {result.reason}"
                )

        return notes

    def _run_output_guardrails(
        self,
        *,
        prompt: str,
        output_text: str,
        model_name: str,
        temperature: float,
        guardrails: Sequence[BaseGuardrail],
    ) -> list[dict[str, Any]]:
        notes: list[dict[str, Any]] = []

        for guardrail in guardrails:
            result = guardrail.check_output(
                prompt=prompt,
                output_text=output_text,
                model_name=model_name,
                temperature=temperature,
            )
            notes.append(
                {
                    "guardrail": guardrail.name,
                    "stage": "output",
                    "passed": result.passed,
                    "reason": result.reason,
                    "metadata": result.metadata,
                }
            )
            if not result.passed:
                raise GuardrailBlockedError(
                    f"Output guardrail '{guardrail.name}' blocked the response: {result.reason}"
                )

        return notes

    @staticmethod
    def _build_messages(
        *,
        system_prompt: str | None,
        user_prompt: str,
    ) -> list[ChatCompletionMessageParam]:
        messages: list[ChatCompletionMessageParam] = []

        if system_prompt and system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": user_prompt})
        return messages

    @staticmethod
    def _compose_logical_prompt(
        *,
        system_prompt: str | None,
        user_prompt: str,
    ) -> str:
        if system_prompt and system_prompt.strip():
            return f"[SYSTEM]\n{system_prompt}\n\n[USER]\n{user_prompt}"
        return user_prompt

    @staticmethod
    def _extract_chat_text(response: Any) -> str:
        try:
            message = response.choices[0].message
            content = getattr(message, "content", None)

            if isinstance(content, str) and content.strip():
                return content

            if isinstance(content, list):
                chunks: list[str] = []
                content_parts = cast(list[Any], content)
                for part in content_parts:
                    text = getattr(part, "text", None)
                    if isinstance(text, str):
                        chunks.append(text)
                joined = "\n".join(c for c in chunks if c).strip()
                if joined:
                    return joined
        except Exception:
            pass

        raise UpstreamServiceError("Could not extract text from chat completion response.")
