"""S4.7 local page-classification diagnostic bundle tests."""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from app.exceptions import ModelOutputParsingError, UpstreamServiceError
from app.llm.openai_wrapper import LLMCallResult
from app.page_classification.contracts import (
    ClassificationProgress,
    CurrentClassificationState,
)
from app.page_classification.diagnostics import (
    MANIFEST_FILENAME,
    ClassificationDiagnosticSession,
    DiagnosticPersistenceError,
    begin_classification_diagnostics,
    diagnostics_root,
)
from app.page_classification.page_classification_schemas import (
    DocumentSupportingResponse,
    MaterialEquipmentResponse,
    ProcessOperationsResponse,
)
from app.page_classification.page_input import prepare_reviewed_document
from app.page_classification.service import PageClassificationService
from app.page_classification.store import (
    PageClassificationStore,
    canonical_classification_snapshot_bytes,
    classification_snapshot_sha256,
)

FIXTURE = Path(__file__).parent / "fixtures" / "reviewed_html_v1.html"
PROMPTS = Path(__file__).resolve().parents[2] / "src" / "app" / "page_classification" / "prompts"
FIXED_NOW = datetime(2026, 10, 1, 15, 0, 0, tzinfo=UTC)

_CALL_REQUEST_EXPECTATIONS: tuple[tuple[int, str, str, str], ...] = (
    (
        1,
        "01-materials-equipment.txt",
        "MaterialEquipmentResponse",
        "01-materials-equipment.schema.json",
    ),
    (
        2,
        "02-process-operations-controls.txt",
        "ProcessOperationsResponse",
        "02-process-operations-controls.schema.json",
    ),
    (
        3,
        "03-document-supporting-records.txt",
        "DocumentSupportingResponse",
        "03-document-supporting-records.schema.json",
    ),
)


def _wait_for(predicate: Any, *, timeout: float = 20.0, interval: float = 0.05) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("condition not met before timeout")


def _root(**overrides: str) -> str:
    values = {
        "version": "1",
        "job_id": "job-diag-1",
        "revision_id": "rev-diag-1",
        "generation": "1",
        "status": "SUCCEEDED",
    }
    values.update(overrides)
    return (
        "<!doctype html>"
        f'<html data-review-html-version="{values["version"]}" data-job-id="{values["job_id"]}" '
        f'data-review-revision-id="{values["revision_id"]}" '
        f'data-review-generation="{values["generation"]}" '
        f'data-conversion-status="{values["status"]}">'
    )


def _four_page_html() -> str:
    pages: list[str] = []
    for number in range(1, 5):
        pages.append(
            f'<section class="page" id="source-page-{number}" data-page="{number}">'
            f'<article class="element" data-kind="text" data-element-id="p{number}">'
            f'<p id="node-{number}" data-node-id="node-{number}">'
            f"Page {number} body content UNIQUE-{number}</p>"
            f"</article></section>"
        )
    return (
        f"{_root()}"
        '<head><meta charset="utf-8"><title>Reviewed document</title></head>'
        f"<body><main>{''.join(pages)}</main></body></html>"
    )


class SettingsWrapper:
    default_model = "gpt-4.1-mini"
    default_temperature = 0.0
    timeout_seconds = 20.0
    max_retries = 2
    max_output_tokens = 4096

    def __init__(self, handlers: dict[type[Any], Any] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._handlers = handlers or {}

    async def generate_structured(self, **kwargs: Any) -> LLMCallResult[Any]:
        self.calls.append(dict(kwargs))
        schema = kwargs["response_schema"]
        handler = self._handlers.get(schema)
        if isinstance(handler, Exception):
            raise handler
        if callable(handler):
            value = handler(kwargs)
            if isinstance(value, Exception):
                raise value
            if isinstance(value, LLMCallResult):
                return cast(LLMCallResult[Any], value)
            parsed = value
            raw = "{}"
        elif handler is None:
            parsed = schema.model_validate({"labels": [], "status": "empty", "evidence": []})
            raw = "{}"
        else:
            parsed = handler
            raw = json.dumps(parsed.model_dump(mode="json"), ensure_ascii=False)
        return LLMCallResult(
            model_name=self.default_model,
            raw_text=raw,
            parsed=parsed,
            attempts=1,
            latency_ms=12.5,
            guardrail_notes=[{"guardrail": "none", "stage": "input", "ok": True}],
        )


def _write_html(tmp_path: Path, html: str | None = None) -> Path:
    path = tmp_path / "reviewed.html"
    if html is None:
        path.write_bytes(FIXTURE.read_bytes())
    else:
        path.write_text(html, encoding="utf-8")
    return path


def _try_uuid_dir(name: str) -> bool:
    try:
        return str(uuid.UUID(name)) == name
    except ValueError:
        return False


def _assert_no_secrets(payload: object) -> None:
    text = json.dumps(payload, ensure_ascii=False)
    lowered = text.lower()
    assert "openai_api_key" not in lowered
    assert "authorization" not in lowered
    assert "sk-" not in text
    assert "api_key" not in lowered


def _wait_completed(service: PageClassificationService, reviewed_html: Any) -> None:
    def _ready() -> bool:
        current = service.get_current(reviewed_html)
        return current is not None and current.status == "completed"

    _wait_for(_ready)


def _wait_terminal(service: PageClassificationService, reviewed_html: Any) -> None:
    def _ready() -> bool:
        current = service.get_current(reviewed_html)
        return current is not None and current.status in {"completed", "failed"}

    _wait_for(_ready)


def test_successful_two_page_bundle_layout_and_hashes(tmp_path: Path) -> None:
    html_path = _write_html(tmp_path)
    prepared = prepare_reviewed_document(html_path)
    # Restrict runner path by using a two-page document copy via service on full fixture
    # but assert only that a complete 3-page run still produces one bundle; use custom 2-page HTML.
    two_page = (
        f"{_root()}"
        '<head><meta charset="utf-8"><title>Reviewed document</title></head><body><main>'
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="text" data-element-id="a1">'
        '<p id="n1" data-node-id="n1">Page one</p></article></section>'
        '<section class="page" id="source-page-2" data-page="2">'
        '<article class="element" data-kind="text" data-element-id="a2">'
        '<p id="n2" data-node-id="n2">Page two Sodium Chloride</p></article></section>'
        "</main></body></html>"
    )
    html_path = _write_html(tmp_path, two_page)
    prepared = prepare_reviewed_document(html_path)
    wrapper = SettingsWrapper()
    service = PageClassificationService(
        tmp_path / "data",
        wrapper,  # type: ignore[arg-type]
        clock=lambda: FIXED_NOW,
    )
    started = service.start_classification(html_path, expected=prepared.reviewed_html)
    assert started.classification_run_id is not None
    run_id = started.classification_run_id
    _wait_completed(service, prepared.reviewed_html)
    final = service.get_current(prepared.reviewed_html)
    assert final is not None
    assert final.status == "completed"
    assert final.classification_run_id == run_id

    bundle = diagnostics_root(tmp_path / "data") / run_id
    assert bundle.is_dir()
    manifest = json.loads((bundle / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert manifest["classification_run_id"] == run_id
    assert manifest["effective_settings"]["model"] == "gpt-4.1-mini"
    assert manifest["effective_settings"]["temperature"] == 0.0
    assert manifest["effective_settings"]["timeout_seconds"] == 20.0
    assert manifest["effective_settings"]["max_retries"] == 2
    assert manifest["effective_settings"]["max_output_tokens"] is None
    assert manifest["effective_settings"]["output_token_limit_configured"] is False
    _assert_no_secrets(manifest)

    for name in (
        "01-materials-equipment.txt",
        "02-process-operations-controls.txt",
        "03-document-supporting-records.txt",
    ):
        copied = bundle / "assets" / "prompts" / name
        assert copied.is_file()
        assert copied.read_text(encoding="utf-8") == (PROMPTS / name).read_text(encoding="utf-8")
        assert manifest["asset_sha256"][f"prompts/{name}"]

    for name in (
        "01-materials-equipment.schema.json",
        "02-process-operations-controls.schema.json",
        "03-document-supporting-records.schema.json",
    ):
        assert (bundle / "assets" / "schemas" / name).is_file()

    for page_number in (1, 2):
        page_dir = bundle / "pages" / f"page-{page_number:03d}"
        for call_id in (1, 2, 3):
            assert (page_dir / f"call-{call_id}-request.json").is_file()
            assert (page_dir / f"call-{call_id}-response.json").is_file()
        result = json.loads((page_dir / "result.json").read_text(encoding="utf-8"))
        assert result["binding"]["page_number"] == page_number
        assert len(result["call_outcomes"]) == 3
        assert result["eligibility"]["eligible_for_extraction"] is True
        current_page = next(
            item for item in final.page_results if item.binding.page_number == page_number
        )
        assert result == current_page.model_dump(mode="json")
        response = json.loads((page_dir / "call-1-response.json").read_text(encoding="utf-8"))
        assert response["raw_text"] == "{}"
        assert response["parsed"] == {"labels": [], "status": "empty", "evidence": []}
        assert response["attempts"] == 1
        assert response["latency_ms"] == 12.5
        assert response["call_outcome"]["availability"] == "valid"
        assert "guardrail_notes" not in response
        _assert_no_secrets(response)


def test_request_records_preserve_exact_prompt_and_page_html_for_pages_2_and_4(
    tmp_path: Path,
) -> None:
    html_path = _write_html(tmp_path, _four_page_html())
    prepared = prepare_reviewed_document(html_path)
    wrapper = SettingsWrapper()
    service = PageClassificationService(
        tmp_path / "data",
        wrapper,  # type: ignore[arg-type]
        clock=lambda: FIXED_NOW,
    )
    started = service.start_classification(html_path, expected=prepared.reviewed_html)
    _wait_completed(service, prepared.reviewed_html)
    run_id = started.classification_run_id
    assert run_id is not None
    bundle = diagnostics_root(tmp_path / "data") / run_id
    manifest = json.loads((bundle / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert manifest["effective_settings"]["max_output_tokens"] is None
    assert manifest["effective_settings"]["output_token_limit_configured"] is False
    schema_hashes = manifest["asset_sha256"]
    for page in prepared.pages:
        if page.binding.page_number not in {2, 4}:
            continue
        page_dir = bundle / "pages" / f"page-{page.binding.page_number:03d}"
        for call_id, prompt_name, schema_name, schema_file in _CALL_REQUEST_EXPECTATIONS:
            request = json.loads(
                (page_dir / f"call-{call_id}-request.json").read_text(encoding="utf-8")
            )
            assert request["messages"][0]["role"] == "system"
            assert request["messages"][0]["content"] == (PROMPTS / prompt_name).read_text(
                encoding="utf-8"
            )
            assert request["messages"][1]["role"] == "user"
            assert request["messages"][1]["content"] == page.page_html_fragment
            assert f"UNIQUE-{page.binding.page_number}" in request["messages"][1]["content"]
            assert request["response_schema_name"] == schema_name
            assert request["response_schema_sha256"] == schema_hashes[f"schemas/{schema_file}"]
            assert request["prompt_sha256"] == schema_hashes[f"prompts/{prompt_name}"]
            assert request["model"] == "gpt-4.1-mini"
            assert request["temperature"] == 0.0
            assert request["timeout_seconds"] == 20.0
            assert request["max_retries"] == 2
            assert request["max_output_tokens"] is None
            assert request["output_token_limit_configured"] is False
            _assert_no_secrets(request)


def test_failed_and_invalid_calls_and_source_evidence_needs_review(tmp_path: Path) -> None:
    html_path = _write_html(tmp_path)
    prepared = prepare_reviewed_document(html_path)

    def _invalid_process(_kwargs: dict[str, Any]) -> Any:
        # Bypass construction so runner re-validation yields availability=invalid.
        return ProcessOperationsResponse.model_construct(
            labels=["NOT_A_REAL_LABEL"],  # type: ignore[arg-type]
            status="ok",
            evidence=[],
        )

    def _unverified_support(_kwargs: dict[str, Any]) -> Any:
        return DocumentSupportingResponse.model_validate(
            {
                "labels": ["COVER_PAGE"],
                "status": "ok",
                "evidence": [
                    {
                        "label": "COVER_PAGE",
                        "quote": "THIS QUOTE IS NOT ON THE PAGE AT ALL",
                        "reason": "invented",
                        "element_id": None,
                    }
                ],
            }
        )

    wrapper = SettingsWrapper(
        handlers={
            MaterialEquipmentResponse: UpstreamServiceError("provider boom sk-secret"),
            ProcessOperationsResponse: _invalid_process,
            DocumentSupportingResponse: _unverified_support,
        }
    )
    service = PageClassificationService(
        tmp_path / "data",
        wrapper,  # type: ignore[arg-type]
        clock=lambda: FIXED_NOW,
    )
    service.start_classification(html_path, expected=prepared.reviewed_html)
    _wait_completed(service, prepared.reviewed_html)
    final = service.get_current(prepared.reviewed_html)
    assert final is not None
    assert final.status == "completed"
    run_id = final.classification_run_id
    assert run_id is not None
    page_dir = diagnostics_root(tmp_path / "data") / run_id / "pages" / "page-002"
    failed_response = json.loads((page_dir / "call-1-response.json").read_text(encoding="utf-8"))
    assert failed_response["error"]["code"] == "UPSTREAM_SERVICE_ERROR"
    assert failed_response["call_outcome"]["availability"] == "failed"
    assert failed_response["raw_text"] is None
    assert failed_response["refusal_text"] is None
    assert failed_response["structured_output_error"]["stage"] == "provider_response_unavailable"
    assert "sk-secret" not in json.dumps(failed_response)
    invalid_response = json.loads((page_dir / "call-2-response.json").read_text(encoding="utf-8"))
    assert invalid_response["call_outcome"]["availability"] == "invalid"
    assert "traceback" not in json.dumps(invalid_response).lower()
    support_response = json.loads((page_dir / "call-3-response.json").read_text(encoding="utf-8"))
    assert support_response["call_outcome"]["availability"] == "valid"
    result = json.loads((page_dir / "result.json").read_text(encoding="utf-8"))
    page_result = next(item for item in final.page_results if item.binding.page_number == 2)
    assert page_result.requires_review is True
    assert page_result.source_validation.has_unverified is True
    assert page_result.eligibility.eligible_for_extraction is True
    assert page_result.kind in {"incomplete", "needs_review"}
    assert result == page_result.model_dump(mode="json")


def test_parsing_error_is_safe_failed_call_record(tmp_path: Path) -> None:
    html = (
        f"{_root()}"
        '<head><meta charset="utf-8"><title>Reviewed document</title></head><body><main>'
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="text" data-element-id="a1">'
        '<p id="n1" data-node-id="n1">Only page</p></article></section>'
        "</main></body></html>"
    )
    html_path = _write_html(tmp_path, html)
    prepared = prepare_reviewed_document(html_path)
    wrapper = SettingsWrapper(
        handlers={
            MaterialEquipmentResponse: ModelOutputParsingError("bad json with sk-secret"),
        }
    )
    service = PageClassificationService(
        tmp_path / "data",
        wrapper,  # type: ignore[arg-type]
        clock=lambda: FIXED_NOW,
    )
    service.start_classification(html_path, expected=prepared.reviewed_html)
    _wait_completed(service, prepared.reviewed_html)
    final = service.get_current(prepared.reviewed_html)
    assert final is not None
    run_id = final.classification_run_id
    assert run_id is not None
    response = json.loads(
        (
            diagnostics_root(tmp_path / "data")
            / run_id
            / "pages"
            / "page-001"
            / "call-1-response.json"
        ).read_text(encoding="utf-8")
    )
    assert response["error"]["code"] == "MODEL_OUTPUT_PARSING_ERROR"
    assert response["error"]["message"] == (
        "classifier call failed: structured output parsing error"
    )
    assert "sk-secret" not in json.dumps(response)
    assert response["call_outcome"]["availability"] == "failed"
    assert response["raw_text"] is None
    assert response["refusal_text"] is None
    assert response["structured_output_error"] is None


def test_call_3_schema_validation_failure_preserves_raw_text_in_diagnostics(
    tmp_path: Path,
) -> None:
    html = (
        f"{_root()}"
        '<head><meta charset="utf-8"><title>Reviewed document</title></head><body><main>'
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="text" data-element-id="a1">'
        '<p id="n1" data-node-id="n1">Only page</p></article></section>'
        "</main></body></html>"
    )
    html_path = _write_html(tmp_path, html)
    prepared = prepare_reviewed_document(html_path)
    rejected_raw = json.dumps(
        {
            "labels": ["NOT_A_REAL_LABEL"],
            "status": "ok",
            "evidence": [
                {
                    "label": "NOT_A_REAL_LABEL",
                    "quote": "Only page",
                    "reason": "bad label",
                    "element_id": None,
                }
            ],
        }
    )
    wrapper = SettingsWrapper(
        handlers={
            DocumentSupportingResponse: ModelOutputParsingError(
                "structured response failed validation",
                raw_text=rejected_raw,
                model_name="gpt-4.1-mini",
                attempts=1,
                latency_ms=42.5,
                structured_output_error={
                    "stage": "schema_validation",
                    "error_type": "ValidationError",
                    "message": "structured response failed validation",
                    "validation_errors": [
                        {
                            "loc": ["labels", "0"],
                            "type": "literal_error",
                            "msg": "Input should be ...",
                        }
                    ],
                },
            ),
        }
    )
    service = PageClassificationService(
        tmp_path / "data-call3-parse",
        wrapper,  # type: ignore[arg-type]
        clock=lambda: FIXED_NOW,
    )
    service.start_classification(html_path, expected=prepared.reviewed_html)
    _wait_completed(service, prepared.reviewed_html)
    final = service.get_current(prepared.reviewed_html)
    assert final is not None
    run_id = final.classification_run_id
    assert run_id is not None
    response = json.loads(
        (
            diagnostics_root(tmp_path / "data-call3-parse")
            / run_id
            / "pages"
            / "page-001"
            / "call-3-response.json"
        ).read_text(encoding="utf-8")
    )
    assert response["error"]["code"] == "MODEL_OUTPUT_PARSING_ERROR"
    assert response["error"]["message"] == (
        "classifier call failed: structured output parsing error"
    )
    assert response["raw_text"] == rejected_raw
    assert response["refusal_text"] is None
    assert response["model_name"] == "gpt-4.1-mini"
    assert response["attempts"] == 1
    assert response["latency_ms"] == 42.5
    assert response["structured_output_error"]["stage"] == "schema_validation"
    assert response["structured_output_error"]["validation_errors"][0]["loc"] == [
        "labels",
        "0",
    ]
    assert response["call_outcome"]["availability"] == "failed"
    text = json.dumps(response)
    assert "sk-" not in text
    assert "traceback" not in text.lower()
    assert '"input"' not in text
    assert "authorization" not in text.lower()


def test_refusal_preserves_exact_refusal_text_in_diagnostics(tmp_path: Path) -> None:
    html = (
        f"{_root()}"
        '<head><meta charset="utf-8"><title>Reviewed document</title></head><body><main>'
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="text" data-element-id="a1">'
        '<p id="n1" data-node-id="n1">Only page</p></article></section>'
        "</main></body></html>"
    )
    html_path = _write_html(tmp_path, html)
    prepared = prepare_reviewed_document(html_path)
    refusal = "I refuse to classify this page under the requested schema."
    wrapper = SettingsWrapper(
        handlers={
            DocumentSupportingResponse: ModelOutputParsingError(
                "structured response refused",
                raw_text=None,
                refusal_text=refusal,
                model_name="gpt-4.1-mini",
                attempts=1,
                latency_ms=11.0,
                structured_output_error={
                    "stage": "refusal",
                    "error_type": "Refusal",
                    "message": "model refused structured response",
                    "validation_errors": [],
                },
            ),
        }
    )
    service = PageClassificationService(
        tmp_path / "data-refusal",
        wrapper,  # type: ignore[arg-type]
        clock=lambda: FIXED_NOW,
    )
    service.start_classification(html_path, expected=prepared.reviewed_html)
    _wait_completed(service, prepared.reviewed_html)
    final = service.get_current(prepared.reviewed_html)
    assert final is not None
    run_id = final.classification_run_id
    assert run_id is not None
    response = json.loads(
        (
            diagnostics_root(tmp_path / "data-refusal")
            / run_id
            / "pages"
            / "page-001"
            / "call-3-response.json"
        ).read_text(encoding="utf-8")
    )
    assert response["error"]["code"] == "MODEL_OUTPUT_PARSING_ERROR"
    assert response["error"]["message"] == (
        "classifier call failed: structured output parsing error"
    )
    assert response["refusal_text"] == refusal
    assert response["raw_text"] is None
    assert response["structured_output_error"]["stage"] == "refusal"
    assert "traceback" not in json.dumps(response).lower()


def test_source_evidence_mismatch_is_needs_review_not_diagnostic_failure(
    tmp_path: Path,
) -> None:
    html_path = _write_html(tmp_path)
    prepared = prepare_reviewed_document(html_path)

    def _unverified_support(_kwargs: dict[str, Any]) -> Any:
        return DocumentSupportingResponse.model_validate(
            {
                "labels": ["COVER_PAGE"],
                "status": "ok",
                "evidence": [
                    {
                        "label": "COVER_PAGE",
                        "quote": "THIS QUOTE IS NOT ON THE PAGE AT ALL",
                        "reason": "invented",
                        "element_id": None,
                    }
                ],
            }
        )

    wrapper = SettingsWrapper(handlers={DocumentSupportingResponse: _unverified_support})
    service = PageClassificationService(
        tmp_path / "data-evidence",
        wrapper,  # type: ignore[arg-type]
        clock=lambda: FIXED_NOW,
    )
    service.start_classification(html_path, expected=prepared.reviewed_html)
    _wait_completed(service, prepared.reviewed_html)
    final = service.get_current(prepared.reviewed_html)
    assert final is not None
    assert final.status == "completed"
    run_id = final.classification_run_id
    assert run_id is not None
    page_result = next(item for item in final.page_results if item.binding.page_number == 2)
    assert page_result.kind == "needs_review"
    assert page_result.source_validation.has_unverified is True
    assert page_result.requires_review is True
    assert page_result.eligibility.eligible_for_extraction is True
    result = json.loads(
        (
            diagnostics_root(tmp_path / "data-evidence")
            / run_id
            / "pages"
            / "page-002"
            / "result.json"
        ).read_text(encoding="utf-8")
    )
    assert result == page_result.model_dump(mode="json")


def test_diagnostic_write_failure_prevents_false_completion(tmp_path: Path) -> None:
    html_path = _write_html(tmp_path)
    prepared = prepare_reviewed_document(html_path)
    wrapper = SettingsWrapper()

    class BoomRunner:
        async def classify_page(
            self,
            page: Any,
            *,
            on_complete: Any = None,
            diagnostics: Any = None,
        ) -> Any:
            raise DiagnosticPersistenceError("injected diagnostic write failure")

    service = PageClassificationService(
        tmp_path / "data-boom",
        wrapper,  # type: ignore[arg-type]
        runner=BoomRunner(),  # type: ignore[arg-type]
        clock=lambda: FIXED_NOW,
    )
    started = service.start_classification(html_path, expected=prepared.reviewed_html)
    _wait_for(lambda: (service.get_current(prepared.reviewed_html) or started).status == "failed")
    state = service.get_current(prepared.reviewed_html)
    assert state is not None
    assert state.status == "failed"
    assert state.terminal_reason == "injected diagnostic write failure"
    assert state.progress.completed_pages == 0


def test_restart_interrupts_matching_bundle_and_legacy_loads(tmp_path: Path) -> None:
    html_path = _write_html(tmp_path)
    prepared = prepare_reviewed_document(html_path)
    data = tmp_path / "data"
    store = PageClassificationStore(data)
    run_id = str(uuid.uuid4())
    wrapper = SettingsWrapper()
    begin_classification_diagnostics(
        data,
        classification_run_id=run_id,
        reviewed_html=prepared.reviewed_html,
        total_pages=3,
        wrapper=wrapper,
        clock=lambda: FIXED_NOW,
    )
    abandoned = CurrentClassificationState(
        reviewed_html=prepared.reviewed_html,
        status="running",
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
        progress=ClassificationProgress(
            total_pages=3,
            completed_pages=0,
            current_page_number=1,
        ),
        page_results=(),
        classification_run_id=run_id,
    )
    store.save(abandoned)
    service = PageClassificationService(data, wrapper, clock=lambda: FIXED_NOW)  # type: ignore[arg-type]
    state = service.get_current(prepared.reviewed_html)
    assert state is not None
    assert state.status == "interrupted"
    manifest = json.loads(
        (diagnostics_root(data) / run_id / MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    assert manifest["status"] == "interrupted"

    legacy = CurrentClassificationState(
        reviewed_html=prepared.reviewed_html,
        status="interrupted",
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
        finished_at=FIXED_NOW,
        progress=ClassificationProgress(
            total_pages=3,
            completed_pages=0,
            current_page_number=None,
        ),
        page_results=(),
        terminal_reason="legacy interrupted without diagnostics",
    )
    store.save(legacy)
    loaded = store.load(prepared.reviewed_html)
    assert loaded is not None
    assert loaded.classification_run_id is None
    assert loaded.status == "interrupted"


def test_guardrail_notes_are_not_persisted_in_diagnostic_artifacts(tmp_path: Path) -> None:
    html = (
        f"{_root()}"
        '<head><meta charset="utf-8"><title>Reviewed document</title></head><body><main>'
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="text" data-element-id="a1">'
        '<p id="n1" data-node-id="n1">Only page</p></article></section>'
        "</main></body></html>"
    )
    html_path = _write_html(tmp_path, html)
    prepared = prepare_reviewed_document(html_path)

    class SecretNoteWrapper(SettingsWrapper):
        async def generate_structured(self, **kwargs: Any) -> LLMCallResult[Any]:
            result = await super().generate_structured(**kwargs)
            return LLMCallResult(
                model_name=result.model_name,
                raw_text=result.raw_text,
                parsed=result.parsed,
                attempts=result.attempts,
                latency_ms=result.latency_ms,
                guardrail_notes=[{"message": "leaked sk-secret-token"}],
            )

    service = PageClassificationService(
        tmp_path / "data-guardrail",
        SecretNoteWrapper(),  # type: ignore[arg-type]
        clock=lambda: FIXED_NOW,
    )
    service.start_classification(html_path, expected=prepared.reviewed_html)
    _wait_completed(service, prepared.reviewed_html)
    final = service.get_current(prepared.reviewed_html)
    assert final is not None
    run_id = final.classification_run_id
    assert run_id is not None
    bundle = diagnostics_root(tmp_path / "data-guardrail") / run_id
    for path in bundle.rglob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert "guardrail_notes" not in text
        assert "sk-secret-token" not in text


def test_write_call_request_failure_issues_no_wrapper_calls(tmp_path: Path) -> None:
    html = (
        f"{_root()}"
        '<head><meta charset="utf-8"><title>Reviewed document</title></head><body><main>'
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="text" data-element-id="a1">'
        '<p id="n1" data-node-id="n1">Only page</p></article></section>'
        "</main></body></html>"
    )
    html_path = _write_html(tmp_path, html)
    prepared = prepare_reviewed_document(html_path)
    wrapper = SettingsWrapper()
    with patch.object(
        ClassificationDiagnosticSession,
        "write_call_request",
        side_effect=DiagnosticPersistenceError("request write failed"),
    ):
        service = PageClassificationService(
            tmp_path / "data-fail-request",
            wrapper,  # type: ignore[arg-type]
            clock=lambda: FIXED_NOW,
        )
        service.start_classification(html_path, expected=prepared.reviewed_html)
        _wait_terminal(service, prepared.reviewed_html)
    assert len(wrapper.calls) == 0
    state = service.get_current(prepared.reviewed_html)
    assert state is not None
    assert state.status == "failed"
    assert state.terminal_reason == "request write failed"
    assert state.progress.completed_pages == 0


def test_late_diagnostic_write_failure_stops_further_classifier_calls(tmp_path: Path) -> None:
    html = (
        f"{_root()}"
        '<head><meta charset="utf-8"><title>Reviewed document</title></head><body><main>'
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="text" data-element-id="a1">'
        '<p id="n1" data-node-id="n1">Only page</p></article></section>'
        "</main></body></html>"
    )
    html_path = _write_html(tmp_path, html)
    prepared = prepare_reviewed_document(html_path)
    wrapper = SettingsWrapper()
    original = ClassificationDiagnosticSession.write_call_response_success

    def _fail_on_call_two(self: ClassificationDiagnosticSession, **kwargs: Any) -> None:
        if kwargs.get("call_id") == 2:
            raise DiagnosticPersistenceError("late response write failed")
        original(self, **kwargs)

    with patch.object(
        ClassificationDiagnosticSession,
        "write_call_response_success",
        _fail_on_call_two,
    ):
        service = PageClassificationService(
            tmp_path / "data-late-fail",
            wrapper,  # type: ignore[arg-type]
            clock=lambda: FIXED_NOW,
        )
        service.start_classification(html_path, expected=prepared.reviewed_html)
        _wait_terminal(service, prepared.reviewed_html)
    assert len(wrapper.calls) == 2
    state = service.get_current(prepared.reviewed_html)
    assert state is not None
    assert state.status == "failed"
    assert state.terminal_reason == "late response write failed"
    assert state.progress.completed_pages == 0


def test_malformed_classification_run_id_recovery_skips_diagnostic_bundle(tmp_path: Path) -> None:
    html_path = _write_html(tmp_path)
    prepared = prepare_reviewed_document(html_path)
    data = tmp_path / "data"
    store = PageClassificationStore(data)
    bogus_run_id = "not-a-canonical-uuid"
    bogus_bundle = diagnostics_root(data) / bogus_run_id
    bogus_bundle.mkdir(parents=True)
    (bogus_bundle / "keep.txt").write_text("must survive", encoding="utf-8")
    abandoned = CurrentClassificationState(
        reviewed_html=prepared.reviewed_html,
        status="running",
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
        progress=ClassificationProgress(
            total_pages=3,
            completed_pages=0,
            current_page_number=1,
        ),
        page_results=(),
        classification_run_id=bogus_run_id,
    )
    store.save(abandoned)
    wrapper = SettingsWrapper()
    service = PageClassificationService(data, wrapper, clock=lambda: FIXED_NOW)  # type: ignore[arg-type]
    state = service.get_current(prepared.reviewed_html)
    assert state is not None
    assert state.status == "interrupted"
    assert state.classification_run_id == bogus_run_id
    assert (bogus_bundle / "keep.txt").read_text(encoding="utf-8") == "must survive"
    assert not (bogus_bundle / MANIFEST_FILENAME).is_file()


def test_retention_keeps_newest_five_bundles(tmp_path: Path) -> None:
    html = (
        f"{_root()}"
        '<head><meta charset="utf-8"><title>Reviewed document</title></head><body><main>'
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="text" data-element-id="a1">'
        '<p id="n1" data-node-id="n1">Only page</p></article></section>'
        "</main></body></html>"
    )
    html_path = _write_html(tmp_path, html)
    prepared = prepare_reviewed_document(html_path)
    data = tmp_path / "data"
    sentinel = data / "page-classifications" / "do-not-delete.txt"
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("keep me", encoding="utf-8")
    outside = tmp_path / "outside-diagnostics" / "keep.txt"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("outside", encoding="utf-8")
    unrelated = diagnostics_root(data) / "operator-notes"
    unrelated.mkdir(parents=True)
    (unrelated / "readme.txt").write_text("keep unrelated", encoding="utf-8")
    wrapper = SettingsWrapper()
    run_ids: list[str] = []
    base = FIXED_NOW
    for index in range(6):
        clock_now = base + timedelta(seconds=index)
        service = PageClassificationService(
            data,
            wrapper,  # type: ignore[arg-type]
            clock=lambda now=clock_now: now,
        )
        started = service.start_classification(html_path, expected=prepared.reviewed_html)
        assert started.classification_run_id is not None
        run_ids.append(started.classification_run_id)
        _wait_terminal(service, prepared.reviewed_html)
    root = diagnostics_root(data)
    remaining_bundle_ids = sorted(
        path.name for path in root.iterdir() if path.is_dir() and _try_uuid_dir(path.name)
    )
    assert len(remaining_bundle_ids) == 5
    assert run_ids[0] not in remaining_bundle_ids
    assert set(run_ids[1:]) == set(remaining_bundle_ids)
    assert unrelated.is_dir()
    assert (unrelated / "readme.txt").read_text(encoding="utf-8") == "keep unrelated"
    assert sentinel.read_text(encoding="utf-8") == "keep me"
    assert outside.read_text(encoding="utf-8") == "outside"


def test_classified_snapshot_retains_classification_run_id(tmp_path: Path) -> None:
    html_path = _write_html(tmp_path)
    prepared = prepare_reviewed_document(html_path)
    wrapper = SettingsWrapper()
    service = PageClassificationService(
        tmp_path / "data",
        wrapper,  # type: ignore[arg-type]
        clock=lambda: FIXED_NOW,
    )
    service.start_classification(html_path, expected=prepared.reviewed_html)
    _wait_completed(service, prepared.reviewed_html)
    state = service.get_current(prepared.reviewed_html)
    assert state is not None
    assert state.classification_run_id is not None
    snapshot = canonical_classification_snapshot_bytes(state)
    payload = json.loads(snapshot.decode("utf-8"))
    assert payload["classification_run_id"] == state.classification_run_id
    digest = classification_snapshot_sha256(state)
    assert isinstance(digest, str) and len(digest) == 64


def test_final_completed_manifest_failure_does_not_claim_completed(tmp_path: Path) -> None:
    html = (
        f"{_root()}"
        '<head><meta charset="utf-8"><title>Reviewed document</title></head><body><main>'
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="text" data-element-id="a1">'
        '<p id="n1" data-node-id="n1">Only page</p></article></section>'
        "</main></body></html>"
    )
    html_path = _write_html(tmp_path, html)
    prepared = prepare_reviewed_document(html_path)
    wrapper = SettingsWrapper()
    original_finalize = ClassificationDiagnosticSession.finalize

    def _fail_completed_finalize(
        self: ClassificationDiagnosticSession,
        status: Any,
        *,
        terminal_reason: str | None = None,
        completed_pages: int | None = None,
    ) -> None:
        if status == "completed":
            raise DiagnosticPersistenceError(
                "page classification diagnostic artifact could not be written"
            )
        original_finalize(
            self,
            status,
            terminal_reason=terminal_reason,
            completed_pages=completed_pages,
        )

    with patch.object(ClassificationDiagnosticSession, "finalize", _fail_completed_finalize):
        service = PageClassificationService(
            tmp_path / "data-final-manifest",
            wrapper,  # type: ignore[arg-type]
            clock=lambda: FIXED_NOW,
        )
        started = service.start_classification(html_path, expected=prepared.reviewed_html)
        run_id = started.classification_run_id
        assert run_id is not None
        _wait_terminal(service, prepared.reviewed_html)

    state = service.get_current(prepared.reviewed_html)
    assert state is not None
    assert state.status == "failed"
    assert state.status != "completed"
    assert state.terminal_reason == ("page classification diagnostic artifact could not be written")
    assert "traceback" not in (state.terminal_reason or "").lower()
    manifest = json.loads(
        (diagnostics_root(tmp_path / "data-final-manifest") / run_id / MANIFEST_FILENAME).read_text(
            encoding="utf-8"
        )
    )
    assert manifest["status"] == "failed"
    assert manifest["status"] != "completed"


def test_current_state_save_failure_after_diagnostic_completion_compensates(
    tmp_path: Path,
) -> None:
    html = (
        f"{_root()}"
        '<head><meta charset="utf-8"><title>Reviewed document</title></head><body><main>'
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="text" data-element-id="a1">'
        '<p id="n1" data-node-id="n1">Only page</p></article></section>'
        "</main></body></html>"
    )
    html_path = _write_html(tmp_path, html)
    prepared = prepare_reviewed_document(html_path)
    wrapper = SettingsWrapper()
    original_save = PageClassificationStore.save

    def _fail_completed_save(
        self: PageClassificationStore,
        state: CurrentClassificationState,
    ) -> CurrentClassificationState:
        if state.status == "completed":
            raise OSError("disk full with sk-secret and traceback detail")
        return original_save(self, state)

    with patch.object(PageClassificationStore, "save", _fail_completed_save):
        service = PageClassificationService(
            tmp_path / "data-current-save",
            wrapper,  # type: ignore[arg-type]
            clock=lambda: FIXED_NOW,
        )
        started = service.start_classification(html_path, expected=prepared.reviewed_html)
        run_id = started.classification_run_id
        assert run_id is not None
        _wait_terminal(service, prepared.reviewed_html)

    state = service.get_current(prepared.reviewed_html)
    assert state is not None
    assert state.status == "failed"
    assert state.status != "completed"
    assert state.terminal_reason == "page classification current-state persistence failed"
    assert "sk-secret" not in (state.terminal_reason or "")
    assert "traceback" not in (state.terminal_reason or "").lower()
    manifest = json.loads(
        (diagnostics_root(tmp_path / "data-current-save") / run_id / MANIFEST_FILENAME).read_text(
            encoding="utf-8"
        )
    )
    assert manifest["status"] == "failed"
    assert manifest["status"] != "completed"
    assert "sk-secret" not in json.dumps(manifest)


def test_normal_success_keeps_current_and_diagnostic_completed(tmp_path: Path) -> None:
    html = (
        f"{_root()}"
        '<head><meta charset="utf-8"><title>Reviewed document</title></head><body><main>'
        '<section class="page" id="source-page-1" data-page="1">'
        '<article class="element" data-kind="text" data-element-id="a1">'
        '<p id="n1" data-node-id="n1">Only page</p></article></section>'
        "</main></body></html>"
    )
    html_path = _write_html(tmp_path, html)
    prepared = prepare_reviewed_document(html_path)
    wrapper = SettingsWrapper()
    service = PageClassificationService(
        tmp_path / "data-success",
        wrapper,  # type: ignore[arg-type]
        clock=lambda: FIXED_NOW,
    )
    started = service.start_classification(html_path, expected=prepared.reviewed_html)
    run_id = started.classification_run_id
    assert run_id is not None
    _wait_completed(service, prepared.reviewed_html)
    state = service.get_current(prepared.reviewed_html)
    assert state is not None
    assert state.status == "completed"
    assert state.classification_run_id == run_id
    manifest = json.loads(
        (diagnostics_root(tmp_path / "data-success") / run_id / MANIFEST_FILENAME).read_text(
            encoding="utf-8"
        )
    )
    assert manifest["status"] == "completed"
    assert manifest["classification_run_id"] == run_id
    assert manifest["progress"]["completed_pages"] == 1
    assert manifest["progress"]["total_pages"] == 1
