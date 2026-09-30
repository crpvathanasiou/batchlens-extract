"""Async three-call page classifier around the injected OpenAI wrapper."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Final

from app.exceptions import GuardrailBlockedError, ModelOutputParsingError, UpstreamServiceError
from app.llm import AsyncOpenAIWrapper, LLMCallResult
from app.page_classification.contracts import (
    CallOutcome,
    ClassifierCallId,
    CompletedPageClassificationResult,
    PreparedDocument,
    PreparedPageInput,
    completed_page_result_from_merge,
)
from app.page_classification.page_classification_schemas import (
    DocumentSupportingResponse,
    MaterialEquipmentResponse,
    ProcessOperationsResponse,
)
from app.page_classification.rules import (
    decide_extraction_eligibility,
    failed_call,
    merge_page_classification,
    validate_call_response,
)

_PROMPTS_DIR: Final = Path(__file__).resolve().parent / "prompts"
_MAX_SAFE_REASON: Final = 200

_CALL_SPECS: Final[
    tuple[
        tuple[
            ClassifierCallId,
            str,
            type[MaterialEquipmentResponse]
            | type[ProcessOperationsResponse]
            | type[DocumentSupportingResponse],
        ],
        ...,
    ]
] = (
    (1, "01-materials-equipment.txt", MaterialEquipmentResponse),
    (2, "02-process-operations-controls.txt", ProcessOperationsResponse),
    (3, "03-document-supporting-records.txt", DocumentSupportingResponse),
)

PageCompleteCallback = Callable[[CompletedPageClassificationResult], Awaitable[None] | None]


class PageClassificationRunner:
    """Classify prepared pages through the three locked structured calls."""

    def __init__(self, wrapper: AsyncOpenAIWrapper) -> None:
        self._wrapper = wrapper
        self._system_prompts: dict[ClassifierCallId, str] = {
            call_id: (_PROMPTS_DIR / filename).read_text(encoding="utf-8")
            for call_id, filename, _schema in _CALL_SPECS
        }

    @property
    def call_specs(
        self,
    ) -> Sequence[
        tuple[
            ClassifierCallId,
            str,
            type[MaterialEquipmentResponse]
            | type[ProcessOperationsResponse]
            | type[DocumentSupportingResponse],
        ]
    ]:
        return _CALL_SPECS

    async def classify_page(
        self,
        page: PreparedPageInput,
        *,
        on_complete: PageCompleteCallback | None = None,
    ) -> CompletedPageClassificationResult:
        """Run calls 1–3 serially, then apply S4.1 validate/merge/eligibility."""

        outcomes: list[CallOutcome] = []
        for call_id, _filename, schema in _CALL_SPECS:
            outcomes.append(await self._run_one_call(page, call_id=call_id, schema=schema))
        ordered = (outcomes[0], outcomes[1], outcomes[2])
        merged = merge_page_classification(page, ordered)
        eligibility = decide_extraction_eligibility(merged)
        result = completed_page_result_from_merge(merged, eligibility)
        if on_complete is not None:
            maybe_awaitable = on_complete(result)
            if maybe_awaitable is not None:
                await maybe_awaitable
        return result

    async def classify_document(
        self,
        document: PreparedDocument,
        *,
        on_page_complete: PageCompleteCallback | None = None,
    ) -> tuple[CompletedPageClassificationResult, ...]:
        """Classify every prepared page in document order."""

        results: list[CompletedPageClassificationResult] = []
        for page in document.pages:
            results.append(await self.classify_page(page, on_complete=on_page_complete))
        return tuple(results)

    async def _run_one_call(
        self,
        page: PreparedPageInput,
        *,
        call_id: ClassifierCallId,
        schema: type[MaterialEquipmentResponse]
        | type[ProcessOperationsResponse]
        | type[DocumentSupportingResponse],
    ) -> CallOutcome:
        system_prompt = self._system_prompts[call_id]
        try:
            result: LLMCallResult[
                MaterialEquipmentResponse | ProcessOperationsResponse | DocumentSupportingResponse
            ] = await self._wrapper.generate_structured(
                prompt=page.page_html_fragment,
                response_schema=schema,
                system_prompt=system_prompt,
            )
        except Exception as exc:  # noqa: BLE001 - map to truthful failed call
            return failed_call(
                page.binding,
                call_id,
                reason=_safe_call_failure_reason(exc),
            )

        if result.parsed is None:
            return failed_call(
                page.binding,
                call_id,
                reason="classifier call returned no structured response",
            )
        return validate_call_response(page.binding, call_id, result.parsed)


def _safe_call_failure_reason(exc: BaseException) -> str:
    """Return a concise persisted reason without provider/exception leakage."""

    if isinstance(exc, UpstreamServiceError):
        message = "classifier call failed: upstream service error"
    elif isinstance(exc, ModelOutputParsingError):
        message = "classifier call failed: structured output parsing error"
    elif isinstance(exc, GuardrailBlockedError):
        message = "classifier call failed: guardrail blocked"
    else:
        message = "classifier call failed"
    if len(message) <= _MAX_SAFE_REASON:
        return message
    return message[: _MAX_SAFE_REASON - 3] + "..."
