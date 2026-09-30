"""Fixed V1 source-field mapping from flat snapshot rows to eligible search terms.

Maps L04 ``SourceRow`` cells to compact, source-backed search-term records for
independently selected lexical components. This module does not match document
text, normalize comparison keys, parse values, aggregate occurrences, or build
L01 final candidates.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from app.lexical_extraction.contracts import (
    FUZZY_MIN_WORD_LENGTH,
    Component,
    SafeStructuredError,
)
from app.lexical_extraction.knowledge_snapshot import KnowledgeSnapshot, SourceRow

# Component → allowlisted tables that can contribute eligible terms.
COMPONENT_SOURCE_TABLES: Final[Mapping[Component, tuple[str, ...]]] = {
    Component.MATERIALS: ("materials_fda_ema", "materials_chebi"),
    Component.EQUIPMENT: ("equipment",),
    Component.PARAMETER_NAMES: ("equipment",),
    Component.UNITS: ("equipment",),
    Component.UNIT_OPERATIONS: ("unit_operations",),
    Component.PROCESS_STEPS: ("unit_operations",),
    Component.QUANTITY_EXPRESSIONS: (),
    Component.PARAMETER_VALUE_EXPRESSIONS: (),
}

_TABLE_SCAN_ORDER: Final[tuple[str, ...]] = (
    "materials_fda_ema",
    "materials_chebi",
    "equipment",
    "unit_operations",
)

_INDEX_TRUE: Final = "TRUE"
_CODE_PATTERN: Final = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_MAX_ERROR_MESSAGE: Final = 200
_ELLIPSIS: Final = "..."
_MIN_DICTIONARY_TERM_CODEPOINTS: Final = 3
_CONTEXT_REQUIRED_POLICY: Final = "context_required"

KNOWN_MATCH_POLICIES: Final[frozenset[str]] = frozenset(
    {
        "direct_candidate",
        "context_required",
        "step_cue_only",
        "support_only",
        "inspection_only",
    }
)
KNOWN_RECORD_TYPES: Final[frozenset[str]] = frozenset({"unit_operation", "generic_step_cue"})
_GENERIC_CUE_POLICIES: Final[frozenset[str]] = frozenset(
    {"step_cue_only", "support_only", "inspection_only"}
)
_DIRECT_UO_POLICIES: Final[frozenset[str]] = frozenset({"direct_candidate", "context_required"})

# Exact case-insensitive unavailable markers for code/identity cells only.
# Not applied to Materials names or aliases.
_UNAVAILABLE_IDENTITY_MARKERS: Final[frozenset[str]] = frozenset({"n/a", "na", "unknown", "none"})

# Natural-language roles that may carry a fuzzy hint when shape-eligible.
# Chemicals, UNII, units, and generic/support/inspection/context cues stay false.
_FUZZY_NATURAL_ROLES: Final[frozenset[str]] = frozenset(
    {
        "equipment_type",
        "parameter_name",
        "unit_operation",
        "process_step",
    }
)
_FUZZY_FORBIDDEN_POLICIES: Final[frozenset[str]] = frozenset(
    {
        "context_required",
        "step_cue_only",
        "support_only",
        "inspection_only",
    }
)

# Conservative Equipment.Unit eligibility: reject placeholders, alternatives,
# annotated footnotes, ranges, and multi-word prose. Slash compounds without
# surrounding spaces (for example ``mL/min``) remain eligible.
_UNIT_PLACEHOLDER_MARKERS: Final[tuple[str, ...]] = (
    "unknown",
    "not applicable",
    "n/a",
    "unverified",
    "indicative",
    "versus",
)
_UNIT_RANGE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\d+(?:[.,]\d+)?\s*[-–—]\s*\d+(?:[.,]\d+)?"
)
_UNIT_NUMERIC_ONLY_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[\d.,]+$")


class FieldMappingError(Exception):
    """Bounded field-mapping failure for unrecognized source semantics.

    ``code`` and ``message`` map to :class:`SafeStructuredError`. A failure is
    not a successful empty term list and does not invent policy meanings.
    """

    def __init__(self, code: str, message: str) -> None:
        if _CODE_PATTERN.fullmatch(code) is None or not 1 <= len(message) <= _MAX_ERROR_MESSAGE:
            raise ValueError("field-mapping error code or message is not bounded")
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")

    def to_structured_error(self) -> SafeStructuredError:
        return SafeStructuredError(code=self.code, message=self.message, retryable=False)


@dataclass(frozen=True)
class EligibleSearchTerm:
    """One source-backed eligible search expression for a later matcher.

    ``literal`` keeps the original eligible cell spelling. Optional identities
    that the source left blank or marked unavailable are ``None``. This is not
    an L01 candidate and carries no document span or match evidence.
    """

    literal: str
    component: Component
    term_role: str
    source_table: str
    source_field: str
    row_id: str
    lexical_term_id: str | None = None
    snapshot_id: str | None = None
    boundary_hint: str = "default"
    fuzzy_allowed: bool = False
    display_name: str | None = None
    unii: str | None = None
    sms_id: str | None = None
    chebi_id: str | None = None
    alias_type: str | None = None
    source: str | None = None
    source_version: str | None = None
    source_record: str | None = None
    equipment_type_id: str | None = None
    parameter_id: str | None = None
    catalogue_equipment_type_id: str | None = None
    catalogue_equipment_type_label: str | None = None
    source_section: str | None = None
    operation_id: str | None = None
    canonical_unit_operation: str | None = None
    unit_operation_en: str | None = None
    process_step_id: str | None = None
    index_this_row: str | None = None
    match_policy: str | None = None
    record_type: str | None = None
    term_relation: str | None = None
    operation_role: str | None = None
    provenance_source: str | None = None
    supporting_evidence: str | None = None


def tables_for_components(components: Sequence[Component]) -> tuple[str, ...]:
    """Return distinct source tables needed by ``components``, in scan order."""

    selected = frozenset(components)
    needed: set[str] = set()
    for component in selected:
        needed.update(COMPONENT_SOURCE_TABLES.get(component, ()))
    return tuple(table for table in _TABLE_SCAN_ORDER if table in needed)


def is_unavailable_identity_marker(value: str) -> bool:
    """Return whether ``value`` is an exact known unavailable code/ID marker.

    Comparison is case-insensitive after stripping surrounding whitespace.
    Markers: ``N/A``, ``NA``, ``unknown``, ``None``. This rule applies to code
    search and optional native ID attributes only, not to Materials names or
    aliases.
    """

    return value.strip().casefold() in _UNAVAILABLE_IDENTITY_MARKERS


def is_eligible_equipment_unit_spelling(cell: str) -> bool:
    """Return whether an Equipment ``Unit`` cell is an atomic unit spelling.

    Fixed V1 internal rule (not user configuration):

    - blank / whitespace-only cells are ineligible
    - placeholder or uncertainty prose is ineligible
    - alternatives (`` or ``, spaced `` / ``), semicolons, dash prose, footnote
      markers (``*``, bare ``¹``), embedded whitespace, pure numerics, and
      numeric ranges are ineligible
    - compact tokens, slash compounds without spaces, and mathematical
      reciprocal forms such as ``min⁻¹`` remain eligible; the original cell
      spelling is preserved when a term is emitted
    """

    if _is_blank(cell):
        return False
    lowered = cell.casefold()
    for marker in _UNIT_PLACEHOLDER_MARKERS:
        if marker in lowered:
            return False
    if " or " in lowered:
        return False
    if ";" in cell or " / " in cell or "—" in cell or "–" in cell:
        return False
    if "*" in cell:
        return False
    # Footnote ``¹`` is ineligible; mathematical reciprocal ``⁻¹`` remains eligible.
    if "¹" in cell and "⁻¹" not in cell:
        return False
    if any(character.isspace() for character in cell):
        return False
    if _UNIT_NUMERIC_ONLY_PATTERN.fullmatch(cell) is not None:
        return False
    if _UNIT_RANGE_PATTERN.search(cell) is not None:
        return False
    return True


def index_this_row_authorizes(value: str) -> bool:
    """Return whether ``Index this row`` authorizes the UO search expression.

    Only the exact source text ``TRUE`` authorizes. Exact ``FALSE`` and every
    other value, including blank and unknown flags, do not authorize. Unknown
    nonempty values are not treated as ``TRUE``.
    """

    return value == _INDEX_TRUE


def fuzzy_shape_eligible(literal: str) -> bool:
    """Return whether ``literal`` matches the fixed V1 single-word fuzzy shape.

    One alphabetic word of at least six Unicode code points, with no whitespace.
    This does not calculate edit distance.
    """

    if any(character.isspace() for character in literal) or not literal.isalpha():
        return False
    return len(literal) >= FUZZY_MIN_WORD_LENGTH


def map_source_row(
    row: SourceRow,
    *,
    components: Sequence[Component],
    snapshot_id: str | None = None,
) -> tuple[EligibleSearchTerm, ...]:
    """Map one flat source row to zero or more eligible search terms.

    Only roles required by ``components`` are produced. Distinct source rows and
    repeated spellings stay separate. No global vocabulary is accumulated.
    Unrecognized nonempty UO ``Match policy`` / ``record_type`` values raise
    :class:`FieldMappingError` instead of inventing candidate semantics.
    """

    selected = frozenset(components)
    if not selected:
        return ()
    values = dict(row.values)
    if row.table_name == "materials_fda_ema":
        if Component.MATERIALS not in selected:
            return ()
        return _map_materials_fda_ema(row, values, snapshot_id=snapshot_id)
    if row.table_name == "materials_chebi":
        if Component.MATERIALS not in selected:
            return ()
        return _map_materials_chebi(row, values, snapshot_id=snapshot_id)
    if row.table_name == "equipment":
        return _map_equipment(row, values, selected, snapshot_id=snapshot_id)
    if row.table_name == "unit_operations":
        return _map_unit_operations(row, values, selected, snapshot_id=snapshot_id)
    return ()


def iter_eligible_terms(
    snapshot: KnowledgeSnapshot,
    components: Sequence[Component],
    *,
    batch_size: int | None = None,
) -> Iterator[EligibleSearchTerm]:
    """Yield eligible terms row-by-row from tables needed by ``components``.

    Uses an already validated L04 handle. Scans only required tables. Does not
    build a global term list.
    """

    selected = tuple(components)
    if not selected:
        return
    identity = snapshot.identity.snapshot_id
    for table_name in tables_for_components(selected):
        for batch in snapshot.iter_batches(table_name, batch_size=batch_size):
            for row in batch.rows:
                yield from map_source_row(
                    row,
                    components=selected,
                    snapshot_id=identity,
                )


def _map_materials_fda_ema(
    row: SourceRow,
    values: Mapping[str, str],
    *,
    snapshot_id: str | None,
) -> tuple[EligibleSearchTerm, ...]:
    display = values.get("material_name", "")
    unii = _optional_native_id(values.get("UNII", ""))
    sms_id = _optional_native_id(values.get("SMS_ID", ""))
    alias_type = _optional_text(values.get("alias_type", ""))
    source = _optional_text(values.get("source", ""))
    lexical_term_id = _optional_text(values.get("lexical_term_id", ""))
    terms: list[EligibleSearchTerm] = []

    material_name = values.get("material_name", "")
    if not _is_blank(material_name) and _may_emit_dictionary_term(material_name):
        terms.append(
            EligibleSearchTerm(
                literal=material_name,
                component=Component.MATERIALS,
                term_role="material_name",
                source_table=row.table_name,
                source_field="material_name",
                row_id=row.row_id,
                lexical_term_id=lexical_term_id,
                snapshot_id=snapshot_id,
                boundary_hint="default",
                fuzzy_allowed=False,
                display_name=_optional_text(display),
                unii=unii,
                sms_id=sms_id,
                alias_type=alias_type,
                source=source,
            )
        )

    alias_name = values.get("alias_name", "")
    if not _is_blank(alias_name) and _may_emit_dictionary_term(alias_name):
        terms.append(
            EligibleSearchTerm(
                literal=alias_name,
                component=Component.MATERIALS,
                term_role="material_alias",
                source_table=row.table_name,
                source_field="alias_name",
                row_id=row.row_id,
                lexical_term_id=lexical_term_id,
                snapshot_id=snapshot_id,
                boundary_hint="default",
                fuzzy_allowed=False,
                display_name=_optional_text(display),
                unii=unii,
                sms_id=sms_id,
                alias_type=alias_type,
                source=source,
            )
        )

    unii_cell = values.get("UNII", "")
    if _is_available_code_search_cell(unii_cell) and _may_emit_dictionary_term(unii_cell):
        terms.append(
            EligibleSearchTerm(
                literal=unii_cell,
                component=Component.MATERIALS,
                term_role="unii_code",
                source_table=row.table_name,
                source_field="UNII",
                row_id=row.row_id,
                lexical_term_id=lexical_term_id,
                snapshot_id=snapshot_id,
                boundary_hint="whole_code",
                fuzzy_allowed=False,
                display_name=_optional_text(display),
                unii=unii,
                sms_id=sms_id,
                alias_type=alias_type,
                source=source,
            )
        )
    return tuple(terms)


def _map_materials_chebi(
    row: SourceRow,
    values: Mapping[str, str],
    *,
    snapshot_id: str | None,
) -> tuple[EligibleSearchTerm, ...]:
    display = values.get("material_name", "")
    chebi_id = _optional_native_id(values.get("CHEBI_ID", ""))
    alias_type = _optional_text(values.get("alias_type", ""))
    source = _optional_text(values.get("source", ""))
    source_version = _optional_text(values.get("source_version", ""))
    source_record = _optional_text(values.get("source_record", ""))
    lexical_term_id = _optional_text(values.get("lexical_term_id", ""))
    terms: list[EligibleSearchTerm] = []

    material_name = values.get("material_name", "")
    if not _is_blank(material_name) and _may_emit_dictionary_term(material_name):
        terms.append(
            EligibleSearchTerm(
                literal=material_name,
                component=Component.MATERIALS,
                term_role="material_name",
                source_table=row.table_name,
                source_field="material_name",
                row_id=row.row_id,
                lexical_term_id=lexical_term_id,
                snapshot_id=snapshot_id,
                boundary_hint="default",
                fuzzy_allowed=False,
                display_name=_optional_text(display),
                chebi_id=chebi_id,
                alias_type=alias_type,
                source=source,
                source_version=source_version,
                source_record=source_record,
            )
        )

    alias_name = values.get("alias_name", "")
    if not _is_blank(alias_name) and _may_emit_dictionary_term(alias_name):
        terms.append(
            EligibleSearchTerm(
                literal=alias_name,
                component=Component.MATERIALS,
                term_role="material_alias",
                source_table=row.table_name,
                source_field="alias_name",
                row_id=row.row_id,
                lexical_term_id=lexical_term_id,
                snapshot_id=snapshot_id,
                boundary_hint="default",
                fuzzy_allowed=False,
                display_name=_optional_text(display),
                chebi_id=chebi_id,
                alias_type=alias_type,
                source=source,
                source_version=source_version,
                source_record=source_record,
            )
        )
    return tuple(terms)


def _map_equipment(
    row: SourceRow,
    values: Mapping[str, str],
    selected: frozenset[Component],
    *,
    snapshot_id: str | None,
) -> tuple[EligibleSearchTerm, ...]:
    source_section = _optional_text(values.get("Source / section", ""))
    equipment_type_id = _optional_text(values.get("equipment_type_id", ""))
    equipment_type_label = values.get("Equipment type (EN)", "")
    terms: list[EligibleSearchTerm] = []

    if Component.EQUIPMENT in selected:
        equipment_type = values.get("Equipment type (EN)", "")
        if not _is_blank(equipment_type) and _may_emit_dictionary_term(equipment_type):
            terms.append(
                EligibleSearchTerm(
                    literal=equipment_type,
                    component=Component.EQUIPMENT,
                    term_role="equipment_type",
                    source_table=row.table_name,
                    source_field="Equipment type (EN)",
                    row_id=row.row_id,
                    snapshot_id=snapshot_id,
                    boundary_hint="default",
                    fuzzy_allowed=_fuzzy_allowed_hint(equipment_type, "equipment_type"),
                    display_name=_optional_text(equipment_type),
                    equipment_type_id=equipment_type_id,
                    source_section=source_section,
                )
            )

    if Component.PARAMETER_NAMES in selected:
        parameter = values.get("Operating parameter (EN)", "")
        if not _is_blank(parameter) and _may_emit_dictionary_term(parameter):
            terms.append(
                EligibleSearchTerm(
                    literal=parameter,
                    component=Component.PARAMETER_NAMES,
                    term_role="parameter_name",
                    source_table=row.table_name,
                    source_field="Operating parameter (EN)",
                    row_id=row.row_id,
                    snapshot_id=snapshot_id,
                    boundary_hint="default",
                    fuzzy_allowed=_fuzzy_allowed_hint(parameter, "parameter_name"),
                    display_name=_optional_text(parameter),
                    parameter_id=_optional_text(values.get("parameter_id", "")),
                    catalogue_equipment_type_id=equipment_type_id,
                    catalogue_equipment_type_label=_optional_text(equipment_type_label),
                    source_section=source_section,
                )
            )

    if Component.UNITS in selected:
        unit_cell = values.get("Unit", "")
        if is_eligible_equipment_unit_spelling(unit_cell):
            terms.append(
                EligibleSearchTerm(
                    literal=unit_cell,
                    component=Component.UNITS,
                    term_role="unit_spelling",
                    source_table=row.table_name,
                    source_field="Unit",
                    row_id=row.row_id,
                    snapshot_id=snapshot_id,
                    boundary_hint="atomic_unit",
                    fuzzy_allowed=False,
                    display_name=None,
                    source_section=source_section,
                )
            )
    return tuple(terms)


def _map_unit_operations(
    row: SourceRow,
    values: Mapping[str, str],
    selected: frozenset[Component],
    *,
    snapshot_id: str | None,
) -> tuple[EligibleSearchTerm, ...]:
    index_flag = values.get("Index this row", "")
    match_policy = values.get("Match policy", "")
    record_type = values.get("record_type", "")
    term_relation = _optional_text(values.get("Term relation", ""))
    operation_role = _optional_text(values.get("Operation role", ""))
    lexical_term_id = _optional_text(values.get("lexical_term_id", ""))
    provenance = _optional_text(values.get("Provenance / source", ""))
    supporting = _optional_text(values.get("Source / supporting evidence", ""))
    operation_id = _optional_text(values.get("Operation ID", ""))
    process_step_id = _optional_text(values.get("process_step_id", ""))
    canonical = _optional_text(values.get("Canonical unit operation", ""))
    unit_operation_en = _optional_text(values.get("Unit operation (EN)", ""))
    policy_text = _optional_text(match_policy)
    record_text = _optional_text(record_type)
    index_text = index_flag if index_flag != "" else None
    terms: list[EligibleSearchTerm] = []

    if Component.UNIT_OPERATIONS in selected and index_this_row_authorizes(index_flag):
        search_term = values.get("Search term (EN)", "")
        if not _is_blank(search_term) and _may_emit_dictionary_term(
            search_term,
            match_policy=policy_text,
        ):
            term_role = _unit_operation_term_role(match_policy, record_type, row_id=row.row_id)
            terms.append(
                EligibleSearchTerm(
                    literal=search_term,
                    component=Component.UNIT_OPERATIONS,
                    term_role=term_role,
                    source_table=row.table_name,
                    source_field="Search term (EN)",
                    row_id=row.row_id,
                    lexical_term_id=lexical_term_id,
                    snapshot_id=snapshot_id,
                    boundary_hint="default",
                    fuzzy_allowed=_fuzzy_allowed_hint(
                        search_term,
                        term_role,
                        match_policy=match_policy,
                    ),
                    display_name=canonical or unit_operation_en,
                    operation_id=(operation_id if term_role == "unit_operation" else None),
                    canonical_unit_operation=canonical,
                    unit_operation_en=unit_operation_en,
                    index_this_row=index_text,
                    match_policy=policy_text,
                    record_type=record_text,
                    term_relation=term_relation,
                    operation_role=operation_role,
                    provenance_source=provenance,
                )
            )

    if Component.PROCESS_STEPS in selected:
        step = values.get("Process step (EN)", "")
        if not _is_blank(step) and _may_emit_dictionary_term(step):
            terms.append(
                EligibleSearchTerm(
                    literal=step,
                    component=Component.PROCESS_STEPS,
                    term_role="process_step",
                    source_table=row.table_name,
                    source_field="Process step (EN)",
                    row_id=row.row_id,
                    lexical_term_id=lexical_term_id,
                    snapshot_id=snapshot_id,
                    boundary_hint="default",
                    fuzzy_allowed=_fuzzy_allowed_hint(
                        step, "process_step", match_policy=match_policy
                    ),
                    display_name=_optional_text(step),
                    process_step_id=process_step_id,
                    index_this_row=index_text,
                    match_policy=policy_text,
                    record_type=record_text,
                    term_relation=term_relation,
                    operation_role=operation_role,
                    provenance_source=provenance,
                    supporting_evidence=supporting,
                )
            )
    return tuple(terms)


def _unit_operation_term_role(match_policy: str, record_type: str, *, row_id: str) -> str:
    """Classify UO search terms without inventing unknown policy semantics."""

    if not _is_blank(match_policy) and match_policy not in KNOWN_MATCH_POLICIES:
        raise _uo_field_mapping_error(
            "UNKNOWN_MATCH_POLICY",
            "unrecognized Match policy on unit_operations row",
            row_id,
        )
    if not _is_blank(record_type) and record_type not in KNOWN_RECORD_TYPES:
        raise _uo_field_mapping_error(
            "UNKNOWN_RECORD_TYPE",
            "unrecognized record_type on unit_operations row",
            row_id,
        )
    if record_type == "generic_step_cue" or match_policy in _GENERIC_CUE_POLICIES:
        return "generic_cue"
    if match_policy in _DIRECT_UO_POLICIES:
        return "unit_operation"
    raise _uo_field_mapping_error(
        "AMBIGUOUS_UO_CLASSIFICATION",
        "UO search term lacks classifiable policy/record_type on row",
        row_id,
    )


def _uo_field_mapping_error(code: str, prefix: str, row_id: str) -> FieldMappingError:
    """Build a ``FieldMappingError`` with a bounded message and truncated row context.

    Source ``row_id`` is not limited or mutated; only the diagnostic text is clipped
    so ``SafeStructuredError.message`` stays within 200 characters.
    """

    return FieldMappingError(code, _bounded_message_with_row_id(prefix, row_id))


def _bounded_message_with_row_id(prefix: str, row_id: str) -> str:
    """Join ``prefix`` and a safely truncated ``row_id`` within the message bound."""

    separator = " "
    budget = _MAX_ERROR_MESSAGE - len(prefix) - len(separator)
    if budget < 1:
        return prefix[:_MAX_ERROR_MESSAGE]
    return f"{prefix}{separator}{_truncate_row_id_context(row_id, budget)}"


def _truncate_row_id_context(row_id: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(row_id) <= max_chars:
        return row_id
    if max_chars <= len(_ELLIPSIS):
        return _ELLIPSIS[:max_chars]
    return row_id[: max_chars - len(_ELLIPSIS)] + _ELLIPSIS


def _fuzzy_allowed_hint(
    literal: str,
    term_role: str,
    *,
    match_policy: str | None = None,
) -> bool:
    """Internal fuzzy hint from fixed V1 role and single-word shape only."""

    if term_role not in _FUZZY_NATURAL_ROLES:
        return False
    if match_policy is not None and match_policy in _FUZZY_FORBIDDEN_POLICIES:
        return False
    return fuzzy_shape_eligible(literal)


def _is_available_code_search_cell(value: str) -> bool:
    return not _is_blank(value) and not is_unavailable_identity_marker(value)


def _is_blank(value: str) -> bool:
    return value.strip() == ""


def _optional_text(value: str) -> str | None:
    if _is_blank(value):
        return None
    return value


def _optional_native_id(value: str) -> str | None:
    if _is_blank(value) or is_unavailable_identity_marker(value):
        return None
    return value


def _dictionary_literal_eligible(literal: str) -> bool:
    """Dictionary search terms require at least three Unicode code points."""

    return len(literal) >= _MIN_DICTIONARY_TERM_CODEPOINTS


def _may_emit_dictionary_term(
    literal: str,
    *,
    match_policy: str | None = None,
) -> bool:
    """Return whether a dictionary literal may enter lexical search.

    Short literals (under three code points) and explicitly ``context_required``
    unit-operation terms remain non-searchable. Alias type does not exclude a
    term from search; related-synonym aliases stay searchable.
    """

    if not _dictionary_literal_eligible(literal):
        return False
    if match_policy == _CONTEXT_REQUIRED_POLICY:
        return False
    return True


__all__ = [
    "COMPONENT_SOURCE_TABLES",
    "EligibleSearchTerm",
    "FieldMappingError",
    "KNOWN_MATCH_POLICIES",
    "KNOWN_RECORD_TYPES",
    "fuzzy_shape_eligible",
    "index_this_row_authorizes",
    "is_eligible_equipment_unit_spelling",
    "is_unavailable_identity_marker",
    "iter_eligible_terms",
    "map_source_row",
    "tables_for_components",
]
