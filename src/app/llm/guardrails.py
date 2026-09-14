"""Deterministic LLM input/output guardrails used by the async wrapper."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _empty_metadata() -> dict[str, Any]:
    return {}


@dataclass
class GuardrailResult:
    """Outcome of a single guardrail check."""

    passed: bool
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=_empty_metadata)


class BaseGuardrail:
    """Base class for prompt/output guardrails.

    Default behaviour allows all traffic. Concrete guardrails override
    `check_input` and/or `check_output`.
    """

    name: str = "base_guardrail"

    def check_input(
        self,
        *,
        prompt: str,
        model_name: str,
        temperature: float,
    ) -> GuardrailResult:
        return GuardrailResult(passed=True)

    def check_output(
        self,
        *,
        prompt: str,
        output_text: str,
        model_name: str,
        temperature: float,
    ) -> GuardrailResult:
        return GuardrailResult(passed=True)


class MaxPromptLengthGuardrail(BaseGuardrail):
    """Rejects prompts that exceed a configured character limit."""

    name = "max_prompt_length"

    def __init__(self, max_chars: int) -> None:
        self.max_chars = max_chars

    def check_input(
        self,
        *,
        prompt: str,
        model_name: str,
        temperature: float,
    ) -> GuardrailResult:
        if len(prompt) > self.max_chars:
            return GuardrailResult(
                passed=False,
                reason=f"Prompt exceeds max allowed length ({self.max_chars} chars).",
                metadata={"actual_length": len(prompt)},
            )
        return GuardrailResult(passed=True)
