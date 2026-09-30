"""Async page-classification runner tests with an injected fake wrapper."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from app.exceptions import UpstreamServiceError
from app.llm.openai_wrapper import LLMCallResult
from app.page_classification.page_classification_schemas import (
    DocumentSupportingResponse,
    MaterialEquipmentResponse,
    ProcessOperationsResponse,
)
from app.page_classification.page_input import prepare_reviewed_document
from app.page_classification.runner import PageClassificationRunner

FIXTURE = Path(__file__).parent / "fixtures" / "reviewed_html_v1.html"
PROMPTS = Path(__file__).resolve().parents[2] / "src" / "app" / "page_classification" / "prompts"


class RecordingWrapper:
    def __init__(self, handlers: dict[type[Any], Any] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._handlers = handlers or {}

    async def generate_structured(self, **kwargs: Any) -> LLMCallResult[Any]:
        self.calls.append(dict(kwargs))
        schema = kwargs["response_schema"]
        handler = self._handlers.get(schema)
        if handler is None:
            parsed = schema.model_validate({"labels": [], "status": "empty", "evidence": []})
            return LLMCallResult(model_name="fake", raw_text="{}", parsed=parsed)
        if isinstance(handler, Exception):
            raise handler
        if callable(handler):
            value = handler(kwargs)
            if isinstance(value, Exception):
                raise value
            if isinstance(value, LLMCallResult):
                return cast(LLMCallResult[Any], value)
            return LLMCallResult(model_name="fake", raw_text="{}", parsed=value)
        return LLMCallResult(model_name="fake", raw_text="{}", parsed=handler)


@pytest.fixture
def document(tmp_path: Path) -> Any:
    path = tmp_path / "reviewed.html"
    path.write_bytes(FIXTURE.read_bytes())
    return prepare_reviewed_document(path)


@pytest.mark.asyncio
async def test_three_calls_in_order_with_locked_pairing(document: Any) -> None:
    wrapper = RecordingWrapper()
    runner = PageClassificationRunner(wrapper)  # type: ignore[arg-type]
    page = document.pages[1]
    await runner.classify_page(page)

    assert len(wrapper.calls) == 3
    expected = (
        (MaterialEquipmentResponse, "01-materials-equipment.txt"),
        (ProcessOperationsResponse, "02-process-operations-controls.txt"),
        (DocumentSupportingResponse, "03-document-supporting-records.txt"),
    )
    for call, (schema, prompt_name) in zip(wrapper.calls, expected, strict=True):
        assert call["response_schema"] is schema
        assert call["prompt"] == page.page_html_fragment
        assert call["system_prompt"] == (PROMPTS / prompt_name).read_text(encoding="utf-8")
        assert "model_name" not in call
        assert "temperature" not in call
        assert "timeout" not in call
        assert "max_retries" not in call
        assert "enforced_guardrails" not in call


@pytest.mark.asyncio
async def test_no_context_appended_to_page_html(document: Any) -> None:
    wrapper = RecordingWrapper()
    runner = PageClassificationRunner(wrapper)  # type: ignore[arg-type]
    page = document.pages[0]
    await runner.classify_page(page)
    for call in wrapper.calls:
        assert call["prompt"] == page.page_html_fragment
        assert "call" not in call["prompt"].lower() or "call" in page.page_html_fragment.lower()
        assert call["prompt"].count("<section") == page.page_html_fragment.count("<section")


@pytest.mark.asyncio
async def test_continues_after_call_failure_and_safe_reason(document: Any) -> None:
    secret = "sk-secret-SHOULD-NOT-LEAK"
    wrapper = RecordingWrapper(
        handlers={
            MaterialEquipmentResponse: UpstreamServiceError(
                f"OpenAI structured request failed: {secret}"
            ),
            ProcessOperationsResponse: ProcessOperationsResponse.model_validate(
                {"labels": [], "status": "ok", "evidence": []}
            ),
            DocumentSupportingResponse: DocumentSupportingResponse.model_validate(
                {"labels": [], "status": "ok", "evidence": []}
            ),
        }
    )
    runner = PageClassificationRunner(wrapper)  # type: ignore[arg-type]
    page = document.pages[1]
    result = await runner.classify_page(page)
    assert len(wrapper.calls) == 3
    assert result.call_outcomes[0].availability == "failed"
    assert result.call_outcomes[0].failure_reason is not None
    assert secret not in result.call_outcomes[0].failure_reason
    assert "upstream service error" in result.call_outcomes[0].failure_reason
    assert result.call_outcomes[1].availability == "valid"
    assert result.call_outcomes[2].availability == "valid"
    assert result.kind == "incomplete"
    assert result.eligibility.eligible_for_extraction is True


@pytest.mark.asyncio
async def test_document_order_callback_and_s41_behaviors(document: Any) -> None:
    completed_pages: list[int] = []

    def on_complete(result: Any) -> None:
        completed_pages.append(result.binding.page_number)

    # Page 1: application fallback OTHER_UNCLASSIFIED
    # Page 2: valid BOM merge
    # Page 3: needs_review + unverified evidence path via bad quote on call 3
    def make_handlers(page_number: int) -> dict[type[Any], Any]:
        if page_number == 1:
            empty_ok: dict[str, object] = {"labels": [], "status": "ok", "evidence": []}
            return {
                MaterialEquipmentResponse: MaterialEquipmentResponse.model_validate(empty_ok),
                ProcessOperationsResponse: ProcessOperationsResponse.model_validate(empty_ok),
                DocumentSupportingResponse: DocumentSupportingResponse.model_validate(empty_ok),
            }
        if page_number == 2:
            return {
                MaterialEquipmentResponse: MaterialEquipmentResponse.model_validate(
                    {
                        "labels": ["BILL_OF_MATERIALS"],
                        "status": "ok",
                        "evidence": [
                            {
                                "label": "BILL_OF_MATERIALS",
                                "quote": "Sodium Chloride",
                                "reason": "Materials table.",
                                "element_id": "materials-table",
                            }
                        ],
                    }
                ),
                ProcessOperationsResponse: ProcessOperationsResponse.model_validate(
                    {"labels": [], "status": "ok", "evidence": []}
                ),
                DocumentSupportingResponse: DocumentSupportingResponse.model_validate(
                    {"labels": [], "status": "ok", "evidence": []}
                ),
            }
        return {
            MaterialEquipmentResponse: MaterialEquipmentResponse.model_validate(
                {"labels": [], "status": "ok", "evidence": []}
            ),
            ProcessOperationsResponse: ProcessOperationsResponse.model_validate(
                {"labels": [], "status": "ok", "evidence": []}
            ),
            DocumentSupportingResponse: DocumentSupportingResponse.model_validate(
                {
                    "labels": ["SIGNATURE_APPROVAL"],
                    "status": "needs_review",
                    "evidence": [
                        {
                            "label": "SIGNATURE_APPROVAL",
                            "quote": "not present on this page at all",
                            "reason": "Looks like approval.",
                            "element_id": "approval-block",
                        }
                    ],
                }
            ),
        }

    class RoutingWrapper:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []
            self._page_index = 0
            self._call_in_page = 0

        async def generate_structured(self, **kwargs: Any) -> LLMCallResult[Any]:
            self.calls.append(dict(kwargs))
            page_number = document.pages[self._page_index].binding.page_number
            handlers = make_handlers(page_number)
            schema = kwargs["response_schema"]
            parsed = handlers[schema]
            self._call_in_page += 1
            if self._call_in_page == 3:
                self._call_in_page = 0
                self._page_index += 1
            return LLMCallResult(model_name="fake", raw_text="{}", parsed=parsed)

    wrapper = RoutingWrapper()
    runner = PageClassificationRunner(wrapper)  # type: ignore[arg-type]
    results = await runner.classify_document(document, on_page_complete=on_complete)

    assert completed_pages == [1, 2, 3]
    assert [item.binding.page_number for item in results] == [1, 2, 3]
    assert len(wrapper.calls) == 9

    fallback = results[0]
    assert fallback.applied_other_unclassified is True
    assert fallback.kind == "needs_review"
    assert fallback.labels[0].label == "OTHER_UNCLASSIFIED"
    assert fallback.eligibility.eligible_for_extraction is True

    merged = results[1]
    assert merged.kind == "completed"
    assert [item.label for item in merged.labels] == ["BILL_OF_MATERIALS"]
    assert merged.source_validation.has_unverified is False
    assert merged.eligibility.eligible_for_extraction is True

    review = results[2]
    assert review.kind == "needs_review"
    assert review.requires_review is True
    assert review.source_validation.has_unverified is True
    assert review.eligibility.eligible_for_extraction is True
    assert review.eligibility.excluded_by_policy is False


@pytest.mark.asyncio
async def test_second_page_continues_after_first_page_call_failure(document: Any) -> None:
    class FailFirstPageCallOne:
        def __init__(self) -> None:
            self.calls = 0

        async def generate_structured(self, **kwargs: Any) -> LLMCallResult[Any]:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("provider boom with key=sk-live")
            schema = kwargs["response_schema"]
            parsed = schema.model_validate({"labels": [], "status": "empty", "evidence": []})
            return LLMCallResult(model_name="fake", raw_text="{}", parsed=parsed)

    wrapper = FailFirstPageCallOne()
    runner = PageClassificationRunner(wrapper)  # type: ignore[arg-type]
    results = await runner.classify_document(document)
    assert len(results) == 3
    assert results[0].call_outcomes[0].availability == "failed"
    assert results[0].call_outcomes[0].failure_reason == "classifier call failed"
    assert "sk-live" not in (results[0].call_outcomes[0].failure_reason or "")
    assert results[0].call_outcomes[1].availability == "valid"
    assert results[1].kind == "empty"
    assert results[2].kind == "empty"
    assert wrapper.calls == 9
