"""Stage 3 extraction-review current-state contract validation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.extraction_review.contracts import (
    MAX_FINDING_EDITS_PER_SAVE,
    MAX_FINDINGS_PER_REVIEW,
    AddedByUserProvenance,
    AddFindingEdit,
    ApproveExtractionResultCommand,
    AssignedPage,
    CatalogueCandidateReference,
    DocumentSourceReference,
    ExtractionResultApproval,
    ExtractionReviewAction,
    ExtractionReviewState,
    ExtractionRunReference,
    FindingEvidenceStatus,
    InitializeReviewCommand,
    LexicalFindingOrigin,
    OriginalLexicalEvidence,
    PatchFindingTextEdit,
    PublishedManifestReference,
    ReviewFindingRecord,
    SaveReviewEditsCommand,
    UnassignedPage,
    UserAddedFindingOrigin,
    UserFacingFinding,
    WorkspaceBinding,
    action_to_preset,
    fuzzy_extraction_default_enabled,
)
from app.lexical_extraction.contracts import (
    CharSpan,
    Component,
    ComponentResult,
    ExtractionOutcome,
    ExtractionOutcomeRecord,
    FinalManifestClaim,
    Preset,
    PublicationRecord,
    PublicationStatus,
    ReviewedHtmlV1Input,
    RunProvenance,
)

HTML_SHA = "4fc6da769f8ff764fa10b02f657e60c1838f1ed37ec807e49527c0ce4df5e544"
DOC_HASH = "a" * 64
MANIFEST_SHA = "9" * 64
REV_1 = "11111111-1111-4111-8111-111111111111"
REV_2 = "22222222-2222-4222-8222-222222222222"
NOW = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)


def reviewed_html(**overrides: object) -> ReviewedHtmlV1Input:
    data: dict[str, object] = {
        "html_sha256": HTML_SHA,
        "html_contract_version": 1,
        "job_id": "job-1",
        "review_revision_id": "rev-doc-1",
        "review_generation": 1,
        "conversion_status": "SUCCEEDED",
    }
    data.update(overrides)
    return ReviewedHtmlV1Input.model_validate(data)


def run_provenance(**overrides: object) -> RunProvenance:
    data: dict[str, object] = {
        "run_id": "run-1",
        "requested_presets": [Preset.MATERIALS.value],
        "requested_components": [Component.MATERIALS.value],
        "resolved_components": [Component.MATERIALS.value],
        "fuzzy_requested": False,
        "input_html_sha256": HTML_SHA,
        "knowledge": {
            "snapshot_id": "snap-1",
            "database_sha256": "5" * 64,
            "manifest_sha256": "6" * 64,
        },
        "configuration_sha256": "7" * 64,
        "rules_sha256": "8" * 64,
        "engine_version": "test",
    }
    data.update(overrides)
    return RunProvenance.model_validate(data)


def published_run(**run_overrides: object) -> ExtractionRunReference:
    return ExtractionRunReference(
        run=run_provenance(**run_overrides),
        publication=PublicationRecord(
            status=PublicationStatus.COMPLETED,
            final_manifest=FinalManifestClaim(manifest_id="manifest-1"),
        ),
        published_manifest=PublishedManifestReference(
            manifest_id="manifest-1",
            manifest_sha256=MANIFEST_SHA,
        ),
    )


def document_source(*, document_hash: str | None = DOC_HASH) -> DocumentSourceReference:
    return DocumentSourceReference(
        job_id="job-1",
        document_hash=document_hash,
        reviewed_html=reviewed_html(),
    )


def materials_extraction(*, match_count: int = 1) -> ExtractionOutcomeRecord:
    return ExtractionOutcomeRecord(
        overall=ExtractionOutcome.COMPLETED,
        components=(
            ComponentResult(
                component=Component.MATERIALS,
                outcome=ExtractionOutcome.COMPLETED,
                match_count=match_count,
            ),
        ),
    )


def span(text: str = "water") -> CharSpan:
    return CharSpan(start_char=0, end_char=len(text), matched_text=text)


def lexical_finding(
    finding_id: str = "finding-1",
    text: str = "water",
    *,
    page_number: int | None = 1,
    with_span: bool = True,
) -> ReviewFindingRecord:
    if with_span:
        evidence = OriginalLexicalEvidence(
            occurrence_id=f"occ-{finding_id}",
            occurrence_kind="dictionary",
            block_node_id="node-1",
            page_number=page_number,
            location=span(text),
            candidate_refs=(
                CatalogueCandidateReference(
                    candidate_kind="fda_ema_material",
                    snapshot_id="snap-1",
                    row_id="row-1",
                    matched_term=text,
                ),
            ),
        )
        evidence_status = FindingEvidenceStatus.DOCUMENT_EVIDENCE
        page_assignment: AssignedPage | UnassignedPage = (
            AssignedPage(page_number=page_number) if page_number is not None else UnassignedPage()
        )
    else:
        evidence = OriginalLexicalEvidence(
            occurrence_id=f"occ-{finding_id}",
            occurrence_kind="dictionary",
            block_node_id=None,
            page_number=page_number,
            location=None,
            candidate_refs=(),
        )
        evidence_status = FindingEvidenceStatus.NO_DOCUMENT_EVIDENCE
        page_assignment = (
            AssignedPage(page_number=page_number) if page_number is not None else UnassignedPage()
        )
    return ReviewFindingRecord(
        finding_id=finding_id,
        origin=LexicalFindingOrigin(evidence=evidence, original_matched_text=text),
        current=UserFacingFinding(
            component=Component.MATERIALS,
            display_text=text,
            page_assignment=page_assignment,
            evidence_status=evidence_status,
        ),
    )


def binding(**overrides: object) -> WorkspaceBinding:
    data: dict[str, object] = {
        "document_source": document_source(),
        "run": published_run(),
        "extraction": materials_extraction(),
    }
    data.update(overrides)
    return WorkspaceBinding.model_validate(data)


def test_action_preset_mappings_and_fuzzy_default() -> None:
    assert (
        action_to_preset(ExtractionReviewAction.EXTRACT_UNIT_OPERATIONS)
        is Preset.UNIT_OPERATIONS_WITH_STEPS
    )
    assert (
        action_to_preset(ExtractionReviewAction.EXTRACT_MATERIALS)
        is Preset.MATERIALS_WITH_QUANTITIES
    )
    assert (
        action_to_preset(ExtractionReviewAction.EXTRACT_EQUIPMENT)
        is Preset.EQUIPMENT_WITH_PARAMETERS
    )
    assert action_to_preset(ExtractionReviewAction.EXTRACT_ALL) is Preset.FULL
    assert fuzzy_extraction_default_enabled() is False


def test_document_hash_optional_and_job_id_rules() -> None:
    html_only = document_source(document_hash=None)
    assert html_only.document_hash is None
    with pytest.raises(ValidationError, match="job_id must match"):
        DocumentSourceReference(
            job_id="other-job",
            document_hash=DOC_HASH,
            reviewed_html=reviewed_html(),
        )


def test_manifest_sha256_required() -> None:
    with pytest.raises(ValidationError):
        PublishedManifestReference.model_validate({"manifest_id": "manifest-1"})


def test_completed_run_requires_published_manifest() -> None:
    with pytest.raises(ValidationError, match="published_manifest"):
        ExtractionRunReference(
            run=run_provenance(),
            publication=PublicationRecord(
                status=PublicationStatus.COMPLETED,
                final_manifest=FinalManifestClaim(manifest_id="manifest-1"),
            ),
            published_manifest=None,
        )


def test_mismatched_manifest_id_rejected() -> None:
    with pytest.raises(ValidationError, match="published manifest id"):
        ExtractionRunReference(
            run=run_provenance(),
            publication=PublicationRecord(
                status=PublicationStatus.COMPLETED,
                final_manifest=FinalManifestClaim(manifest_id="manifest-1"),
            ),
            published_manifest=PublishedManifestReference(
                manifest_id="other",
                manifest_sha256=MANIFEST_SHA,
            ),
        )


def test_user_added_cannot_claim_document_evidence() -> None:
    with pytest.raises(ValidationError, match="user_added"):
        ReviewFindingRecord(
            finding_id="u1",
            origin=UserAddedFindingOrigin(),
            current=UserFacingFinding(
                component=Component.MATERIALS,
                display_text="x",
                page_assignment=UnassignedPage(),
                evidence_status=FindingEvidenceStatus.DOCUMENT_EVIDENCE,
            ),
            added_by_user=AddedByUserProvenance(actor="reviewer", at=NOW),
        )


def test_user_added_requires_added_by_user_provenance() -> None:
    with pytest.raises(ValidationError, match="added_by_user provenance"):
        ReviewFindingRecord(
            finding_id="u1",
            origin=UserAddedFindingOrigin(),
            current=UserFacingFinding(
                component=Component.MATERIALS,
                display_text="x",
                page_assignment=UnassignedPage(),
                evidence_status=FindingEvidenceStatus.NO_DOCUMENT_EVIDENCE,
            ),
        )


def test_lexical_document_evidence_requires_source_evidence() -> None:
    with pytest.raises(ValidationError, match="document_evidence requires"):
        ReviewFindingRecord(
            finding_id="f1",
            origin=LexicalFindingOrigin(
                evidence=OriginalLexicalEvidence(
                    occurrence_id="occ-1",
                    occurrence_kind="dictionary",
                    block_node_id=None,
                    page_number=1,
                    location=None,
                ),
                original_matched_text="water",
            ),
            current=UserFacingFinding(
                component=Component.MATERIALS,
                display_text="water",
                page_assignment=AssignedPage(page_number=1),
                evidence_status=FindingEvidenceStatus.DOCUMENT_EVIDENCE,
            ),
        )


def test_lexical_original_matched_text_must_agree_with_span() -> None:
    with pytest.raises(ValidationError, match="original_matched_text must match"):
        LexicalFindingOrigin(
            evidence=OriginalLexicalEvidence(
                occurrence_id="occ-1",
                occurrence_kind="dictionary",
                block_node_id="node-1",
                page_number=1,
                location=span("water"),
            ),
            original_matched_text="ethanol",
        )


def test_no_document_evidence_allows_assigned_or_unassigned_page() -> None:
    assigned = lexical_finding("a", "page-only", page_number=2, with_span=False)
    unassigned = lexical_finding("b", "none", page_number=None, with_span=False)
    assert assigned.current is not None
    assert assigned.current.evidence_status is FindingEvidenceStatus.NO_DOCUMENT_EVIDENCE
    assert assigned.current.page_assignment == AssignedPage(page_number=2)
    assert unassigned.current is not None
    assert unassigned.current.page_assignment == UnassignedPage()


def test_save_batch_duplicate_finding_ids_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate finding_id"):
        SaveReviewEditsCommand(
            expected_revision_id=REV_1,
            actor="reviewer",
            at=NOW,
            edits=(
                PatchFindingTextEdit(finding_id="f1", display_text="a"),
                PatchFindingTextEdit(finding_id="f1", display_text="b"),
            ),
        )


def test_bounded_save_batch_limit() -> None:
    edits = tuple(
        PatchFindingTextEdit(finding_id=f"f-{index}", display_text=f"t-{index}")
        for index in range(MAX_FINDING_EDITS_PER_SAVE)
    )
    SaveReviewEditsCommand(
        expected_revision_id=REV_1,
        actor="reviewer",
        at=NOW,
        edits=edits,
    )
    too_many = edits + (PatchFindingTextEdit(finding_id="extra", display_text="x"),)
    with pytest.raises(ValidationError):
        SaveReviewEditsCommand(
            expected_revision_id=REV_1,
            actor="reviewer",
            at=NOW,
            edits=too_many,
        )


def test_approve_command_has_no_draft_edit_payload() -> None:
    command = ApproveExtractionResultCommand(
        expected_revision_id=REV_1,
        actor="approver",
        at=NOW,
        target_revision_id=REV_1,
    )
    assert "edits" not in ApproveExtractionResultCommand.model_fields
    assert command.target_revision_id == REV_1


def test_state_holds_complete_findings_and_rejects_duplicate_ids() -> None:
    findings = (lexical_finding("f1"), lexical_finding("f2", "ethanol"))
    state = ExtractionReviewState(
        binding=binding(),
        current_revision_id=REV_1,
        findings=findings,
        approval=None,
    )
    assert len(state.findings) == 2
    with pytest.raises(ValidationError, match="finding_id values must be unique"):
        ExtractionReviewState(
            binding=binding(),
            current_revision_id=REV_1,
            findings=(lexical_finding("f1"), lexical_finding("f1", "dup")),
        )


def test_approval_must_name_current_revision() -> None:
    with pytest.raises(ValidationError, match="approval must name the current"):
        ExtractionReviewState(
            binding=binding(),
            current_revision_id=REV_1,
            findings=(lexical_finding(),),
            approval=ExtractionResultApproval(
                actor="approver",
                at=NOW,
                approved_revision_id=REV_2,
            ),
        )


def test_initialize_command_accepts_complete_finding_list() -> None:
    command = InitializeReviewCommand(
        revision_id=REV_1,
        actor="system",
        created_at=NOW,
        document_source=document_source(),
        run=published_run(),
        extraction=materials_extraction(),
        findings=(lexical_finding(),),
    )
    assert len(command.findings) == 1
    assert "findings" in InitializeReviewCommand.model_fields


def test_one_thousand_findings_are_valid() -> None:
    findings = tuple(lexical_finding(f"f-{index}", f"m-{index}") for index in range(1_000))
    assert len(findings) == 1_000
    assert len(findings) <= MAX_FINDINGS_PER_REVIEW
    state = ExtractionReviewState(
        binding=binding(),
        current_revision_id=REV_1,
        findings=findings,
    )
    assert len(state.findings) == 1_000


def test_add_command_requires_explicit_evidence_status() -> None:
    with pytest.raises(ValidationError):
        AddFindingEdit.model_validate(
            {
                "finding_id": "u1",
                "component": Component.MATERIALS.value,
                "display_text": "note",
                "page_assignment": {"kind": "unassigned"},
            }
        )


def test_contradictory_html_run_binding_rejected() -> None:
    with pytest.raises(ValidationError, match="reviewed HTML sha256"):
        WorkspaceBinding(
            document_source=document_source(),
            run=published_run(input_html_sha256="b" * 64),
            extraction=materials_extraction(),
        )


def test_history_oriented_models_are_absent() -> None:
    import app.extraction_review.contracts as contracts

    for name in (
        "ExtractionReviewRevision",
        "ExtractionReviewHead",
        "ReviewTransitionContext",
        "InitializeRevisionBody",
        "ContentSaveRevisionBody",
        "FindingChangeDelta",
        "AddedFindingChange",
        "parent_revision_id",
        "SaveOperationRecord",
        "RevisionKind",
    ):
        assert not hasattr(contracts, name)
