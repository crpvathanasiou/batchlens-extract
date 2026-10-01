"""Evidence, candidate, value, and execution-outcome contracts for lexical extraction.

These models are validation boundaries. They do not read HTML, query the knowledge
snapshot, normalize text, parse values, calculate edit distance, resolve presets,
or publish files.

Ordering semantics for a later assembler, not applied here:

- pages: ``page.order``, then ``page.page_number``
- blocks: ``block.order``, then ``block.node_id``
- OCR references: ``ocr.order``, then ``ocr.block_id``
- occurrences: ``span.start_char``, then ``span.end_char``, then ``occurrence_id``

Different and overlapping spans are both valid. This module does not sort or dedupe.
A standalone character span checks its own offsets and code-point length. Slice
equality requires the block via ``validate_match_against_block``.
"""

from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Any, Literal, Self, cast

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    model_serializer,
    model_validator,
)

RECORD_SCHEMA_VERSION = "batchlens.lexical-record.v1"
HTML_CONTRACT_VERSION = 1
INTERNAL_RULES_VERSION = "lexical-internal-rules-v1"
EXACT_RULE_ID = "lexical-v1-exact"
NORMALIZED_EXACT_RULE_ID = "lexical-v1-normalized-exact"
FUZZY_RULE_ID = "lexical-v1-fuzzy"
UNIT_RULE_ID = "lexical-v1-unit"
VALUE_RULE_ID = "lexical-v1-value"
FUZZY_MAX_EDIT_DISTANCE = 1
FUZZY_MIN_WORD_LENGTH = 6
UNIT_VOCABULARY_ID = "lexical-unit-vocabulary-v1"
FLAT_SQLITE_USER_VERSION = 1
FLAT_SQLITE_PREPARATION_VERSION = "flat-sqlite-1"

_SHA256 = r"^[0-9a-f]{64}$"
_DICTIONARY_COMPONENTS = frozenset(
    {
        "unit_operations",
        "process_steps",
        "materials",
        "equipment",
        "parameter_names",
    }
)
_VALUE_COMPONENTS = frozenset({"quantity_expressions", "parameter_value_expressions"})
_ILLUSTRATIVE_KEYS = frozenset(
    {
        "schema_version",
        "run",
        "validated_input",
        "extraction",
        "publication",
        "pages",
    }
)


def _exact_version(value: int) -> int:
    if value != 1:
        raise ValueError("unsupported contract version")
    return value


def _finite_decimal_text(value: str) -> str:
    if any(character.isspace() for character in value):
        raise ValueError("decimal text must not contain whitespace")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("decimal text is not a finite decimal") from exc
    if not number.is_finite():
        raise ValueError("non-finite decimal values are rejected")
    return value


DecimalText = Annotated[str, Field(min_length=1), AfterValidator(_finite_decimal_text)]
StrictVersionOne = Annotated[int, Field(strict=True), AfterValidator(_exact_version)]
StrictNonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
StrictPositiveInt = Annotated[int, Field(strict=True, ge=1)]
Sha256Hex = Annotated[str, Field(pattern=_SHA256)]
NonEmptyText = Annotated[str, Field(min_length=1)]


class LexicalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Component(StrEnum):
    """Independently executable extraction components. Not presets."""

    UNIT_OPERATIONS = "unit_operations"
    PROCESS_STEPS = "process_steps"
    MATERIALS = "materials"
    EQUIPMENT = "equipment"
    PARAMETER_NAMES = "parameter_names"
    UNITS = "units"
    QUANTITY_EXPRESSIONS = "quantity_expressions"
    PARAMETER_VALUE_EXPRESSIONS = "parameter_value_expressions"


class Preset(StrEnum):
    """Named component selections. Expansion is not implemented in this module.

    ``unit_operations`` selects unit-operation mentions, including generic cues.
    ``unit_operations_with_steps`` adds process-step mentions.
    ``materials`` selects material mentions.
    ``materials_with_quantities`` adds quantity expressions and units.
    ``equipment`` selects catalogue equipment-type mentions.
    ``equipment_with_parameters`` adds parameter names, parameter-value expressions, and units.
    ``full`` is the union of those components.
    """

    UNIT_OPERATIONS = "unit_operations"
    UNIT_OPERATIONS_WITH_STEPS = "unit_operations_with_steps"
    MATERIALS = "materials"
    MATERIALS_WITH_QUANTITIES = "materials_with_quantities"
    EQUIPMENT = "equipment"
    EQUIPMENT_WITH_PARAMETERS = "equipment_with_parameters"
    FULL = "full"


class ExtractionOutcome(StrEnum):
    NOT_REQUESTED = "not_requested"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class PublicationStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class PageCoverage(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    NOT_COVERED = "not_covered"


class AmbiguityQualification(StrEnum):
    """Candidate qualification. This is not a technical execution failure."""

    NONE = "none"
    UNRESOLVED = "unresolved"
    CONTEXT_REQUIRED = "context_required"


class ConversionStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"


class CharSpan(LexicalModel):
    """Zero-based half-open Unicode code-point span.

    ``len(matched_text)`` counts code points, matching Python ``str`` indexing.
    Equality with a block is not decided here.
    """

    start_char: StrictNonNegativeInt
    end_char: StrictPositiveInt
    matched_text: NonEmptyText

    @model_validator(mode="after")
    def offsets_match_text(self) -> Self:
        if self.start_char >= self.end_char:
            raise ValueError("span offsets must be half-open and non-empty")
        if len(self.matched_text) != self.end_char - self.start_char:
            raise ValueError("matched_text length must equal the code-point span")
        return self


class CellGeometry(LexicalModel):
    row: StrictPositiveInt
    column: StrictPositiveInt
    row_span: StrictPositiveInt = 1
    column_span: StrictPositiveInt = 1


class OcrReference(LexicalModel):
    """One original OCR block id. Missing references are an empty tuple, not invented ids."""

    block_id: NonEmptyText
    order: StrictNonNegativeInt


class PageEvidence(LexicalModel):
    page_number: StrictPositiveInt
    order: StrictNonNegativeInt
    coverage: PageCoverage


class BlockEvidence(LexicalModel):
    """Original block text and identity. Text is stored exactly, including empty text."""

    node_id: NonEmptyText
    kind: NonEmptyText
    text: str
    page_number: StrictPositiveInt
    order: StrictNonNegativeInt
    element_id: NonEmptyText | None = None
    table_id: NonEmptyText | None = None
    cell_geometry: CellGeometry | None = None
    ocr_references: tuple[OcrReference, ...] = ()


def validate_match_against_block(span: CharSpan, block: BlockEvidence) -> None:
    """Require ``block.text[start:end] == matched_text`` using code-point offsets.

    Does not strip, collapse, or normalize ``block.text``.
    """

    if span.end_char > len(block.text):
        raise ValueError("span is outside the block text")
    if block.text[span.start_char : span.end_char] != span.matched_text:
        raise ValueError("span text does not equal the block slice")


class ReviewedHtmlV1Input(LexicalModel):
    """Validated reviewed-HTML v1 identity. All producer root fields are required."""

    html_sha256: Sha256Hex
    html_contract_version: StrictVersionOne
    job_id: NonEmptyText
    review_revision_id: NonEmptyText
    review_generation: StrictNonNegativeInt
    conversion_status: ConversionStatus
    external_document_id: NonEmptyText | None = None


class SafeStructuredError(LexicalModel):
    code: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")]
    message: Annotated[str, Field(min_length=1, max_length=200)]
    component: Component | None = None
    retryable: Annotated[bool, Field(strict=True)] = False


class PreValidationFailure(LexicalModel):
    """A failure before input validation. There is no validated-input record to fill."""

    outcome: Literal["pre_validation_failure"] = "pre_validation_failure"
    validated_input: None = None
    error: SafeStructuredError


class ExactEvidence(LexicalModel):
    method: Literal["exact"] = "exact"
    rule_id: Literal["lexical-v1-exact"] = EXACT_RULE_ID


class NormalizedExactEvidence(LexicalModel):
    method: Literal["normalized_exact"] = "normalized_exact"
    rule_id: Literal["lexical-v1-normalized-exact"] = NORMALIZED_EXACT_RULE_ID


class FuzzyEvidence(LexicalModel):
    """Recorded single-word fuzzy claim. The distance is stored, not calculated.

    V1 fuzzy evidence is one alphabetic word of at least six characters and a
    recorded edit distance of at most one. Phrases stay exact or normalized-exact.
    A valid record is not proof that a matcher measured that distance.
    """

    method: Literal["fuzzy"] = "fuzzy"
    rule_id: Literal["lexical-v1-fuzzy"] = FUZZY_RULE_ID
    dictionary_term: NonEmptyText
    edit_distance: Annotated[int, Field(strict=True, ge=0, le=FUZZY_MAX_EDIT_DISTANCE)]

    @model_validator(mode="after")
    def eligible_single_word(self) -> Self:
        term = self.dictionary_term
        if any(character.isspace() for character in term) or not term.isalpha():
            raise ValueError("fuzzy evidence is limited to one alphabetic word")
        if len(term) < FUZZY_MIN_WORD_LENGTH:
            raise ValueError("fuzzy evidence requires a word of at least six characters")
        return self


MatchEvidence = Annotated[
    ExactEvidence | NormalizedExactEvidence | FuzzyEvidence,
    Field(discriminator="method"),
]


def _reject_fuzzy(evidence: MatchEvidence, subject: str) -> None:
    if evidence.method == "fuzzy":
        raise ValueError(f"fuzzy evidence is not permitted for {subject}")


class _CandidateBase(LexicalModel):
    matched_term: NonEmptyText
    canonical_display_name: str | None = None
    ambiguity: AmbiguityQualification = AmbiguityQualification.NONE
    snapshot_id: NonEmptyText
    row_id: NonEmptyText
    supporting_row_ids: tuple[NonEmptyText, ...] = ()
    evidence: MatchEvidence

    @model_validator(mode="after")
    def supporting_row_ids_are_distinct(self) -> Self:
        if self.row_id in self.supporting_row_ids:
            raise ValueError("supporting_row_ids must not include the representative row_id")
        if len(set(self.supporting_row_ids)) != len(self.supporting_row_ids):
            raise ValueError("supporting_row_ids must not contain duplicates")
        return self


class FdaEmaMaterialCandidate(_CandidateBase):
    """FDA/EMA source row. UNII and SMS_ID are optional identities, not fabricated.

    Search fields are ``material_name``, ``alias_name``, and ``UNII`` only.
    """

    candidate_kind: Literal["fda_ema_material"] = "fda_ema_material"
    table: Literal["materials_fda_ema"] = "materials_fda_ema"
    source_field: Literal["material_name", "alias_name", "UNII"]
    unii: NonEmptyText | None = None
    sms_id: NonEmptyText | None = None
    alias_type: str | None = None
    lexical_term_id: NonEmptyText | None = None
    source: str | None = None

    @model_validator(mode="after")
    def chemicals_are_not_fuzzy(self) -> Self:
        _reject_fuzzy(self.evidence, "chemicals or UNII")
        return self


class ChebiMaterialCandidate(_CandidateBase):
    """ChEBI source row. Not merged with an FDA/EMA candidate by spelling or CAS.

    Search fields are ``material_name`` and ``alias_name`` only.
    """

    candidate_kind: Literal["chebi_material"] = "chebi_material"
    table: Literal["materials_chebi"] = "materials_chebi"
    source_field: Literal["material_name", "alias_name"]
    chebi_id: NonEmptyText | None = None
    alias_type: str | None = None
    lexical_term_id: NonEmptyText | None = None
    source: str | None = None
    source_version: str | None = None
    source_record: str | None = None

    @model_validator(mode="after")
    def chemicals_are_not_fuzzy(self) -> Self:
        _reject_fuzzy(self.evidence, "chemicals or chemical identifiers")
        return self


class EquipmentTypeCandidate(_CandidateBase):
    """Catalogue equipment type. Not an installed asset, brand, or model."""

    candidate_kind: Literal["equipment_type"] = "equipment_type"
    table: Literal["equipment"] = "equipment"
    source_field: Literal["Equipment type (EN)"] = "Equipment type (EN)"
    equipment_type_id: NonEmptyText | None = None
    source_section: str | None = None


class ParameterNameCandidate(_CandidateBase):
    """Parameter row. Catalogue equipment scope is not a detected equipment mention."""

    candidate_kind: Literal["parameter_name"] = "parameter_name"
    table: Literal["equipment"] = "equipment"
    source_field: Literal["Operating parameter (EN)"] = "Operating parameter (EN)"
    parameter_id: NonEmptyText | None = None
    catalogue_equipment_type_id: NonEmptyText | None = None
    catalogue_equipment_type_label: str | None = None
    source_section: str | None = None


class UnitOperationCandidate(_CandidateBase):
    """Unit-operation lexical row. ``index_this_row`` is original source text, not a bool."""

    candidate_kind: Literal["unit_operation"] = "unit_operation"
    table: Literal["unit_operations"] = "unit_operations"
    source_field: Literal["Search term (EN)"] = "Search term (EN)"
    operation_id: NonEmptyText | None = None
    canonical_unit_operation: str | None = None
    unit_operation_en: str | None = None
    index_this_row: str | None = None
    match_policy: str | None = None
    record_type: str | None = None
    term_relation: str | None = None
    operation_role: str | None = None
    lexical_term_id: NonEmptyText | None = None
    provenance_source: str | None = None


class GenericCueCandidate(_CandidateBase):
    """Generic cue. An operation id is not part of this record and must not be invented."""

    candidate_kind: Literal["generic_cue"] = "generic_cue"
    table: Literal["unit_operations"] = "unit_operations"
    source_field: Literal["Search term (EN)"] = "Search term (EN)"
    operation_role: str | None = None
    match_policy: str | None = None
    record_type: str | None = None
    term_relation: str | None = None
    lexical_term_id: NonEmptyText | None = None
    provenance_source: str | None = None


class ProcessStepCandidate(_CandidateBase):
    """Process-step label. ``Index this row`` does not gate this candidate."""

    candidate_kind: Literal["process_step"] = "process_step"
    table: Literal["unit_operations"] = "unit_operations"
    source_field: Literal["Process step (EN)"] = "Process step (EN)"
    process_step_id: NonEmptyText | None = None
    lexical_term_id: NonEmptyText | None = None
    provenance_source: str | None = None
    supporting_evidence: str | None = None
    match_policy: str | None = None
    record_type: str | None = None
    term_relation: str | None = None
    operation_role: str | None = None


LexicalCandidate = Annotated[
    FdaEmaMaterialCandidate
    | ChebiMaterialCandidate
    | EquipmentTypeCandidate
    | ParameterNameCandidate
    | UnitOperationCandidate
    | GenericCueCandidate
    | ProcessStepCandidate,
    Field(discriminator="candidate_kind"),
]

_CANDIDATE_COMPONENT = {
    "fda_ema_material": Component.MATERIALS,
    "chebi_material": Component.MATERIALS,
    "equipment_type": Component.EQUIPMENT,
    "parameter_name": Component.PARAMETER_NAMES,
    "unit_operation": Component.UNIT_OPERATIONS,
    "generic_cue": Component.UNIT_OPERATIONS,
    "process_step": Component.PROCESS_STEPS,
}


class FixedUnitVocabulary(LexicalModel):
    kind: Literal["fixed_vocabulary"] = "fixed_vocabulary"
    vocabulary_id: Literal["lexical-unit-vocabulary-v1"] = UNIT_VOCABULARY_ID


class EquipmentUnitRecord(LexicalModel):
    """Eligible ``equipment.Unit`` source cell. Not a parameter or equipment identity.

    When multiple denormalized equipment rows share the same unit spelling at one
    span, ``row_id`` is the representative and ``supporting_row_ids`` retains the
    remaining source references without multiplying the textual hit.
    """

    kind: Literal["equipment_unit_record"] = "equipment_unit_record"
    row_id: NonEmptyText
    supporting_row_ids: tuple[NonEmptyText, ...] = ()
    source_section: str | None = None

    @model_validator(mode="after")
    def supporting_row_ids_are_distinct(self) -> Self:
        if self.row_id in self.supporting_row_ids:
            raise ValueError("supporting_row_ids must not include the representative row_id")
        if len(set(self.supporting_row_ids)) != len(self.supporting_row_ids):
            raise ValueError("supporting_row_ids must not contain duplicates")
        return self


UnitProvenance = Annotated[
    FixedUnitVocabulary | EquipmentUnitRecord,
    Field(discriminator="kind"),
]


class UnitMention(LexicalModel):
    literal_text: NonEmptyText
    span: CharSpan
    rule_id: Literal["lexical-v1-unit"] = UNIT_RULE_ID
    controlled_spelling: str | None = None
    controlled_identity: str | None = None
    provenance: UnitProvenance | None = None
    evidence: MatchEvidence

    @model_validator(mode="after")
    def literal_matches_span(self) -> Self:
        _reject_fuzzy(self.evidence, "units")
        if self.span.matched_text != self.literal_text:
            raise ValueError("unit literal_text must equal its span text")
        return self


class ExactDecimal(LexicalModel):
    kind: Literal["exact_decimal"] = "exact_decimal"
    text: DecimalText


class AmbiguousNumber(LexicalModel):
    """An unresolved numeric token. No resolved decimal is stored or invented."""

    kind: Literal["ambiguous"] = "ambiguous"
    raw_token: NonEmptyText


NumberToken = Annotated[ExactDecimal | AmbiguousNumber, Field(discriminator="kind")]


class NumberUnitGroup(LexicalModel):
    """Syntactic grouping of a number and a unit span. Not an entity association."""

    number_span: CharSpan
    unit_span: CharSpan
    group_span: CharSpan


class _UnitBearing(LexicalModel):
    raw_expression: str
    span: CharSpan
    source_unit_spelling: str | None = None
    unit_span: CharSpan | None = None
    controlled_unit_spelling: str | None = None
    controlled_unit_identity: str | None = None
    number_unit_group: NumberUnitGroup | None = None

    @model_validator(mode="after")
    def expression_spans_agree(self) -> Self:
        _validate_unit_bearing(self)
        return self


class ScalarWithUnit(_UnitBearing):
    """A number with a unit. The unit span is syntactic evidence, not an entity link."""

    form: Literal["scalar_with_unit"] = "scalar_with_unit"
    number: NumberToken

    @model_validator(mode="after")
    def unit_is_present(self) -> Self:
        if not self.source_unit_spelling or self.unit_span is None:
            raise ValueError("a scalar with a unit requires unit spelling and a unit span")
        return self


class RangeValue(_UnitBearing):
    form: Literal["range"] = "range"
    low: NumberToken
    high: NumberToken


class ComparisonValue(_UnitBearing):
    form: Literal["comparison"] = "comparison"
    comparator: Literal["<", "<=", ">", ">=", "="]
    number: NumberToken


class SymmetricTolerance(_UnitBearing):
    form: Literal["symmetric_tolerance"] = "symmetric_tolerance"
    center: NumberToken
    tolerance: NumberToken


class CategoricalExpression(LexicalModel):
    form: Literal["categorical"] = "categorical"
    raw_expression: str
    span: CharSpan
    category_label: NonEmptyText

    @model_validator(mode="after")
    def expression_text_agrees(self) -> Self:
        _raw_expression_agrees(self.raw_expression, self.span)
        return self


class CuedUnitlessValue(LexicalModel):
    """An explicitly cued unitless value. No unit or parent entity is implied."""

    form: Literal["cued_unitless"] = "cued_unitless"
    raw_expression: str
    span: CharSpan
    cue: NonEmptyText
    number: NumberToken

    @model_validator(mode="after")
    def expression_text_agrees(self) -> Self:
        _raw_expression_agrees(self.raw_expression, self.span)
        return self


ValueExpression = Annotated[
    ScalarWithUnit
    | RangeValue
    | ComparisonValue
    | SymmetricTolerance
    | CategoricalExpression
    | CuedUnitlessValue,
    Field(discriminator="form"),
]


def value_expression_spans(expression: ValueExpression) -> tuple[CharSpan, ...]:
    spans: list[CharSpan] = [expression.span]
    unit_span = getattr(expression, "unit_span", None)
    if isinstance(unit_span, CharSpan):
        spans.append(unit_span)
    group = getattr(expression, "number_unit_group", None)
    if isinstance(group, NumberUnitGroup):
        spans.extend((group.number_span, group.unit_span, group.group_span))
    return tuple(spans)


class DictionaryOccurrence(LexicalModel):
    """A document span plus at least one source-backed catalogue candidate.

    Exact evidence asserts that the candidate term equals this span's original text.
    Normalized-exact evidence asserts a future fixed normalization; this record does
    not apply that normalization. Fuzzy evidence asserts a stored single-word distance,
    which this record does not calculate.
    """

    kind: Literal["dictionary"] = "dictionary"
    occurrence_id: NonEmptyText
    block_node_id: NonEmptyText
    location: CharSpan
    applies_to: tuple[Component, ...] = Field(min_length=1)
    candidates: tuple[LexicalCandidate, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def applicability(self) -> Self:
        _unique_components(self.applies_to)
        unknown = {component.value for component in self.applies_to} - _DICTIONARY_COMPONENTS
        if unknown:
            raise ValueError("dictionary occurrence applies only to dictionary components")
        literal = self.location.matched_text
        for candidate in self.candidates:
            required = _CANDIDATE_COMPONENT[candidate.candidate_kind]
            if required not in self.applies_to:
                raise ValueError("candidate role is not in the occurrence applicability")
            evidence = candidate.evidence
            if evidence.method == "exact" and candidate.matched_term != literal:
                raise ValueError("exact evidence requires the matched term to equal the span text")
            if evidence.method == "fuzzy" and evidence.dictionary_term != candidate.matched_term:
                raise ValueError("fuzzy dictionary term must equal the candidate matched term")
        return self


class UnitOccurrence(LexicalModel):
    kind: Literal["unit"] = "unit"
    occurrence_id: NonEmptyText
    block_node_id: NonEmptyText
    mention: UnitMention


class ValueRecognitionEvidence(LexicalModel):
    """Fixed V1 value-recognition rule. This is not a user-configurable parser."""

    rule_id: Literal["lexical-v1-value"] = VALUE_RULE_ID


class ValueOccurrence(LexicalModel):
    """A value expression with no material, equipment, or parameter parent."""

    kind: Literal["value"] = "value"
    occurrence_id: NonEmptyText
    block_node_id: NonEmptyText
    expression: ValueExpression
    recognition_rule: ValueRecognitionEvidence = Field(default_factory=ValueRecognitionEvidence)
    applies_to: tuple[Component, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def applicability(self) -> Self:
        _unique_components(self.applies_to)
        unknown = {component.value for component in self.applies_to} - _VALUE_COMPONENTS
        if unknown:
            raise ValueError(
                "value occurrence applies only to quantity or parameter-value components"
            )
        return self


LexicalOccurrence = Annotated[
    DictionaryOccurrence | UnitOccurrence | ValueOccurrence,
    Field(discriminator="kind"),
]


def occurrence_spans(occurrence: LexicalOccurrence) -> tuple[CharSpan, ...]:
    if isinstance(occurrence, DictionaryOccurrence):
        return (occurrence.location,)
    if isinstance(occurrence, UnitOccurrence):
        return (occurrence.mention.span,)
    return value_expression_spans(occurrence.expression)


class BlockRecord(LexicalModel):
    """One block and the occurrences validated against that block alone."""

    block: BlockEvidence
    occurrences: tuple[LexicalOccurrence, ...] = ()

    @model_validator(mode="after")
    def occurrences_agree_with_block(self) -> Self:
        for occurrence in self.occurrences:
            if occurrence.block_node_id != self.block.node_id:
                raise ValueError("occurrence block_node_id must match the block")
            for span in occurrence_spans(occurrence):
                validate_match_against_block(span, self.block)
        return self


class PageRecord(LexicalModel):
    """One page and its blocks. Not a whole-document tree."""

    page: PageEvidence
    blocks: tuple[BlockRecord, ...] = ()

    @model_validator(mode="after")
    def blocks_belong_to_page(self) -> Self:
        for record in self.blocks:
            if record.block.page_number != self.page.page_number:
                raise ValueError("block page_number must match the page")
        return self


class DependencyVersion(LexicalModel):
    name: NonEmptyText
    version: NonEmptyText


class ElapsedTiming(LexicalModel):
    name: NonEmptyText
    elapsed_ms: StrictNonNegativeInt


class AvailableMeasurement(LexicalModel):
    """A measurement that was actually taken. Omission means unavailable, not zero."""

    name: NonEmptyText
    value: DecimalText


class KnowledgeSnapshotIdentity(LexicalModel):
    snapshot_id: NonEmptyText
    database_sha256: Sha256Hex
    manifest_sha256: Sha256Hex
    schema_user_version: StrictVersionOne = FLAT_SQLITE_USER_VERSION
    preparation_version: Literal["flat-sqlite-1"] = FLAT_SQLITE_PREPARATION_VERSION


STAGE4_CLASSIFIER_POLICY_VERSION: Literal["batchlens.page-classification-policy.v1"] = (
    "batchlens.page-classification-policy.v1"
)


class Stage4PageRestrictionProvenance(LexicalModel):
    """Stage-4-only provenance when a lexical run scanned an explicit page allow-list.

    Records that Stage 2 scanned only the listed reviewed-HTML page numbers while
    retaining the original full HTML identity/hash. Omitted pages were not scanned
    and must not appear as synthetic extraction pages. Present only on restricted
    runs; unrestricted serialization must omit this object entirely.
    """

    selected_page_numbers: tuple[StrictPositiveInt, ...]
    classifier_policy_version: Literal["batchlens.page-classification-policy.v1"] = (
        STAGE4_CLASSIFIER_POLICY_VERSION
    )
    classification_snapshot_sha256: Sha256Hex

    @model_validator(mode="after")
    def selected_pages_are_strictly_increasing(self) -> Self:
        pages = self.selected_page_numbers
        if not pages:
            raise ValueError("selected_page_numbers must not be empty")
        if list(pages) != sorted(pages):
            raise ValueError("selected_page_numbers must be strictly increasing")
        if len(set(pages)) != len(pages):
            raise ValueError("selected_page_numbers must not contain duplicates")
        return self


class RunProvenance(LexicalModel):
    """Identities for one requested run. Preset names are not expanded here."""

    schema_version: Literal["batchlens.lexical-record.v1"] = RECORD_SCHEMA_VERSION
    run_id: NonEmptyText
    requested_presets: tuple[Preset, ...] = ()
    requested_components: tuple[Component, ...]
    resolved_components: tuple[Component, ...]
    fuzzy_requested: Annotated[bool, Field(strict=True)] = False
    input_html_sha256: Sha256Hex
    knowledge: KnowledgeSnapshotIdentity
    configuration_sha256: Sha256Hex
    rules_version: Literal["lexical-internal-rules-v1"] = INTERNAL_RULES_VERSION
    rules_sha256: Sha256Hex
    engine_version: NonEmptyText
    dependency_versions: tuple[DependencyVersion, ...] = ()
    timings: tuple[ElapsedTiming, ...] = ()
    measurements: tuple[AvailableMeasurement, ...] = ()
    stage4_page_restriction: Stage4PageRestrictionProvenance | None = None

    @model_validator(mode="after")
    def component_lists_are_unique(self) -> Self:
        if len(set(self.requested_presets)) != len(self.requested_presets):
            raise ValueError("preset list contains a duplicate")
        _unique_components(self.requested_components)
        _unique_components(self.resolved_components)
        return self

    @model_serializer(mode="wrap")
    def _omit_absent_stage4_restriction(
        self,
        serializer: Callable[[Any], Any],
    ) -> dict[str, Any]:
        payload = cast(dict[str, Any], serializer(self))
        if payload.get("stage4_page_restriction") is None:
            payload.pop("stage4_page_restriction", None)
        return payload


class ComponentResult(LexicalModel):
    component: Component
    outcome: ExtractionOutcome
    match_count: StrictNonNegativeInt | None = None
    blocks_considered: StrictNonNegativeInt | None = None
    error: SafeStructuredError | None = None

    @model_validator(mode="after")
    def outcome_measurements(self) -> Self:
        if self.outcome is ExtractionOutcome.NOT_REQUESTED:
            if (
                self.match_count is not None
                or self.blocks_considered is not None
                or self.error is not None
            ):
                raise ValueError("not_requested carries no measurements or errors")
        if self.outcome is ExtractionOutcome.COMPLETED:
            if self.match_count is None:
                raise ValueError("completed coverage includes an explicit match count")
            if self.error is not None:
                raise ValueError("completed coverage cannot carry a technical error")
        if self.outcome is ExtractionOutcome.PARTIAL and self.match_count is None:
            raise ValueError("partial coverage includes an explicit match count")
        if self.outcome is ExtractionOutcome.FAILED and self.error is None:
            raise ValueError("failed coverage requires a structured error")
        if self.error is not None and self.error.component not in (None, self.component):
            raise ValueError("error component must match the component result")
        return self


class ExtractionOutcomeRecord(LexicalModel):
    overall: ExtractionOutcome
    components: tuple[ComponentResult, ...]

    @model_validator(mode="after")
    def overall_agrees_with_components(self) -> Self:
        seen: set[Component] = set()
        for item in self.components:
            if item.component in seen:
                raise ValueError("duplicate component outcome")
            seen.add(item.component)
        requested = [
            item for item in self.components if item.outcome is not ExtractionOutcome.NOT_REQUESTED
        ]
        if not requested:
            if self.overall is not ExtractionOutcome.NOT_REQUESTED:
                raise ValueError("nothing requested is not_requested overall")
            return self
        if self.overall is ExtractionOutcome.NOT_REQUESTED:
            raise ValueError("requested work is not not_requested overall")
        statuses = {item.outcome for item in requested}
        if statuses == {ExtractionOutcome.COMPLETED}:
            if self.overall is not ExtractionOutcome.COMPLETED:
                raise ValueError("fully completed requested work is completed overall")
            return self
        usable = any(
            item.outcome in {ExtractionOutcome.COMPLETED, ExtractionOutcome.PARTIAL}
            for item in requested
        )
        if not usable:
            if self.overall is not ExtractionOutcome.FAILED:
                raise ValueError("entirely failed requested work is failed overall")
            return self
        if self.overall is not ExtractionOutcome.PARTIAL:
            raise ValueError("incomplete coverage with usable results is partial overall")
        return self


class FinalManifestClaim(LexicalModel):
    """Claims completed publication. It does not prove that files were written."""

    manifest_id: NonEmptyText
    publication_status: Literal["completed"] = "completed"


class PublicationRecord(LexicalModel):
    status: PublicationStatus
    final_manifest: FinalManifestClaim | None = None

    @model_validator(mode="after")
    def manifest_follows_publication(self) -> Self:
        if self.status is PublicationStatus.COMPLETED:
            if self.final_manifest is None:
                raise ValueError("completed publication requires a final manifest claim")
        elif self.final_manifest is not None:
            raise ValueError("failed or interrupted publication cannot claim a final manifest")
        return self


def _unique_components(components: tuple[Component, ...]) -> None:
    if len(set(components)) != len(components):
        raise ValueError("component list contains a duplicate")


def _raw_expression_agrees(raw_expression: str, span: CharSpan) -> None:
    if raw_expression != span.matched_text:
        raise ValueError("raw_expression must equal the expression span text")


def _span_inside(inner: CharSpan, outer: CharSpan) -> None:
    if inner.start_char < outer.start_char or inner.end_char > outer.end_char:
        raise ValueError("nested span is outside its enclosing span")
    start = inner.start_char - outer.start_char
    end = inner.end_char - outer.start_char
    if outer.matched_text[start:end] != inner.matched_text:
        raise ValueError("nested span text does not match the enclosing slice")


def _validate_unit_bearing(expression: _UnitBearing) -> None:
    _raw_expression_agrees(expression.raw_expression, expression.span)
    spelling = expression.source_unit_spelling
    unit_span = expression.unit_span
    if (spelling is None) != (unit_span is None):
        raise ValueError("source unit spelling and unit span must both be present or both absent")
    if spelling is not None and unit_span is not None and spelling != unit_span.matched_text:
        raise ValueError("source unit spelling must equal the unit span text")
    if unit_span is not None:
        _span_inside(unit_span, expression.span)
    group = expression.number_unit_group
    if group is None:
        return
    _span_inside(group.group_span, expression.span)
    _span_inside(group.number_span, group.group_span)
    _span_inside(group.unit_span, group.group_span)
    if unit_span is not None and group.unit_span != unit_span:
        raise ValueError("number-unit group unit span must agree with the expression unit span")
    if spelling is not None and group.unit_span.matched_text != spelling:
        raise ValueError("group unit text must equal the source unit spelling")


def validate_resolved_component_coverage(
    run: RunProvenance,
    extraction: ExtractionOutcomeRecord,
) -> None:
    """Require one executed outcome for each resolved component.

    Does not load pages, expand presets, or run extraction.
    """

    by_component = {item.component: item for item in extraction.components}
    resolved = set(run.resolved_components)
    for component in run.resolved_components:
        item = by_component.get(component)
        if item is None:
            raise ValueError("every resolved component needs exactly one outcome")
        if item.outcome is ExtractionOutcome.NOT_REQUESTED:
            raise ValueError("a resolved component cannot be not_requested")
    for item in extraction.components:
        executed = item.outcome is not ExtractionOutcome.NOT_REQUESTED
        if item.component not in resolved and executed:
            raise ValueError(
                "a component outside the resolved selection cannot claim executed work"
            )


def validate_illustrative_result(
    payload: Mapping[str, object],
) -> tuple[
    RunProvenance,
    ReviewedHtmlV1Input,
    ExtractionOutcomeRecord,
    PublicationRecord,
    tuple[PageRecord, ...],
]:
    """Validate a small fixture by reusable records, one page at a time.

    This is not a production container for every page, match, and candidate.
    """

    unexpected = set(payload) - _ILLUSTRATIVE_KEYS
    if unexpected:
        raise ValueError(f"unknown illustrative result fields: {sorted(unexpected)}")
    missing = _ILLUSTRATIVE_KEYS - set(payload)
    if missing:
        raise ValueError(f"missing illustrative result fields: {sorted(missing)}")
    if payload["schema_version"] != RECORD_SCHEMA_VERSION:
        raise ValueError("unsupported lexical record schema")
    run = RunProvenance.model_validate(_mapping(payload["run"], "run"))
    validated_input = ReviewedHtmlV1Input.model_validate(
        _mapping(payload["validated_input"], "validated_input")
    )
    extraction = ExtractionOutcomeRecord.model_validate(
        _mapping(payload["extraction"], "extraction")
    )
    publication = PublicationRecord.model_validate(_mapping(payload["publication"], "publication"))
    if run.input_html_sha256 != validated_input.html_sha256:
        raise ValueError("run HTML hash must equal the validated input hash")
    validate_resolved_component_coverage(run, extraction)
    raw_pages = payload["pages"]
    if not isinstance(raw_pages, list):
        raise ValueError("pages must be a list of page records")
    page_items = cast(list[object], raw_pages)
    pages = tuple(PageRecord.model_validate(_mapping(page, "page")) for page in page_items)
    return run, validated_input, extraction, publication, pages


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    raw = cast(dict[object, object], value)
    checked: dict[str, object] = {}
    for key, item in raw.items():
        if not isinstance(key, str):
            raise ValueError(f"{label} keys must be strings")
        checked[key] = item
    return checked
