"""Async LLM wrapper for plain-text and structured OpenAI chat completions.

Ported from a working reference implementation. Orchestrates retries, timeouts,
guardrails, and typed results. Does not construct `AsyncOpenAI` or read API keys;
the async client is injected by the caller (tests use fakes; production uses
`create_async_openai_client`).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Generic, Protocol, TypeVar, cast

from openai import APIError, APITimeoutError
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, ValidationError

from app.exceptions import (
    GuardrailBlockedError,
    ModelOutputParsingError,
    UpstreamServiceError,
)
from app.llm.guardrails import BaseGuardrail


def _empty_notes() -> list[dict[str, Any]]:
    return []


def strict_json_schema_response_format(response_schema: type[BaseModel]) -> dict[str, Any]:
    """Build a public strict JSON Schema response_format from a Pydantic v2 model."""

    return {
        "type": "json_schema",
        "json_schema": {
            "name": response_schema.__name__,
            "strict": True,
            "schema": response_schema.model_json_schema(mode="validation"),
        },
    }


# -----------------------------------------------------------------------------
# Protocols
# -----------------------------------------------------------------------------
# Enable type-safe injection of either a real AsyncOpenAI client or test fakes.


class ChatCompletionsCreateProtocol(Protocol):
    async def create(self, **kwargs: Any) -> Any: ...


class ChatCompletionsProtocol(Protocol):
    @property
    def completions(self) -> ChatCompletionsCreateProtocol: ...


class AsyncOpenAIClientProtocol(Protocol):
    @property
    def chat(self) -> ChatCompletionsProtocol: ...


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
        """Strict structured path: schema-enforced create, then local Pydantic validation."""
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
        response_format = strict_json_schema_response_format(response_schema)

        for attempt in range(1, self.max_retries + 2):
            try:
                completion = await asyncio.wait_for(
                    self.client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=temp,
                        response_format=response_format,
                    ),
                    timeout=self.timeout_seconds,
                )

                latency_ms = round((time.perf_counter() - start) * 1000, 2)
                try:
                    raw_text, refusal = self._extract_structured_message_content(completion)
                except ModelOutputParsingError as exc:
                    raise ModelOutputParsingError(
                        str(exc),
                        raw_text=exc.raw_text,
                        refusal_text=exc.refusal_text,
                        model_name=model,
                        attempts=attempt,
                        latency_ms=latency_ms,
                        structured_output_error=exc.structured_output_error,
                    ) from None
                parsed = self._parse_structured_content(
                    raw_text=raw_text,
                    refusal=refusal,
                    response_schema=response_schema,
                    model_name=model,
                    attempts=attempt,
                    latency_ms=latency_ms,
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
                if isinstance(
                    exc,
                    GuardrailBlockedError | ModelOutputParsingError | UpstreamServiceError,
                ):
                    raise

                raise ModelOutputParsingError(
                    f"Structured parsing failed for schema '{response_schema.__name__}': {exc}",
                    raw_text=None,
                    refusal_text=None,
                    model_name=model,
                    attempts=attempt,
                    latency_ms=round((time.perf_counter() - start) * 1000, 2),
                    structured_output_error={
                        "stage": "provider_response_unavailable",
                        "error_type": "ProviderResponseUnavailable",
                        "message": "provider did not return a usable completion",
                        "validation_errors": [],
                    },
                ) from exc

        raise UpstreamServiceError(f"OpenAI structured request failed: {last_error}")

    def _parse_structured_content(
        self,
        *,
        raw_text: str,
        refusal: str | None,
        response_schema: type[T],
        model_name: str,
        attempts: int,
        latency_ms: float,
    ) -> T:
        """Validate returned model text locally so diagnostics can keep the exact content."""

        if refusal is not None and str(refusal).strip():
            raise ModelOutputParsingError(
                f"Structured response refused for schema '{response_schema.__name__}'.",
                raw_text=raw_text if raw_text else None,
                refusal_text=refusal,
                model_name=model_name,
                attempts=attempts,
                latency_ms=latency_ms,
                structured_output_error={
                    "stage": "refusal",
                    "error_type": "Refusal",
                    "message": "model refused structured response",
                    "validation_errors": [],
                },
            )
        if not raw_text.strip():
            raise ModelOutputParsingError(
                f"Structured response content was empty for schema "
                f"'{response_schema.__name__}'.",
                raw_text=raw_text,
                refusal_text=None,
                model_name=model_name,
                attempts=attempts,
                latency_ms=latency_ms,
                structured_output_error={
                    "stage": "empty_content",
                    "error_type": "EmptyContent",
                    "message": "structured response content was empty",
                    "validation_errors": [],
                },
            )
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as decode_exc:
            raise ModelOutputParsingError(
                f"Structured response was not valid JSON for schema "
                f"'{response_schema.__name__}'.",
                raw_text=raw_text,
                refusal_text=None,
                model_name=model_name,
                attempts=attempts,
                latency_ms=latency_ms,
                structured_output_error={
                    "stage": "json_decode",
                    "error_type": "JSONDecodeError",
                    "message": "structured response is not valid JSON",
                    "validation_errors": [],
                    "decode_error": {
                        "msg": decode_exc.msg,
                        "lineno": decode_exc.lineno,
                        "colno": decode_exc.colno,
                        "pos": decode_exc.pos,
                    },
                },
            ) from None
        try:
            return response_schema.model_validate(payload)
        except ValidationError as exc:
            raise ModelOutputParsingError(
                f"Structured response failed validation for schema "
                f"'{response_schema.__name__}'.",
                raw_text=raw_text,
                refusal_text=None,
                model_name=model_name,
                attempts=attempts,
                latency_ms=latency_ms,
                structured_output_error={
                    "stage": "schema_validation",
                    "error_type": "ValidationError",
                    "message": "structured response failed validation",
                    "validation_errors": _safe_validation_errors(exc),
                },
            ) from None

    @staticmethod
    def _extract_structured_message_content(response: Any) -> tuple[str, str | None]:
        try:
            message = response.choices[0].message
        except Exception as exc:  # noqa: BLE001 - map to unavailable completion
            raise ModelOutputParsingError(
                "Structured response did not include a completion message.",
                raw_text=None,
                refusal_text=None,
                structured_output_error={
                    "stage": "provider_response_unavailable",
                    "error_type": "ProviderResponseUnavailable",
                    "message": "provider did not return a usable completion",
                    "validation_errors": [],
                },
            ) from exc

        refusal_value = getattr(message, "refusal", None)
        refusal = refusal_value if isinstance(refusal_value, str) else None
        content = getattr(message, "content", None)
        if isinstance(content, str):
            return content, refusal
        if isinstance(content, list):
            chunks: list[str] = []
            content_parts = cast(list[Any], content)
            for part in content_parts:
                text = getattr(part, "text", None)
                if isinstance(text, str):
                    chunks.append(text)
            return "\n".join(c for c in chunks if c), refusal
        return "", refusal

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


def _safe_validation_errors(exc: ValidationError) -> list[dict[str, Any]]:
    """Extract loc/type/msg only; never persist Pydantic input values."""

    safe: list[dict[str, Any]] = []
    for item in exc.errors(include_url=False):
        loc = item.get("loc", ())
        safe.append(
            {
                "loc": [str(part) for part in loc],
                "type": str(item.get("type", "")),
                "msg": str(item.get("msg", "")),
            }
        )
    return safe
