"""Public lexical execution-configuration behavior."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.lexical_extraction.configuration import (
    COMPONENT_ORDER,
    DEFAULT_MAX_TERM_CODEPOINTS_PER_SHARD,
    DEFAULT_MAX_TERMS_PER_SHARD,
    DEFAULT_RESULT_BUFFER_RECORDS,
    DEFAULT_SQLITE_CACHE_KIB,
    DEFAULT_SQLITE_READ_BATCH_ROWS,
    MAX_SQLITE_READ_BATCH_ROWS,
    PRESET_COMPONENTS,
    ConfigurationError,
    EffectiveExecutionConfiguration,
    SelectionOverride,
    effective_configuration_sha256,
    load_execution_configuration,
    resolve_components,
)
from app.lexical_extraction.contracts import (
    Component,
    KnowledgeSnapshotIdentity,
    Preset,
    RunProvenance,
)

EXAMPLE_PATH = (
    Path(__file__).resolve().parents[2]
    / "examples"
    / "lexical_extraction"
    / "execution-config.example.yaml"
)
HTML_SHA = "4fc6da769f8ff764fa10b02f657e60c1838f1ed37ec807e49527c0ce4df5e544"
DB_SHA = "cd709652a4b4de5acf9ca8558a2423fb3e8ebf83e0fde5994cca47af922468f2"
MANIFEST_SHA = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
RULES_SHA = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def _write_config(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def _minimal_yaml(
    *,
    presets: str = "[materials_with_quantities]",
    components: str = "[]",
    fuzzy: str | None = "false",
    resources: str | None = "resources: {}",
    extra_root: str = "",
) -> str:
    fuzzy_line = "" if fuzzy is None else f"  fuzzy_enabled: {fuzzy}\n"
    resources_block = "resources: {}\n" if resources is None else f"{resources}\n"
    return (
        "schema_version: 1\n"
        "input:\n"
        "  reviewed_html_path: ./inputs/reviewed.html\n"
        "knowledge:\n"
        "  snapshot_directory: ./knowledge/flat-v1\n"
        "output:\n"
        "  directory: ./results\n"
        "extraction:\n"
        f"  presets: {presets}\n"
        f"  components: {components}\n"
        f"{fuzzy_line}"
        f"{resources_block}"
        f"{extra_root}"
    )


def test_checked_in_example_loads_with_defaults_digest_and_union() -> None:
    config = load_execution_configuration(EXAMPLE_PATH)
    assert config.schema_version == 1
    assert config.input.reviewed_html_path.is_absolute()
    assert config.knowledge.snapshot_directory.is_absolute()
    assert config.output.directory.is_absolute()
    assert (
        config.input.reviewed_html_path
        == (EXAMPLE_PATH.parent / "inputs" / "reviewed.html").resolve()
    )
    assert config.extraction.presets == (Preset.MATERIALS_WITH_QUANTITIES,)
    assert config.extraction.components == ()
    assert config.extraction.fuzzy_enabled is False
    assert config.resolved_components == (
        Component.MATERIALS,
        Component.UNITS,
        Component.QUANTITY_EXPRESSIONS,
    )
    assert config.resources.sqlite_read_batch_rows == DEFAULT_SQLITE_READ_BATCH_ROWS
    assert config.resources.sqlite_cache_kib == DEFAULT_SQLITE_CACHE_KIB
    assert config.resources.max_terms_per_shard == DEFAULT_MAX_TERMS_PER_SHARD
    assert config.resources.max_term_codepoints_per_shard == DEFAULT_MAX_TERM_CODEPOINTS_PER_SHARD
    assert config.resources.result_buffer_records == DEFAULT_RESULT_BUFFER_RECORDS
    digest = effective_configuration_sha256(config)
    assert len(digest) == 64
    assert digest == digest.lower()
    assert all(character in "0123456789abcdef" for character in digest)


@pytest.mark.parametrize("preset", list(Preset))
def test_every_preset_maps_exactly(preset: Preset) -> None:
    expected = tuple(
        component for component in COMPONENT_ORDER if component in PRESET_COMPONENTS[preset]
    )
    assert resolve_components((preset,), ()) == expected
    assert set(resolve_components((preset,), ())) == set(PRESET_COMPONENTS[preset])


def test_component_only_overlapping_combined_full_and_canonical_order() -> None:
    assert resolve_components((), (Component.PROCESS_STEPS,)) == (Component.PROCESS_STEPS,)
    overlapping = resolve_components(
        (Preset.MATERIALS_WITH_QUANTITIES,),
        (Component.MATERIALS, Component.UNITS),
    )
    assert overlapping == (
        Component.MATERIALS,
        Component.UNITS,
        Component.QUANTITY_EXPRESSIONS,
    )
    combined = resolve_components(
        (Preset.EQUIPMENT, Preset.MATERIALS),
        (Component.PROCESS_STEPS,),
    )
    assert combined == (
        Component.PROCESS_STEPS,
        Component.MATERIALS,
        Component.EQUIPMENT,
    )
    assert resolve_components((Preset.FULL,), ()) == COMPONENT_ORDER
    assert len(resolve_components((Preset.FULL,), (Component.UNITS,))) == 8
    reversed_request = resolve_components(
        (Preset.MATERIALS_WITH_QUANTITIES, Preset.UNIT_OPERATIONS),
        (Component.EQUIPMENT,),
    )
    assert reversed_request == (
        Component.UNIT_OPERATIONS,
        Component.MATERIALS,
        Component.EQUIPMENT,
        Component.UNITS,
        Component.QUANTITY_EXPRESSIONS,
    )
    assert (
        resolve_components(
            (Preset.UNIT_OPERATIONS, Preset.MATERIALS_WITH_QUANTITIES),
            (Component.EQUIPMENT,),
        )
        == reversed_request
    )


def test_with_presets_are_coexecution_only() -> None:
    materials = PRESET_COMPONENTS[Preset.MATERIALS_WITH_QUANTITIES]
    equipment = PRESET_COMPONENTS[Preset.EQUIPMENT_WITH_PARAMETERS]
    assert materials == (
        Component.MATERIALS,
        Component.QUANTITY_EXPRESSIONS,
        Component.UNITS,
    )
    assert equipment == (
        Component.EQUIPMENT,
        Component.PARAMETER_NAMES,
        Component.PARAMETER_VALUE_EXPRESSIONS,
        Component.UNITS,
    )
    assert not hasattr(EffectiveExecutionConfiguration, "associations")
    assert "association" not in EffectiveExecutionConfiguration.model_fields
    assert "parent" not in EffectiveExecutionConfiguration.model_fields
    assert "required_child" not in EffectiveExecutionConfiguration.model_fields


def test_fuzzy_defaults_explicit_and_rejects_coercion(tmp_path: Path) -> None:
    omitted = load_execution_configuration(
        _write_config(tmp_path / "omit.yaml", _minimal_yaml(fuzzy=None))
    )
    assert omitted.extraction.fuzzy_enabled is False
    enabled = load_execution_configuration(
        _write_config(tmp_path / "true.yaml", _minimal_yaml(fuzzy="true"))
    )
    assert enabled.extraction.fuzzy_enabled is True
    with pytest.raises(ConfigurationError, match="strict boolean"):
        load_execution_configuration(
            _write_config(tmp_path / "string.yaml", _minimal_yaml(fuzzy='"true"'))
        )
    with pytest.raises(ConfigurationError, match="strict boolean"):
        load_execution_configuration(
            _write_config(tmp_path / "number.yaml", _minimal_yaml(fuzzy="1"))
        )
    algo_body = (
        "schema_version: 1\n"
        "input:\n"
        "  reviewed_html_path: ./inputs/reviewed.html\n"
        "knowledge:\n"
        "  snapshot_directory: ./knowledge/flat-v1\n"
        "output:\n"
        "  directory: ./results\n"
        "extraction:\n"
        "  presets: [materials_with_quantities]\n"
        "  components: []\n"
        "  fuzzy_enabled: false\n"
        "  matching_algorithm: aho_corasick\n"
        "resources: {}\n"
    )
    with pytest.raises(ConfigurationError, match="unknown extraction fields"):
        load_execution_configuration(_write_config(tmp_path / "algo.yaml", algo_body))


def test_validation_failures(tmp_path: Path) -> None:
    cases: list[tuple[str, str]] = [
        (
            "missing",
            _minimal_yaml().replace("output:\n  directory: ./results\n", ""),
        ),
        (
            "unknown-root",
            _minimal_yaml(extra_root="policy_file: ./x.yaml\n"),
        ),
        (
            "nested-unknown",
            _minimal_yaml().replace(
                "  reviewed_html_path: ./inputs/reviewed.html\n",
                "  reviewed_html_path: ./inputs/reviewed.html\n  extra: 1\n",
            ),
        ),
        (
            "schema",
            _minimal_yaml().replace("schema_version: 1", "schema_version: 2"),
        ),
        (
            "empty-selection",
            _minimal_yaml(presets="[]", components="[]"),
        ),
        (
            "dup-preset",
            _minimal_yaml(presets="[materials, materials]"),
        ),
        (
            "dup-component",
            _minimal_yaml(presets="[]", components="[materials, materials]"),
        ),
        (
            "bad-enum",
            _minimal_yaml(presets="[not_a_preset]"),
        ),
        (
            "resource-zero",
            _minimal_yaml(resources="resources:\n  sqlite_read_batch_rows: 0"),
        ),
        (
            "resource-high",
            _minimal_yaml(
                resources=(
                    "resources:\n" f"  sqlite_read_batch_rows: {MAX_SQLITE_READ_BATCH_ROWS + 1}"
                )
            ),
        ),
        (
            "resource-coerced",
            _minimal_yaml(resources="resources:\n  sqlite_read_batch_rows: '5000'"),
        ),
        (
            "empty-path",
            _minimal_yaml().replace(
                "reviewed_html_path: ./inputs/reviewed.html",
                'reviewed_html_path: ""',
            ),
        ),
    ]
    for name, body in cases:
        path = _write_config(tmp_path / f"{name}.yaml", body)
        with pytest.raises(ConfigurationError):
            load_execution_configuration(path)


def test_yaml_safety_rejections(tmp_path: Path) -> None:
    payloads = {
        "duplicate-key": (
            "schema_version: 1\n"
            "schema_version: 1\n"
            "input:\n  reviewed_html_path: ./a.html\n"
            "knowledge:\n  snapshot_directory: ./k\n"
            "output:\n  directory: ./o\n"
            "extraction:\n  presets: [materials]\n  components: []\n"
            "resources: {}\n"
        ),
        "non-mapping-root": "- materials\n",
        "multiple-docs": _minimal_yaml() + "---\nschema_version: 1\n",
        "merge-key": (
            "schema_version: 1\n"
            "input:\n  reviewed_html_path: ./a.html\n"
            "knowledge:\n  snapshot_directory: ./k\n"
            "output:\n  directory: ./o\n"
            "extraction:\n"
            "  <<: {fuzzy_enabled: false}\n"
            "  presets: [materials]\n"
            "  components: []\n"
            "resources: {}\n"
        ),
        "anchor-alias": (
            "schema_version: 1\n"
            "input:\n  reviewed_html_path: &p ./a.html\n"
            "knowledge:\n  snapshot_directory: *p\n"
            "output:\n  directory: ./o\n"
            "extraction:\n  presets: [materials]\n  components: []\n"
            "resources: {}\n"
        ),
        "unsafe-tag": (
            "schema_version: !!python/object/apply:os.system ['echo hi']\n"
            "input:\n  reviewed_html_path: ./a.html\n"
            "knowledge:\n  snapshot_directory: ./k\n"
            "output:\n  directory: ./o\n"
            "extraction:\n  presets: [materials]\n  components: []\n"
            "resources: {}\n"
        ),
        "non-string-key": (
            "schema_version: 1\n"
            "1: oops\n"
            "input:\n  reviewed_html_path: ./a.html\n"
            "knowledge:\n  snapshot_directory: ./k\n"
            "output:\n  directory: ./o\n"
            "extraction:\n  presets: [materials]\n  components: []\n"
            "resources: {}\n"
        ),
    }
    for name, body in payloads.items():
        path = _write_config(tmp_path / f"{name}.yaml", body)
        with pytest.raises(ConfigurationError):
            load_execution_configuration(path)


def test_relative_paths_use_config_directory_not_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    foreign = tmp_path / "foreign-cwd"
    foreign.mkdir()
    path = _write_config(config_dir / "run.yaml", _minimal_yaml())
    monkeypatch.chdir(foreign)
    config = load_execution_configuration(path)
    assert config.input.reviewed_html_path == (config_dir / "inputs" / "reviewed.html").resolve()
    assert not config.input.reviewed_html_path.exists()
    assert not (foreign / "inputs").exists()
    assert not (config_dir / "inputs").exists()
    assert not (config_dir / "results").exists()


def test_override_replacement_and_digest_stability(tmp_path: Path) -> None:
    first = load_execution_configuration(
        _write_config(
            tmp_path / "a.yaml",
            _minimal_yaml(
                presets="[materials_with_quantities, equipment]",
                components="[process_steps]",
            ),
        )
    )
    second = load_execution_configuration(
        _write_config(
            tmp_path / "b.yaml",
            _minimal_yaml(
                presets="[equipment, materials_with_quantities]",
                components="[process_steps]",
            ),
        )
    )
    assert first.resolved_components == second.resolved_components
    assert effective_configuration_sha256(first) == effective_configuration_sha256(second)
    assert first.extraction.presets != second.extraction.presets

    overridden = load_execution_configuration(
        _write_config(
            tmp_path / "base.yaml",
            _minimal_yaml(presets="[materials]", components="[equipment]"),
        ),
        overrides=SelectionOverride(
            presets=(Preset.FULL,),
            components=(),
            fuzzy_enabled=True,
        ),
    )
    assert overridden.extraction.presets == (Preset.FULL,)
    assert overridden.extraction.components == ()
    assert overridden.extraction.fuzzy_enabled is True
    assert overridden.resolved_components == COMPONENT_ORDER
    assert "equipment" not in {component.value for component in overridden.extraction.components}

    fuzzy_changed = load_execution_configuration(
        _write_config(tmp_path / "fuzzy.yaml", _minimal_yaml(fuzzy="true"))
    )
    assert effective_configuration_sha256(fuzzy_changed) != effective_configuration_sha256(first)


def test_effective_configuration_round_trip_and_run_provenance(
    tmp_path: Path,
) -> None:
    config = load_execution_configuration(_write_config(tmp_path / "round.yaml", _minimal_yaml()))
    dumped = config.model_dump(mode="json")
    again = EffectiveExecutionConfiguration.model_validate(dumped)
    assert again == config
    digest = effective_configuration_sha256(config)
    run = RunProvenance(
        run_id="fixture-config-run",
        requested_presets=config.extraction.presets,
        requested_components=config.extraction.components,
        resolved_components=config.resolved_components,
        fuzzy_requested=config.extraction.fuzzy_enabled,
        input_html_sha256=HTML_SHA,
        knowledge=KnowledgeSnapshotIdentity(
            snapshot_id="fixture-snapshot",
            database_sha256=DB_SHA,
            manifest_sha256=MANIFEST_SHA,
        ),
        configuration_sha256=digest,
        rules_sha256=RULES_SHA,
        engine_version="lexical-config-test",
    )
    assert run.requested_presets == config.extraction.presets
    assert run.requested_components == config.extraction.components
    assert run.resolved_components == config.resolved_components
    assert run.fuzzy_requested is config.extraction.fuzzy_enabled
    assert run.configuration_sha256 == digest


def test_resource_defaults_apply_when_section_empty(tmp_path: Path) -> None:
    config = load_execution_configuration(
        _write_config(tmp_path / "defaults.yaml", _minimal_yaml(resources="resources: {}"))
    )
    assert config.resources.sqlite_read_batch_rows == DEFAULT_SQLITE_READ_BATCH_ROWS
    assert config.resources.sqlite_cache_kib == DEFAULT_SQLITE_CACHE_KIB


def test_selection_override_model_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SelectionOverride.model_validate({"presets": ["materials"], "policy": "x"})


def test_loader_does_not_create_output_paths(tmp_path: Path) -> None:
    path = _write_config(tmp_path / "nocreate.yaml", _minimal_yaml())
    config = load_execution_configuration(path)
    assert not config.output.directory.exists()
    assert not os.path.exists(config.input.reviewed_html_path)
