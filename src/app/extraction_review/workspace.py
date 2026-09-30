"""Local Stage 3 extraction-review workspace.

Opens one completed U2 lexical job, initialises the existing U1 current-state
store from published L13 occurrences when needed, and applies page-scoped Save
and final approval through the existing transitions. There is no revision
history, projection framework, or second persistence layer.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.extraction_review.approved_documents import (
    ApprovedDocumentError,
    ApprovedDocumentsRegistry,
    SelectedApprovedDocument,
)
from app.extraction_review.contracts import (
    MAX_FINDINGS_PER_REVIEW,
    AddFindingEdit,
    ApproveExtractionResultCommand,
    AssignedPage,
    DocumentSourceReference,
    ExtractionReviewState,
    ExtractionRunReference,
    FindingEvidenceStatus,
    InitializeReviewCommand,
    LexicalFindingOrigin,
    OriginalLexicalEvidence,
    PageAssignment,
    PatchFindingTextEdit,
    RemoveFindingEdit,
    ReplaceFindingEdit,
    RestoreFindingEdit,
    ReviewFindingRecord,
    SaveReviewEditsCommand,
    TransitionOutcomeKind,
    UserFacingFinding,
    has_usable_completed_component,
)
from app.extraction_review.local_jobs import (
    JOBS_DIR_NAME,
    RAW_RUNS_DIR_NAME,
    LocalJobStatus,
    LocalLexicalJob,
)
from app.extraction_review.page_html import PageHighlight, render_reviewed_page_html
from app.extraction_review.store import (
    ExtractionReviewAlreadyExistsError,
    ExtractionReviewNotFoundError,
    ExtractionReviewStore,
)
from app.lexical_extraction.contracts import (
    CharSpan,
    Component,
    DictionaryOccurrence,
    ExtractionOutcome,
    LexicalOccurrence,
    PublicationStatus,
    UnitOccurrence,
)
from app.lexical_extraction.html_reader import ReviewedHtmlReadError, open_reviewed_html
from app.lexical_extraction.publication import (
    MANIFEST_FILE_NAME,
    PublicationError,
    iter_component_pages,
    load_final_manifest,
    verify_artifact_hashes,
)

logger = logging.getLogger("app.extraction_review.workspace")

LOCAL_REVIEW_ACTOR = "local-test-reviewer"

_CATEGORY_CLASS: dict[Component, str] = {
    Component.UNIT_OPERATIONS: "bl-hit--unit-operation",
    Component.MATERIALS: "bl-hit--material",
    Component.EQUIPMENT: "bl-hit--equipment",
}


class ExtractionWorkspaceError(Exception):
    """Safe workspace failure. ``message`` never includes paths or raw exceptions."""

    def __init__(self, code: str, message: str, status: int) -> None:
        self.code = code
        self.message = message
        self.status = status
        super().__init__(code)


class PageEditModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str = Field(min_length=1)
    page_number: int = Field(ge=1)


class AddPageEdit(PageEditModel):
    op: Literal["add"] = "add"
    component: Component
    display_text: str = Field(min_length=1)


class PatchPageEdit(PageEditModel):
    op: Literal["patch_text"] = "patch_text"
    display_text: str = Field(min_length=1)


class ReplacePageEdit(PageEditModel):
    op: Literal["replace"] = "replace"
    component: Component
    display_text: str = Field(min_length=1)


class RemovePageEdit(PageEditModel):
    op: Literal["remove"] = "remove"
    note: str | None = None


class RestorePageEdit(PageEditModel):
    op: Literal["restore"] = "restore"


PageEdit = AddPageEdit | PatchPageEdit | ReplacePageEdit | RemovePageEdit | RestorePageEdit


class ExtractionReviewWorkspace:
    """Read completed local lexical jobs and persist one current extraction review."""

    def __init__(
        self,
        data_dir: Path,
        approved_documents_root: Path,
        *,
        actor: str = LOCAL_REVIEW_ACTOR,
        clock: Callable[[], datetime] | None = None,
        revision_id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not actor:
            raise ValueError("actor must be non-empty")
        self._data_dir = data_dir.expanduser().resolve()
        self._approved_root = approved_documents_root.expanduser().resolve()
        self._actor = actor
        self._clock = clock or _utc_now
        self._revision_ids = revision_id_factory or _new_revision_id
        self._store = ExtractionReviewStore(self._data_dir)
        self._selected: dict[str, SelectedApprovedDocument] = {}
        self._page_numbers: dict[str, tuple[int, ...]] = {}

    @property
    def actor(self) -> str:
        return self._actor

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    def list_completed_jobs(self) -> tuple[LocalLexicalJob, ...]:
        jobs = [job for job in self._read_jobs() if _is_reviewable(job)]
        jobs.sort(key=lambda job: (job.finished_at or job.submitted_at, job.local_job_id))
        return tuple(jobs)

    def open_job(
        self, local_job_id: str
    ) -> tuple[LocalLexicalJob, ExtractionReviewState, tuple[int, ...]]:
        job = self._require_reviewable(local_job_id)
        state = self._load_or_initialize(job)
        return job, state, self._pages_for(job)

    def page_html(self, local_job_id: str, page_number: int) -> str:
        job, state, pages = self.open_job(local_job_id)
        if page_number not in pages:
            raise ExtractionWorkspaceError("PAGE_NOT_FOUND", "reviewed page was not found", 404)
        selected = self._selected_document(job)
        try:
            document_html = selected.html_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ExtractionWorkspaceError(
                "DOCUMENT_NOT_AVAILABLE",
                "reviewed HTML for this job is not available",
                404,
            ) from exc
        rendered = render_reviewed_page_html(
            document_html,
            page_number,
            _highlights_for_page(state, page_number),
        )
        if rendered is None:
            raise ExtractionWorkspaceError("PAGE_NOT_FOUND", "reviewed page was not found", 404)
        return rendered

    def save_page_edits(
        self,
        local_job_id: str,
        *,
        expected_revision_id: str,
        edits: Sequence[PageEdit],
    ) -> ExtractionReviewState:
        job = self._require_reviewable(local_job_id)
        try:
            state = self._store.load(job.local_job_id)
        except ExtractionReviewNotFoundError as exc:
            raise ExtractionWorkspaceError(
                "REVIEW_NOT_FOUND",
                "open the extraction job before saving",
                404,
            ) from exc
        self._require_same_run(state, job)
        pages = self._pages_for(job)
        commands = tuple(self._edit_command(edit, state, pages) for edit in edits)
        try:
            command = SaveReviewEditsCommand(
                expected_revision_id=expected_revision_id,
                actor=self._actor,
                at=self._clock(),
                edits=commands,
            )
        except ValidationError as exc:
            raise ExtractionWorkspaceError(
                "INVALID_REVIEW",
                "save request is invalid",
                422,
            ) from exc
        outcome = self._store.save_edits(
            job.local_job_id,
            command,
            new_revision_id=self._revision_ids(),
        )
        return self._require_transition_state(
            outcome.outcome, outcome.state, outcome.message, "save"
        )

    def approve_saved_result(
        self,
        local_job_id: str,
        *,
        expected_revision_id: str,
    ) -> ExtractionReviewState:
        job = self._require_reviewable(local_job_id)
        try:
            state = self._store.load(job.local_job_id)
        except ExtractionReviewNotFoundError as exc:
            raise ExtractionWorkspaceError(
                "REVIEW_NOT_FOUND",
                "open the extraction job before approval",
                404,
            ) from exc
        self._require_same_run(state, job)
        try:
            command = ApproveExtractionResultCommand(
                expected_revision_id=expected_revision_id,
                actor=self._actor,
                at=self._clock(),
                target_revision_id=expected_revision_id,
            )
        except ValidationError as exc:
            raise ExtractionWorkspaceError(
                "INVALID_REVIEW",
                "approval request is invalid",
                422,
            ) from exc
        outcome = self._store.approve(job.local_job_id, command)
        return self._require_transition_state(
            outcome.outcome,
            outcome.state,
            outcome.message,
            "approve",
        )

    def results_txt(self, local_job_id: str) -> str:
        """Format the current saved extraction-review findings as plain text."""

        _job, state, _pages = self.open_job(local_job_id)
        return format_extraction_results_txt(state)

    def _load_or_initialize(self, job: LocalLexicalJob) -> ExtractionReviewState:
        try:
            state = self._store.load(job.local_job_id)
        except ExtractionReviewNotFoundError:
            state = None
        if state is not None:
            self._require_same_run(state, job)
            return state
        findings = self._project_findings(job)
        reviewed = job.reviewed_html
        run = job.run
        publication = job.publication
        extraction = job.extraction
        manifest = job.published_manifest
        if (
            reviewed is None
            or run is None
            or publication is None
            or extraction is None
            or manifest is None
        ):
            raise ExtractionWorkspaceError(
                "JOB_NOT_REVIEWABLE",
                "completed job is missing published review inputs",
                409,
            )
        try:
            command = InitializeReviewCommand(
                revision_id=self._revision_ids(),
                actor=self._actor,
                created_at=self._clock(),
                document_source=DocumentSourceReference(
                    job_id=job.job_id,
                    document_hash=None,
                    reviewed_html=reviewed,
                ),
                run=ExtractionRunReference(
                    run=run,
                    publication=publication,
                    published_manifest=manifest,
                ),
                extraction=extraction,
                findings=findings,
            )
        except ValidationError as exc:
            raise ExtractionWorkspaceError(
                "INVALID_REVIEW",
                "published lexical findings could not initialize a review",
                422,
            ) from exc
        try:
            created = self._store.create(job.local_job_id, command)
        except ExtractionReviewAlreadyExistsError:
            created = self._store.load(job.local_job_id)
            self._require_same_run(created, job)
            return created
        except ValueError as exc:
            raise ExtractionWorkspaceError(
                "INVALID_REVIEW",
                _safe_message(exc, "extraction review could not be initialized"),
                422,
            ) from exc
        logger.info(
            "extraction_review_initialized local_job_id=%s job_id=%s finding_count=%s",
            job.local_job_id,
            job.job_id,
            len(created.findings),
        )
        return created

    def _project_findings(self, job: LocalLexicalJob) -> tuple[ReviewFindingRecord, ...]:
        if (
            job.extraction is None
            or job.raw_run_relative_dir is None
            or job.published_manifest is None
        ):
            raise ExtractionWorkspaceError(
                "JOB_NOT_REVIEWABLE",
                "completed job is missing published review inputs",
                409,
            )
        run_dir = _resolve_raw_run(self._data_dir, job.raw_run_relative_dir)
        manifest_path = run_dir / MANIFEST_FILE_NAME
        if not manifest_path.is_file():
            raise ExtractionWorkspaceError(
                "ARTIFACT_REJECTED",
                "published manifest was not found",
                422,
            )
        digest = _sha256_file(manifest_path)
        if digest != job.published_manifest.manifest_sha256:
            raise ExtractionWorkspaceError(
                "ARTIFACT_REJECTED",
                "published manifest hash does not match the completed job",
                422,
            )
        try:
            payload = load_final_manifest(manifest_path)
            verified = verify_artifact_hashes(payload, run_dir)
        except PublicationError as exc:
            raise ExtractionWorkspaceError(
                "ARTIFACT_REJECTED",
                "published lexical artifacts could not be verified",
                422,
            ) from exc
        manifest_id = payload.get("manifest_id")
        if manifest_id != job.published_manifest.manifest_id:
            raise ExtractionWorkspaceError(
                "ARTIFACT_REJECTED",
                "published manifest id does not match the completed job",
                422,
            )
        completed = {
            item.component
            for item in job.extraction.components
            if item.outcome is ExtractionOutcome.COMPLETED
        }
        by_component = {artifact.component: artifact for artifact in verified}
        if set(by_component) != completed:
            missing = completed - set(by_component)
            extra = set(by_component) - completed
            if missing or extra:
                raise ExtractionWorkspaceError(
                    "ARTIFACT_REJECTED",
                    "published artifacts do not match completed extraction components",
                    422,
                )
        collected: dict[str, ReviewFindingRecord] = {}
        order: list[tuple[tuple[int, int, int, int, str, str], str]] = []
        for component in completed:
            descriptor = by_component[component]
            artifact_path = _artifact_file(run_dir, descriptor.relative_path)
            try:
                for streamed in iter_component_pages(artifact_path):
                    page_number = streamed.page.page_number
                    for record in streamed.iter_blocks():
                        for finding, sort_key in _findings_from_block(
                            record.block.order,
                            page_number,
                            record.block.node_id,
                            record.occurrences,
                        ):
                            _remember_finding(collected, order, finding, sort_key)
            except PublicationError as exc:
                raise ExtractionWorkspaceError(
                    "ARTIFACT_REJECTED",
                    "published lexical artifacts could not be read",
                    422,
                ) from exc
        if len(collected) > MAX_FINDINGS_PER_REVIEW:
            raise ExtractionWorkspaceError(
                "PROJECTION_LIMIT",
                "published lexical findings exceed the current review limit",
                422,
            )
        order.sort(key=lambda item: item[0])
        return tuple(collected[finding_id] for _, finding_id in order)

    def _require_reviewable(self, local_job_id: str) -> LocalLexicalJob:
        match = next((job for job in self._read_jobs() if job.local_job_id == local_job_id), None)
        if match is None:
            raise ExtractionWorkspaceError("JOB_NOT_FOUND", "extraction job was not found", 404)
        if not _is_reviewable(match):
            raise ExtractionWorkspaceError(
                "JOB_NOT_REVIEWABLE",
                "only a completed published extraction job can be reviewed",
                409,
            )
        return match

    def _read_jobs(self) -> Iterator[LocalLexicalJob]:
        jobs_dir = self._data_dir / JOBS_DIR_NAME
        if not jobs_dir.is_dir():
            return
        for path in sorted(jobs_dir.glob("*.json")):
            if not path.is_file() or path.name.startswith("."):
                continue
            try:
                job = LocalLexicalJob.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                logger.warning("extraction_job_unreadable name=%s", path.name)
                continue
            if path.stem != job.local_job_id:
                continue
            yield job

    def _selected_document(self, job: LocalLexicalJob) -> SelectedApprovedDocument:
        cached = self._selected.get(job.local_job_id)
        if cached is not None:
            return cached
        if job.reviewed_html is None:
            raise ExtractionWorkspaceError(
                "JOB_NOT_REVIEWABLE",
                "completed job is missing reviewed HTML provenance",
                409,
            )
        try:
            selected = ApprovedDocumentsRegistry(self._approved_root).select(
                job.job_id,
                job.review_revision_id,
            )
        except ApprovedDocumentError as exc:
            raise ExtractionWorkspaceError(
                "DOCUMENT_NOT_AVAILABLE",
                "reviewed HTML for this job is not available",
                404,
            ) from exc
        if selected.reviewed_html != job.reviewed_html:
            raise ExtractionWorkspaceError(
                "HTML_CHANGED",
                "reviewed HTML no longer matches the completed extraction job",
                409,
            )
        self._selected[job.local_job_id] = selected
        return selected

    def _pages_for(self, job: LocalLexicalJob) -> tuple[int, ...]:
        cached = self._page_numbers.get(job.local_job_id)
        if cached is not None:
            return cached
        selected = self._selected_document(job)
        reader = open_reviewed_html(selected.html_path)
        numbers: list[int] = []
        try:
            for page in reader.iter_pages():
                numbers.append(page.page.page_number)
        except ReviewedHtmlReadError as exc:
            raise ExtractionWorkspaceError(
                "DOCUMENT_NOT_AVAILABLE",
                "reviewed HTML for this job is not available",
                404,
            ) from exc
        if not reader.completed:
            raise ExtractionWorkspaceError(
                "DOCUMENT_NOT_AVAILABLE",
                "reviewed HTML for this job is not available",
                404,
            )
        result = tuple(numbers)
        self._page_numbers[job.local_job_id] = result
        return result

    def _edit_command(
        self,
        edit: PageEdit,
        state: ExtractionReviewState,
        pages: tuple[int, ...],
    ) -> (
        AddFindingEdit
        | PatchFindingTextEdit
        | ReplaceFindingEdit
        | RemoveFindingEdit
        | RestoreFindingEdit
    ):
        if edit.page_number not in pages:
            raise ExtractionWorkspaceError("PAGE_NOT_FOUND", "reviewed page was not found", 404)
        if isinstance(edit, AddPageEdit):
            return AddFindingEdit(
                finding_id=edit.finding_id,
                component=edit.component,
                display_text=edit.display_text,
                page_assignment=AssignedPage(page_number=edit.page_number),
                evidence_status=FindingEvidenceStatus.NO_DOCUMENT_EVIDENCE,
            )
        finding = next(
            (item for item in state.findings if item.finding_id == edit.finding_id), None
        )
        if finding is None or finding.current is None:
            raise ExtractionWorkspaceError(
                "INVALID_REVIEW",
                "finding is not available on the selected page",
                422,
            )
        assigned = _assigned_page(finding.current.page_assignment)
        if assigned != edit.page_number:
            raise ExtractionWorkspaceError(
                "INVALID_REVIEW",
                "findings can be edited only on their assigned page",
                422,
            )
        if isinstance(edit, RestorePageEdit):
            if not finding.removed:
                raise ExtractionWorkspaceError(
                    "INVALID_REVIEW",
                    "finding is not a removed finding on the selected page",
                    422,
                )
            return RestoreFindingEdit(finding_id=edit.finding_id)
        if finding.removed:
            raise ExtractionWorkspaceError(
                "INVALID_REVIEW",
                "finding is not an active finding on the selected page",
                422,
            )
        if isinstance(edit, RemovePageEdit):
            return RemoveFindingEdit(finding_id=edit.finding_id, note=edit.note)
        if isinstance(edit, PatchPageEdit):
            return PatchFindingTextEdit(finding_id=edit.finding_id, display_text=edit.display_text)
        return ReplaceFindingEdit(
            finding_id=edit.finding_id,
            current=UserFacingFinding(
                component=edit.component,
                display_text=edit.display_text,
                page_assignment=finding.current.page_assignment,
                evidence_status=finding.current.evidence_status,
            ),
        )

    def _require_same_run(self, state: ExtractionReviewState, job: LocalLexicalJob) -> None:
        saved = state.binding.run.published_manifest
        if saved != job.published_manifest or state.job_id != job.job_id:
            raise ExtractionWorkspaceError(
                "REVIEW_RUN_MISMATCH",
                "a current extraction review already exists for another published run",
                409,
            )

    def _require_transition_state(
        self,
        outcome: TransitionOutcomeKind,
        state: ExtractionReviewState | None,
        message: str | None,
        action: str,
    ) -> ExtractionReviewState:
        if outcome is TransitionOutcomeKind.CONFLICT:
            raise ExtractionWorkspaceError(
                "REVIEW_CONFLICT",
                message or "expected revision does not match the saved extraction result",
                409,
            )
        if outcome is TransitionOutcomeKind.VALIDATION_ERROR:
            raise ExtractionWorkspaceError(
                "INVALID_REVIEW",
                _bounded(message or "extraction review edit was rejected"),
                422,
            )
        if state is None:
            raise ExtractionWorkspaceError(
                "INVALID_REVIEW",
                "extraction review did not return a current state",
                422,
            )
        if outcome is TransitionOutcomeKind.CHANGED:
            logger.info(
                "extraction_review_%s local_revision=%s approval=%s",
                action,
                state.current_revision_id,
                state.approval_state.value,
            )
        return state


def category_class(component: Component) -> str:
    return _CATEGORY_CLASS.get(component, "bl-hit--other")


_TXT_CATEGORY_HEADINGS: dict[Component, str] = {
    Component.MATERIALS: "Materials",
    Component.UNIT_OPERATIONS: "Unit Operations",
    Component.PROCESS_STEPS: "Process Steps",
    Component.EQUIPMENT: "Equipment",
    Component.PARAMETER_NAMES: "Parameters",
    Component.QUANTITY_EXPRESSIONS: "Quantities",
    Component.PARAMETER_VALUE_EXPRESSIONS: "Values",
    Component.UNITS: "Units",
}

_TXT_CATEGORY_ORDER: tuple[Component, ...] = (
    Component.MATERIALS,
    Component.UNIT_OPERATIONS,
    Component.PROCESS_STEPS,
    Component.EQUIPMENT,
    Component.PARAMETER_NAMES,
    Component.QUANTITY_EXPRESSIONS,
    Component.PARAMETER_VALUE_EXPRESSIONS,
    Component.UNITS,
)


def format_extraction_results_txt(state: ExtractionReviewState) -> str:
    """Group active saved findings by category for on-demand TXT download."""

    saved_order = {finding.finding_id: index for index, finding in enumerate(state.findings)}
    active = [
        finding for finding in state.findings if finding.is_active and finding.current is not None
    ]
    by_component: dict[Component, list[ReviewFindingRecord]] = {}
    for finding in active:
        assert finding.current is not None
        by_component.setdefault(finding.current.component, []).append(finding)

    sections: list[str] = []
    for component in _TXT_CATEGORY_ORDER:
        group = by_component.get(component)
        if not group:
            continue

        def _txt_sort_key(item: ReviewFindingRecord) -> tuple[int, int, int]:
            page = finding_page_number(item)
            index = saved_order[item.finding_id]
            if page is None:
                return (1, 0, index)
            return (0, page, index)

        group.sort(key=_txt_sort_key)
        lines = [_TXT_CATEGORY_HEADINGS[component]]
        for finding in group:
            assert finding.current is not None
            page = finding_page_number(finding)
            page_label = f"page {page}" if page is not None else "page unassigned"
            line = f"- {finding.current.display_text} ({page_label})"
            if finding.current.evidence_status is FindingEvidenceStatus.NO_DOCUMENT_EVIDENCE:
                line += " [no document evidence]"
            lines.append(line)
        sections.append("\n".join(lines))
    return "\n\n".join(sections) + ("\n" if sections else "")


def finding_page_number(finding: ReviewFindingRecord) -> int | None:
    if finding.current is not None:
        assigned = _assigned_page(finding.current.page_assignment)
        if assigned is not None:
            return assigned
    origin = finding.origin
    if isinstance(origin, LexicalFindingOrigin):
        return origin.evidence.page_number
    return None


def _is_reviewable(job: LocalLexicalJob) -> bool:
    return (
        job.status is LocalJobStatus.COMPLETED
        and job.reviewed_html is not None
        and job.run is not None
        and job.extraction is not None
        and job.publication is not None
        and job.published_manifest is not None
        and job.raw_run_relative_dir is not None
        and job.publication.status is PublicationStatus.COMPLETED
        and has_usable_completed_component(job.extraction)
    )


def _highlights_for_page(
    state: ExtractionReviewState,
    page_number: int,
) -> tuple[PageHighlight, ...]:
    highlights: list[PageHighlight] = []
    for finding in state.findings:
        if not finding.is_active or finding.current is None:
            continue
        if finding.current.evidence_status is not FindingEvidenceStatus.DOCUMENT_EVIDENCE:
            continue
        origin = finding.origin
        if not isinstance(origin, LexicalFindingOrigin):
            continue
        evidence = origin.evidence
        if (
            evidence.page_number != page_number
            or evidence.block_node_id is None
            or evidence.location is None
        ):
            continue
        highlights.append(
            PageHighlight(
                finding_id=finding.finding_id,
                node_id=evidence.block_node_id,
                start_char=evidence.location.start_char,
                end_char=evidence.location.end_char,
                category_class=category_class(finding.current.component),
            )
        )
    return tuple(highlights)


def _findings_from_block(
    block_order: int,
    page_number: int,
    node_id: str,
    occurrences: tuple[LexicalOccurrence, ...],
) -> Iterator[tuple[ReviewFindingRecord, tuple[int, int, int, int, str, str]]]:
    for occurrence in occurrences:
        if isinstance(occurrence, DictionaryOccurrence):
            yield from _dictionary_findings(block_order, page_number, node_id, occurrence)
        elif isinstance(occurrence, UnitOccurrence):
            finding = _lexical_finding(
                component=Component.UNITS,
                occurrence_kind="unit",
                occurrence_id=occurrence.occurrence_id,
                page_number=page_number,
                node_id=node_id,
                start_char=occurrence.mention.span.start_char,
                end_char=occurrence.mention.span.end_char,
                matched_text=occurrence.mention.span.matched_text,
            )
            yield (
                finding,
                _sort_key(
                    block_order, page_number, finding, Component.UNITS, occurrence.occurrence_id
                ),
            )
        else:
            for component in occurrence.applies_to:
                span = occurrence.expression.span
                finding = _lexical_finding(
                    component=component,
                    occurrence_kind="value",
                    occurrence_id=occurrence.occurrence_id,
                    page_number=page_number,
                    node_id=node_id,
                    start_char=span.start_char,
                    end_char=span.end_char,
                    matched_text=span.matched_text,
                )
                yield (
                    finding,
                    _sort_key(
                        block_order, page_number, finding, component, occurrence.occurrence_id
                    ),
                )


def _dictionary_findings(
    block_order: int,
    page_number: int,
    node_id: str,
    occurrence: DictionaryOccurrence,
) -> Iterator[tuple[ReviewFindingRecord, tuple[int, int, int, int, str, str]]]:
    # Catalogue/candidate refs stay in published L13 artifacts only. The Stage 3
    # current review stores source text/evidence for display and edits; copying
    # every candidate would hit U1 MAX_CANDIDATE_REFS_PER_FINDING on real runs.
    for component in occurrence.applies_to:
        finding = _lexical_finding(
            component=component,
            occurrence_kind="dictionary",
            occurrence_id=occurrence.occurrence_id,
            page_number=page_number,
            node_id=node_id,
            start_char=occurrence.location.start_char,
            end_char=occurrence.location.end_char,
            matched_text=occurrence.location.matched_text,
        )
        yield (
            finding,
            _sort_key(block_order, page_number, finding, component, occurrence.occurrence_id),
        )


def _lexical_finding(
    *,
    component: Component,
    occurrence_kind: Literal["dictionary", "unit", "value"],
    occurrence_id: str,
    page_number: int,
    node_id: str,
    start_char: int,
    end_char: int,
    matched_text: str,
) -> ReviewFindingRecord:
    location = CharSpan(start_char=start_char, end_char=end_char, matched_text=matched_text)
    return ReviewFindingRecord(
        finding_id=_finding_id(
            component,
            occurrence_kind,
            occurrence_id,
            page_number,
            node_id,
            start_char,
            end_char,
        ),
        origin=LexicalFindingOrigin(
            evidence=OriginalLexicalEvidence(
                occurrence_id=occurrence_id,
                occurrence_kind=occurrence_kind,
                block_node_id=node_id,
                page_number=page_number,
                location=location,
                candidate_refs=(),
            ),
            original_matched_text=matched_text,
        ),
        current=UserFacingFinding(
            component=component,
            display_text=matched_text,
            page_assignment=AssignedPage(page_number=page_number),
            evidence_status=FindingEvidenceStatus.DOCUMENT_EVIDENCE,
        ),
    )


def _finding_id(
    component: Component,
    occurrence_kind: str,
    occurrence_id: str,
    page_number: int,
    node_id: str,
    start_char: int,
    end_char: int,
) -> str:
    material = "\n".join(
        (
            component.value,
            occurrence_kind,
            occurrence_id,
            str(page_number),
            node_id,
            str(start_char),
            str(end_char),
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _sort_key(
    block_order: int,
    page_number: int,
    finding: ReviewFindingRecord,
    component: Component,
    occurrence_id: str,
) -> tuple[int, int, int, int, str, str]:
    origin = finding.origin
    start = 0
    end = 0
    if isinstance(origin, LexicalFindingOrigin) and origin.evidence.location is not None:
        start = origin.evidence.location.start_char
        end = origin.evidence.location.end_char
    return (page_number, block_order, start, end, component.value, occurrence_id)


def _remember_finding(
    collected: dict[str, ReviewFindingRecord],
    order: list[tuple[tuple[int, int, int, int, str, str], str]],
    finding: ReviewFindingRecord,
    sort_key: tuple[int, int, int, int, str, str],
) -> None:
    existing = collected.get(finding.finding_id)
    if existing is None:
        collected[finding.finding_id] = finding
        order.append((sort_key, finding.finding_id))
        return
    if existing != finding:
        raise ExtractionWorkspaceError(
            "ARTIFACT_REJECTED",
            "the same lexical finding identity was published with different evidence",
            422,
        )


def _assigned_page(assignment: PageAssignment) -> int | None:
    if isinstance(assignment, AssignedPage):
        return assignment.page_number
    return None


def _resolve_raw_run(data_dir: Path, relative: str) -> Path:
    if not relative or relative in {".", ".."} or "/" in relative or "\\" in relative:
        raise ExtractionWorkspaceError(
            "ARTIFACT_REJECTED", "published raw run path is not allowed", 422
        )
    root = (data_dir / RAW_RUNS_DIR_NAME).resolve()
    candidate = (root / relative).resolve()
    if candidate.parent != root or not candidate.is_dir():
        raise ExtractionWorkspaceError("ARTIFACT_REJECTED", "published raw run was not found", 422)
    return candidate


def _artifact_file(run_dir: Path, relative: str) -> Path:
    parts = Path(relative).parts
    if not relative or relative.startswith(("/", "\\")) or ".." in parts:
        raise ExtractionWorkspaceError(
            "ARTIFACT_REJECTED", "published artifact path is not allowed", 422
        )
    path = (run_dir / relative).resolve()
    if not path.is_relative_to(run_dir.resolve()) or not path.is_file():
        raise ExtractionWorkspaceError("ARTIFACT_REJECTED", "published artifact was not found", 422)
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_revision_id() -> str:
    return str(uuid.uuid4())


def _bounded(message: str) -> str:
    text = " ".join(message.split())
    if len(text) <= 200:
        return text
    return text[:197] + "..."


def _safe_message(exc: ValueError, fallback: str) -> str:
    text = _bounded(str(exc))
    if "/" in text or "\\" in text:
        return fallback
    return text or fallback
