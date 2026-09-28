"""Strict execution-configuration loading and fixed preset resolution for lexical extraction.

This module loads YAML into a deterministic effective configuration and resolves
presets to components. It does not read HTML, open SQLite, create directories,
normalize text, match terms, or publish artifacts.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated, Any, Literal, Self, TypeVar, cast

import yaml
from pydantic import Field, model_validator

from app.lexical_extraction.contracts import Component, LexicalModel, Preset

CONFIGURATION_SCHEMA_VERSION = 1

COMPONENT_ORDER: tuple[Component, ...] = (
    Component.UNIT_OPERATIONS,
    Component.PROCESS_STEPS,
    Component.MATERIALS,
    Component.EQUIPMENT,
    Component.PARAMETER_NAMES,
    Component.UNITS,
    Component.QUANTITY_EXPRESSIONS,
    Component.PARAMETER_VALUE_EXPRESSIONS,
)

PRESET_COMPONENTS: dict[Preset, tuple[Component, ...]] = {
    Preset.UNIT_OPERATIONS: (Component.UNIT_OPERATIONS,),
    Preset.UNIT_OPERATIONS_WITH_STEPS: (
        Component.UNIT_OPERATIONS,
        Component.PROCESS_STEPS,
    ),
    Preset.MATERIALS: (Component.MATERIALS,),
    Preset.MATERIALS_WITH_QUANTITIES: (
        Component.MATERIALS,
        Component.QUANTITY_EXPRESSIONS,
        Component.UNITS,
    ),
    Preset.EQUIPMENT: (Component.EQUIPMENT,),
    Preset.EQUIPMENT_WITH_PARAMETERS: (
        Component.EQUIPMENT,
        Component.PARAMETER_NAMES,
        Component.PARAMETER_VALUE_EXPRESSIONS,
        Component.UNITS,
    ),
    Preset.FULL: COMPONENT_ORDER,
}

DEFAULT_SQLITE_READ_BATCH_ROWS = 5_000
DEFAULT_SQLITE_CACHE_KIB = 65_536
DEFAULT_MAX_TERMS_PER_SHARD = 2_000_000
DEFAULT_MAX_TERM_CODEPOINTS_PER_SHARD = 50_000_000
DEFAULT_RESULT_BUFFER_RECORDS = 50_000

MAX_SQLITE_READ_BATCH_ROWS = 100_000
MAX_SQLITE_CACHE_KIB = 1_048_576
MAX_MAX_TERMS_PER_SHARD = 10_000_000
MAX_MAX_TERM_CODEPOINTS_PER_SHARD = 500_000_000
MAX_RESULT_BUFFER_RECORDS = 1_000_000

_ALLOWED_YAML_TAGS = frozenset(
    {
        "tag:yaml.org,2002:null",
        "tag:yaml.org,2002:bool",
        "tag:yaml.org,2002:int",
        "tag:yaml.org,2002:float",
        "tag:yaml.org,2002:str",
        "tag:yaml.org,2002:seq",
        "tag:yaml.org,2002:map",
    }
)

_EnumT = TypeVar("_EnumT", Preset, Component)


class ConfigurationError(ValueError):
    """Invalid YAML, selection, path, or resource configuration."""


class InputPaths(LexicalModel):
    reviewed_html_path: Path


class KnowledgePaths(LexicalModel):
    snapshot_directory: Path


class OutputPaths(LexicalModel):
    directory: Path


class ExtractionRequest(LexicalModel):
    """Requested selection as supplied after overrides.

    List order is preserved for caller visibility. It is not part of the
    operational digest; ``resolved_components`` and the digest use canonical
    order and sorted request sets.
    """

    presets: tuple[Preset, ...] = ()
    components: tuple[Component, ...] = ()
    fuzzy_enabled: Annotated[bool, Field(strict=True)] = False

    @model_validator(mode="after")
    def selection_is_valid(self) -> Self:
        if not self.presets and not self.components:
            raise ValueError("at least one preset or component is required")
        if len(set(self.presets)) != len(self.presets):
            raise ValueError("preset list contains a duplicate")
        if len(set(self.components)) != len(self.components):
            raise ValueError("component list contains a duplicate")
        return self


class ResourceLimits(LexicalModel):
    """Finite resource safeguards. Not a memory or performance guarantee."""

    sqlite_read_batch_rows: Annotated[
        int, Field(strict=True, ge=1, le=MAX_SQLITE_READ_BATCH_ROWS)
    ] = DEFAULT_SQLITE_READ_BATCH_ROWS
    sqlite_cache_kib: Annotated[int, Field(strict=True, ge=1, le=MAX_SQLITE_CACHE_KIB)] = (
        DEFAULT_SQLITE_CACHE_KIB
    )
    max_terms_per_shard: Annotated[int, Field(strict=True, ge=1, le=MAX_MAX_TERMS_PER_SHARD)] = (
        DEFAULT_MAX_TERMS_PER_SHARD
    )
    max_term_codepoints_per_shard: Annotated[
        int, Field(strict=True, ge=1, le=MAX_MAX_TERM_CODEPOINTS_PER_SHARD)
    ] = DEFAULT_MAX_TERM_CODEPOINTS_PER_SHARD
    result_buffer_records: Annotated[
        int, Field(strict=True, ge=1, le=MAX_RESULT_BUFFER_RECORDS)
    ] = DEFAULT_RESULT_BUFFER_RECORDS


class SelectionOverride(LexicalModel):
    """Typed per-run replacement for YAML selection fields.

    Provided fields replace the YAML values entirely. Omitted fields keep YAML.
    Lists never append implicitly.
    """

    presets: tuple[Preset, ...] | None = None
    components: tuple[Component, ...] | None = None
    fuzzy_enabled: Annotated[bool, Field(strict=True)] | None = None


class EffectiveExecutionConfiguration(LexicalModel):
    """Validated effective configuration ready for a later runner.

    Requested preset/component lists retain caller order. ``resolved_components``
    is the deterministic union in ``COMPONENT_ORDER``. The configuration digest
    uses sorted request sets so list order does not change operational provenance.
    """

    schema_version: Literal[1] = CONFIGURATION_SCHEMA_VERSION
    input: InputPaths
    knowledge: KnowledgePaths
    output: OutputPaths
    extraction: ExtractionRequest
    resolved_components: tuple[Component, ...]
    resources: ResourceLimits

    @model_validator(mode="after")
    def resolved_matches_request(self) -> Self:
        expected = resolve_components(
            self.extraction.presets,
            self.extraction.components,
        )
        if self.resolved_components != expected:
            raise ValueError("resolved_components must equal the fixed preset union")
        return self


def resolve_components(
    presets: Sequence[Preset],
    components: Sequence[Component],
) -> tuple[Component, ...]:
    """Return the deterministic component union in canonical order.

    Performs no I/O. Overlapping preset and component requests are valid.
    ``with`` presets expand to co-executed components only; they do not encode
    associations or require child values.
    """

    selected: set[Component] = set()
    for preset in presets:
        selected.update(PRESET_COMPONENTS[preset])
    selected.update(components)
    return tuple(component for component in COMPONENT_ORDER if component in selected)


def effective_configuration_sha256(config: EffectiveExecutionConfiguration) -> str:
    """Lower-case SHA-256 of the effective operational configuration.

    Uses UTF-8 canonical JSON (``sort_keys=True``, compact separators,
    ``ensure_ascii=False``, ``allow_nan=False``). Requested preset/component
    lists are sorted for the digest so YAML selection order does not change
    provenance. Absolute paths, resolved components, fuzzy, and resources are
    included. Suitable for ``RunProvenance.configuration_sha256``.
    """

    return _canonical_sha256(_digest_material(config))


def load_execution_configuration(
    config_path: Path,
    overrides: SelectionOverride | None = None,
) -> EffectiveExecutionConfiguration:
    """Load strict YAML, apply overrides, resolve presets, and return absolutes.

    Paths are resolved against the configuration file's parent directory, never
    the process working directory. Referenced paths are not required to exist
    and are not created.
    """

    path = Path(config_path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigurationError(f"cannot read configuration file: {path}") from exc

    raw = _load_strict_yaml_mapping(text)
    return _build_effective_configuration(
        raw,
        base_dir=path.parent,
        overrides=overrides,
    )


def _build_effective_configuration(
    raw: Mapping[str, object],
    *,
    base_dir: Path,
    overrides: SelectionOverride | None,
) -> EffectiveExecutionConfiguration:
    try:
        schema_version = raw["schema_version"]
    except KeyError as exc:
        raise ConfigurationError("schema_version is required") from exc
    if type(schema_version) is not int or schema_version != CONFIGURATION_SCHEMA_VERSION:
        raise ConfigurationError("schema_version must be the strict integer 1")

    input_raw = _required_mapping(raw, "input")
    knowledge_raw = _required_mapping(raw, "knowledge")
    output_raw = _required_mapping(raw, "output")
    extraction_raw = _required_mapping(raw, "extraction")
    resources_raw = _required_mapping(raw, "resources")

    unexpected = set(raw) - {
        "schema_version",
        "input",
        "knowledge",
        "output",
        "extraction",
        "resources",
    }
    if unexpected:
        raise ConfigurationError(f"unknown configuration fields: {sorted(unexpected)}")

    reviewed_html = _resolve_declared_path(
        input_raw,
        section="input",
        field="reviewed_html_path",
        base_dir=base_dir,
    )
    snapshot_directory = _resolve_declared_path(
        knowledge_raw,
        section="knowledge",
        field="snapshot_directory",
        base_dir=base_dir,
    )
    output_directory = _resolve_declared_path(
        output_raw,
        section="output",
        field="directory",
        base_dir=base_dir,
    )

    presets, components, fuzzy_enabled = _parse_extraction(extraction_raw, overrides)
    resources = _parse_resources(resources_raw)
    resolved = resolve_components(presets, components)

    try:
        return EffectiveExecutionConfiguration(
            schema_version=CONFIGURATION_SCHEMA_VERSION,
            input=InputPaths(reviewed_html_path=reviewed_html),
            knowledge=KnowledgePaths(snapshot_directory=snapshot_directory),
            output=OutputPaths(directory=output_directory),
            extraction=ExtractionRequest(
                presets=presets,
                components=components,
                fuzzy_enabled=fuzzy_enabled,
            ),
            resolved_components=resolved,
            resources=resources,
        )
    except ConfigurationError:
        raise
    except Exception as exc:
        raise ConfigurationError(str(exc)) from exc


def _parse_extraction(
    raw: Mapping[str, object],
    overrides: SelectionOverride | None,
) -> tuple[tuple[Preset, ...], tuple[Component, ...], bool]:
    unexpected = set(raw) - {"presets", "components", "fuzzy_enabled"}
    if unexpected:
        raise ConfigurationError(f"unknown extraction fields: {sorted(unexpected)}")

    presets = _parse_enum_list(raw.get("presets", []), Preset, "presets")
    components = _parse_enum_list(raw.get("components", []), Component, "components")
    if "fuzzy_enabled" in raw:
        fuzzy_enabled = _parse_strict_bool(raw["fuzzy_enabled"], "fuzzy_enabled")
    else:
        fuzzy_enabled = False

    if overrides is not None:
        if overrides.presets is not None:
            presets = overrides.presets
        if overrides.components is not None:
            components = overrides.components
        if overrides.fuzzy_enabled is not None:
            fuzzy_enabled = overrides.fuzzy_enabled

    return presets, components, fuzzy_enabled


def _parse_resources(raw: Mapping[str, object]) -> ResourceLimits:
    unexpected = set(raw) - {
        "sqlite_read_batch_rows",
        "sqlite_cache_kib",
        "max_terms_per_shard",
        "max_term_codepoints_per_shard",
        "result_buffer_records",
    }
    if unexpected:
        raise ConfigurationError(f"unknown resources fields: {sorted(unexpected)}")
    payload: dict[str, object] = {
        "sqlite_read_batch_rows": raw.get(
            "sqlite_read_batch_rows",
            DEFAULT_SQLITE_READ_BATCH_ROWS,
        ),
        "sqlite_cache_kib": raw.get("sqlite_cache_kib", DEFAULT_SQLITE_CACHE_KIB),
        "max_terms_per_shard": raw.get(
            "max_terms_per_shard",
            DEFAULT_MAX_TERMS_PER_SHARD,
        ),
        "max_term_codepoints_per_shard": raw.get(
            "max_term_codepoints_per_shard",
            DEFAULT_MAX_TERM_CODEPOINTS_PER_SHARD,
        ),
        "result_buffer_records": raw.get(
            "result_buffer_records",
            DEFAULT_RESULT_BUFFER_RECORDS,
        ),
    }
    try:
        return ResourceLimits.model_validate(payload)
    except Exception as exc:
        raise ConfigurationError(str(exc)) from exc


def _parse_enum_list(
    value: object,
    enum_type: type[_EnumT],
    label: str,
) -> tuple[_EnumT, ...]:
    if not isinstance(value, list):
        raise ConfigurationError(f"{label} must be a list")
    items: list[_EnumT] = []
    raw_items = cast(list[object], value)
    for item in raw_items:
        if not isinstance(item, str):
            raise ConfigurationError(f"{label} entries must be strings")
        try:
            items.append(enum_type(item))
        except ValueError as exc:
            raise ConfigurationError(f"invalid {label} value: {item}") from exc
    return tuple(items)


def _parse_strict_bool(value: object, label: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ConfigurationError(f"{label} must be a strict boolean")


def _required_mapping(raw: Mapping[str, object], key: str) -> dict[str, object]:
    try:
        value = raw[key]
    except KeyError as exc:
        raise ConfigurationError(f"{key} is required") from exc
    return _string_key_mapping(value, key)


def _string_key_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ConfigurationError(f"{label} must be a mapping")
    raw = cast(dict[object, object], value)
    checked: dict[str, object] = {}
    for key, item in raw.items():
        if not isinstance(key, str):
            raise ConfigurationError(f"{label} keys must be strings")
        checked[key] = item
    return checked


def _resolve_declared_path(
    mapping: Mapping[str, object],
    *,
    section: str,
    field: str,
    base_dir: Path,
) -> Path:
    unexpected = set(mapping) - {field}
    if unexpected:
        raise ConfigurationError(f"unknown {section} fields: {sorted(unexpected)}")
    try:
        raw_value = mapping[field]
    except KeyError as exc:
        raise ConfigurationError(f"{section}.{field} is required") from exc
    if not isinstance(raw_value, str) or raw_value == "":
        raise ConfigurationError(f"{section}.{field} must be a nonempty string")
    candidate = Path(raw_value)
    if candidate.is_absolute():
        return candidate.resolve(strict=False)
    return (base_dir / candidate).resolve(strict=False)


def _digest_material(config: EffectiveExecutionConfiguration) -> dict[str, object]:
    return {
        "schema_version": config.schema_version,
        "input": {
            "reviewed_html_path": str(config.input.reviewed_html_path),
        },
        "knowledge": {
            "snapshot_directory": str(config.knowledge.snapshot_directory),
        },
        "output": {
            "directory": str(config.output.directory),
        },
        "extraction": {
            "presets": sorted(preset.value for preset in config.extraction.presets),
            "components": sorted(component.value for component in config.extraction.components),
            "fuzzy_enabled": config.extraction.fuzzy_enabled,
        },
        "resolved_components": [component.value for component in config.resolved_components],
        "resources": config.resources.model_dump(mode="json"),
    }


def _canonical_sha256(material: Mapping[str, object]) -> str:
    canonical = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_strict_yaml_mapping(text: str) -> dict[str, object]:
    try:
        documents = list(yaml.load_all(text, Loader=_StrictSafeLoader))
    except ConfigurationError:
        raise
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"invalid YAML: {exc}") from exc
    if len(documents) == 0:
        raise ConfigurationError("configuration document is empty")
    if len(documents) > 1:
        raise ConfigurationError("multiple YAML documents are not allowed")
    document = documents[0]
    if document is None:
        raise ConfigurationError("configuration document is empty")
    if not isinstance(document, dict):
        raise ConfigurationError("configuration root must be a mapping")
    return _string_key_mapping(cast(object, document), "configuration")


class _StrictSafeLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicates, merge keys, anchors, and unsafe tags."""

    def compose_node(self, parent: Any, index: Any) -> Any:
        # getattr avoids incomplete PyYAML stubs under strict pyright.
        check_event = getattr(self, "check_event")  # noqa: B009
        if check_event(yaml.AliasEvent):
            raise ConfigurationError("YAML anchors and aliases are not allowed")
        peek_event = getattr(self, "peek_event")  # noqa: B009
        event = peek_event()
        if getattr(event, "anchor", None) is not None:
            raise ConfigurationError("YAML anchors and aliases are not allowed")
        base_compose = getattr(yaml.SafeLoader, "compose_node")  # noqa: B009
        return base_compose(self, parent, index)

    def construct_object(self, node: Any, deep: bool = False) -> Any:
        tag = getattr(node, "tag", None)
        if not isinstance(tag, str) or tag not in _ALLOWED_YAML_TAGS:
            raise ConfigurationError(f"unsafe or unsupported YAML tag: {tag}")
        base_construct = getattr(yaml.SafeLoader, "construct_object")  # noqa: B009
        return base_construct(self, node, deep=deep)

    def construct_mapping(self, node: Any, deep: bool = False) -> dict[Any, Any]:
        mapping: dict[Any, Any] = {}
        pairs = cast(list[tuple[Any, Any]], getattr(node, "value", []))
        for key_node, value_node in pairs:
            if getattr(key_node, "tag", None) == "tag:yaml.org,2002:merge":
                raise ConfigurationError("YAML merge keys are not allowed")
            key = self.construct_object(key_node, deep=deep)
            if isinstance(key, str) and key == "<<":
                raise ConfigurationError("YAML merge keys are not allowed")
            if not isinstance(key, str):
                raise ConfigurationError("YAML mapping keys must be strings")
            if key in mapping:
                raise ConfigurationError(f"duplicate YAML key: {key}")
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping
