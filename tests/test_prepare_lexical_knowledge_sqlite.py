"""Synthetic tests for the flat knowledge SQLite preparation."""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from pathlib import Path

import prepare_lexical_knowledge_sqlite as prep
import pytest

FDA = prep.DATASETS[0]
CHEBI = prep.DATASETS[1]
EQUIPMENT = prep.DATASETS[2]
UNIT = prep.DATASETS[3]


def _write_csv(path: Path, headers: tuple[str, ...], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(headers)
        writer.writerows(rows)


def _minimal_rows() -> dict[str, list[list[str]]]:
    return {
        FDA.logical_name: [
            [
                "T2G0WI9NEZ",
                "Water",
                "7732-18-5",
                "aqua",
                "cn",
                "000123",
                "English",
                "True",
                "FDA",
                "FDA_base",
                "FMR-1",
                "FMLT-1",
            ],
            ["", "NA", "", "None", "FALSE", "0", "", "", "src", "no_UNII", "FMR-2", "FMLT-2"],
        ],
        CHEBI.logical_name: [
            [
                "CHEBI:10",
                "(+)-Atherospermoline",
                "",
                "(+)-Atherospermoline",
                "hasRelatedSynonym",
                "",
                "kegg.compound",
                "ChEBI",
                "255",
                "http://example.test/CHEBI_10",
                "2_STAR",
                "CHR-1",
                "CHLT-1",
            ],
        ],
        EQUIPMENT.logical_name: [
            [
                "Container Blender",
                "Αναμικτήρας δοχείου",
                "L.B. Bohle",
                "PM 400",
                "Mixing speed",
                "Ταχύτητα ανάμειξης",
                "rpm",
                "2–6",
                "PM — Technical data",
                "EQR-1",
                "EQT-1",
                "MFR-1",
                "",
                "PAR-1",
            ],
        ],
        UNIT.logical_name: [
            _uo_row(
                "UOR-1",
                operation_id="UO-003",
                term="sieving",
                index_flag="TRUE",
                role="product_process",
                record_type="unit_operation",
            ),
            _uo_row(
                "UOR-2",
                operation_id="UO-003",
                term="sieving",
                index_flag="TRUE",
                role="product_process",
                record_type="unit_operation",
                step="Second step",
            ),
            _uo_row(
                "UOR-3",
                operation_id="",
                term="drying",
                index_flag="FALSE",
                role="step_cue",
                record_type="generic_step_cue",
            ),
        ],
    }


def _uo_row(
    row_id: str,
    *,
    operation_id: str,
    term: str,
    index_flag: str,
    role: str,
    record_type: str,
    step: str = "Removal of undesired fines",
) -> list[str]:
    values = dict.fromkeys(UNIT.headers, "")
    values.update(
        {
            "record_type": record_type,
            "row_id": row_id,
            "lexical_term_id": "LT-shared" if term == "sieving" else "LT-cue",
            "Category": "Solids" if operation_id else "",
            "Process step (EN)": step if operation_id else "",
            "Process step (GR)": "Βήμα" if operation_id else "",
            "process_step_id": "PS-1" if operation_id else "",
            "Operation ID": operation_id,
            "Operation role": role,
            "Search term (EN)": term,
            "Index this row": index_flag,
            "Match policy": "step_cue_only" if role == "step_cue" else "direct_candidate",
            "Scope / ambiguity rule": "Require product/process context",
        }
    )
    return [values[header] for header in UNIT.headers]


def _write_root(root: Path, rows: dict[str, list[list[str]]] | None = None) -> None:
    chosen = rows if rows is not None else _minimal_rows()
    for spec in prep.DATASETS:
        _write_csv(root / spec.relative_path, spec.headers, chosen[spec.logical_name])


def _connect_ro(database: Path) -> sqlite3.Connection:
    return sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)


def test_flat_tables_preserve_columns_text_and_edge_values(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    output_dir = tmp_path / "out"
    rows = _minimal_rows()
    rows[FDA.logical_name][0][1] = "  kept  "
    rows[FDA.logical_name][0][3] = "alpha, beta"
    rows[FDA.logical_name].append(
        [
            "UNII",
            "line\nbreak",
            "0001",
            "unknown",
            "N/A",
            "000123",
            "English",
            "FALSE",
            "src",
            "FDA_base",
            "FMR-3",
            "FMLT-3",
        ]
    )
    rows[FDA.logical_name].append([""] * len(FDA.headers))
    rows[FDA.logical_name].append(["   "] * len(FDA.headers))
    _write_root(data_root, rows)

    result = prep.prepare(data_root, output_dir, batch_size=1)
    database = result.snapshot_dir / "knowledge.sqlite"
    assert not database.with_name(database.name + "-wal").exists()
    connection = _connect_ro(database)
    try:
        names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        ]
        assert names == ["equipment", "materials_chebi", "materials_fda_ema", "unit_operations"]
        assert connection.execute("PRAGMA user_version").fetchone() == (1,)
        info = connection.execute("PRAGMA table_info(materials_fda_ema)").fetchall()
        assert [row[1] for row in info] == list(FDA.headers)
        assert all(row[2] == "TEXT" and row[3] == 1 for row in info)
        stored = connection.execute(
            "SELECT material_name, alias_name, CAS_NUMBER, alias_type, SMS_ID, Is_Preferred_Name "
            "FROM materials_fda_ema ORDER BY rowid"
        ).fetchall()
        assert stored[0][0] == "  kept  "
        assert stored[0][1] == "alpha, beta"
        assert stored[1] == ("NA", "None", "", "FALSE", "0", "")
        assert stored[2][0] == "line\nbreak"
        assert len(stored) == 3
        fda_report = next(
            table
            for table in result.validation_report["tables"]
            if table["table"] == FDA.logical_name
        )
        assert fda_report["blank_records_skipped"] == 2
        assert fda_report["imported_rows"] == 3
        assert stored[2][2] == "0001"
        greek = connection.execute(
            'SELECT "Τύπος εξοπλισμού (GR)", model_id FROM equipment'
        ).fetchone()
        assert greek == ("Αναμικτήρας δοχείου", "")
        assert (result.snapshot_dir / "FLAT_SQLITE_CONTRACT.md").read_text(encoding="utf-8") == (
            prep.contract_path().read_text(encoding="utf-8")
        )
    finally:
        connection.close()


def test_repetitions_inactive_rows_and_generic_cues_are_retained(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    output_dir = tmp_path / "out"
    _write_root(data_root)
    result = prep.prepare(data_root, output_dir, batch_size=2)
    connection = _connect_ro(result.snapshot_dir / "knowledge.sqlite")
    try:
        sieving = connection.execute(
            "SELECT row_id, lexical_term_id FROM unit_operations "
            'WHERE "Search term (EN)" = ? ORDER BY rowid',
            ("sieving",),
        ).fetchall()
        assert sieving == [("UOR-1", "LT-shared"), ("UOR-2", "LT-shared")]
        cue = connection.execute(
            'SELECT "Operation ID", "Operation role", "Index this row", record_type '
            "FROM unit_operations WHERE row_id = ?",
            ("UOR-3",),
        ).fetchone()
        assert cue == ("", "step_cue", "FALSE", "generic_step_cue")
    finally:
        connection.close()


def test_duplicate_row_id_malformed_record_and_schema_mismatch_fail(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    output_dir = tmp_path / "out"
    rows = _minimal_rows()
    rows[FDA.logical_name].append(rows[FDA.logical_name][0].copy())
    _write_root(data_root, rows)
    with pytest.raises(prep.PreparationError) as duplicate:
        prep.prepare(data_root, output_dir, batch_size=10)
    assert duplicate.value.code == "DUPLICATE_ROW_ID"
    assert list(output_dir.glob("flat-v1-*")) == []

    rows = _minimal_rows()
    _write_root(data_root, rows)
    fda_path = data_root / FDA.relative_path
    fda_path.write_text(fda_path.read_text(encoding="utf-8") + "only-one-field\n", encoding="utf-8")
    with pytest.raises(prep.PreparationError) as malformed:
        prep.prepare(data_root, output_dir, batch_size=10)
    assert malformed.value.code == "MALFORMED_RECORD"

    _write_root(data_root)
    headers = list(EQUIPMENT.headers)
    headers[0] = "Equipment type"
    _write_csv(
        data_root / EQUIPMENT.relative_path, tuple(headers), _minimal_rows()[EQUIPMENT.logical_name]
    )
    with pytest.raises(prep.PreparationError) as mismatch:
        prep.prepare(data_root, output_dir, batch_size=10)
    assert mismatch.value.code == "SCHEMA_MISMATCH"


def test_pagination_lookup_and_batch_size_equivalence(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    _write_root(data_root)
    small = prep.prepare(data_root, tmp_path / "small", batch_size=1)
    large = prep.prepare(data_root, tmp_path / "large", batch_size=50)
    left = _ordered_rows(small.snapshot_dir / "knowledge.sqlite")
    right = _ordered_rows(large.snapshot_dir / "knowledge.sqlite")
    assert left == right

    connection = _connect_ro(small.snapshot_dir / "knowledge.sqlite")
    try:
        seen: list[str] = []
        cursor = 0
        while True:
            batch = connection.execute(
                "SELECT rowid, row_id FROM materials_fda_ema "
                "WHERE rowid > ? ORDER BY rowid LIMIT ?",
                (cursor, 1),
            ).fetchall()
            if not batch:
                break
            assert len(batch) == 1
            seen.append(str(batch[0][1]))
            assert int(batch[0][0]) > cursor
            cursor = int(batch[0][0])
        assert seen == ["FMR-1", "FMR-2"]
        assert connection.execute(
            "SELECT material_name FROM materials_fda_ema WHERE row_id = ?",
            ("FMR-2",),
        ).fetchone() == ("NA",)
        plan = " ".join(
            str(row[3])
            for row in connection.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM materials_fda_ema WHERE row_id = ?",
                ("FMR-2",),
            )
        )
        assert "row_id" in plan
    finally:
        connection.close()


def test_failed_publication_leaves_existing_snapshot_and_sources(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    output_dir = tmp_path / "out"
    _write_root(data_root)
    original = prep.prepare(data_root, output_dir, batch_size=5)
    database = original.snapshot_dir / "knowledge.sqlite"
    before_db = database.read_bytes()
    source_hashes = {
        spec.logical_name: hashlib.sha256((data_root / spec.relative_path).read_bytes()).hexdigest()
        for spec in prep.DATASETS
    }
    rows = _minimal_rows()
    rows[CHEBI.logical_name].append(rows[CHEBI.logical_name][0].copy())
    _write_root(data_root, rows)
    source_bytes = {
        spec.logical_name: (data_root / spec.relative_path).read_bytes() for spec in prep.DATASETS
    }
    with pytest.raises(prep.PreparationError) as failure:
        prep.prepare(data_root, output_dir, batch_size=5)
    assert failure.value.code == "DUPLICATE_ROW_ID"
    assert database.read_bytes() == before_db
    assert list(output_dir.glob(".tmp-*")) == []
    for spec in prep.DATASETS:
        assert (data_root / spec.relative_path).read_bytes() == source_bytes[spec.logical_name]
    assert (
        source_hashes[CHEBI.logical_name]
        != hashlib.sha256(source_bytes[CHEBI.logical_name]).hexdigest()
    )


def test_readonly_database_survives_removal_of_fixture_csvs(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    output_dir = tmp_path / "out"
    _write_root(data_root)
    result = prep.prepare(data_root, output_dir, batch_size=3)
    import shutil

    shutil.rmtree(data_root)
    assert not data_root.exists()
    connection = _connect_ro(result.snapshot_dir / "knowledge.sqlite")
    try:
        row = connection.execute(
            "SELECT alias_name, alias_type FROM materials_chebi WHERE row_id = ?",
            ("CHR-1",),
        ).fetchone()
        assert row == ("(+)-Atherospermoline", "hasRelatedSynonym")
    finally:
        connection.close()


def test_strict_csv_rejects_unterminated_quotes_and_keeps_valid_escapes(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    output_dir = tmp_path / "out"
    rows = _minimal_rows()
    rows[FDA.logical_name][0][1] = 'say "hello"\nstill one field'
    rows[FDA.logical_name][0][3] = "alpha, beta"
    _write_root(data_root, rows)
    prepared = prep.prepare(data_root, output_dir, batch_size=2)
    connection = _connect_ro(prepared.snapshot_dir / "knowledge.sqlite")
    try:
        stored = connection.execute(
            "SELECT material_name, alias_name FROM materials_fda_ema WHERE row_id = ?",
            ("FMR-1",),
        ).fetchone()
        assert stored == ('say "hello"\nstill one field', "alpha, beta")
    finally:
        connection.close()

    _write_root(data_root)
    fda_path = data_root / FDA.relative_path
    plain = _minimal_rows()[FDA.logical_name][0]
    assert plain[FDA.headers.index("row_id")] == "FMR-1"
    prefix = ",".join(plain[:-1])
    fda_path.write_text(
        ",".join(FDA.headers) + "\n" + prefix + ',"FMLT-open',
        encoding="utf-8",
        newline="",
    )
    written = fda_path.read_bytes()
    with pytest.raises(prep.PreparationError) as unterminated:
        prep.prepare(data_root, tmp_path / "bad-row", batch_size=2)
    assert unterminated.value.code == "MALFORMED_RECORD"
    assert list((tmp_path / "bad-row").glob("flat-v1-*")) == []
    assert fda_path.read_bytes() == written

    header = fda_path.read_text(encoding="utf-8").splitlines()[0]
    fda_path.write_text('"' + header + "\n", encoding="utf-8", newline="")
    before = fda_path.read_bytes()
    with pytest.raises(prep.PreparationError) as bad_header:
        prep.prepare(data_root, tmp_path / "bad-header", batch_size=2)
    assert bad_header.value.code == "MALFORMED_RECORD"
    assert "SCHEMA_MISMATCH" not in str(bad_header.value)
    assert list((tmp_path / "bad-header").glob("flat-v1-*")) == []
    assert fda_path.read_bytes() == before


def test_complete_snapshot_is_reused_without_rewriting_artifacts(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    output_dir = tmp_path / "out"
    _write_root(data_root)
    first = prep.prepare(data_root, output_dir, batch_size=4)
    before = _artifact_bytes(first.snapshot_dir)
    second = prep.prepare(data_root, output_dir, batch_size=4)
    assert second.reused is True
    assert second.snapshot_dir == first.snapshot_dir
    assert _artifact_bytes(first.snapshot_dir) == before
    identity = first.manifest["snapshot_identity"]
    assert prep.reusable_snapshot(first.snapshot_dir, identity) is not None


def test_incomplete_snapshot_companions_are_not_reusable(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    output_dir = tmp_path / "out"
    _write_root(data_root)
    prepared = prep.prepare(data_root, output_dir, batch_size=4)
    snapshot = prepared.snapshot_dir
    identity = prepared.manifest["snapshot_identity"]
    preserved = _artifact_bytes(snapshot)

    for name in ("FLAT_SQLITE_CONTRACT.md", "validation_report.json"):
        target = snapshot / name
        backup = target.read_bytes()
        target.unlink()
        assert prep.reusable_snapshot(snapshot, identity) is None
        target.write_bytes(backup)
    assert _artifact_bytes(snapshot) == preserved

    contract = snapshot / "FLAT_SQLITE_CONTRACT.md"
    contract.write_text("   \n", encoding="utf-8")
    assert prep.reusable_snapshot(snapshot, identity) is None
    contract.write_bytes(preserved["FLAT_SQLITE_CONTRACT.md"])

    report = snapshot / "validation_report.json"
    report.write_text("[", encoding="utf-8")
    assert prep.reusable_snapshot(snapshot, identity) is None
    report.write_text("[]", encoding="utf-8")
    assert prep.reusable_snapshot(snapshot, identity) is None
    report.write_text("{}", encoding="utf-8")
    assert prep.reusable_snapshot(snapshot, identity) is None

    payload = json.loads(preserved["validation_report.json"].decode("utf-8"))
    payload["content_digests_match"] = "false"
    report.write_text(json.dumps(payload), encoding="utf-8")
    assert prep.reusable_snapshot(snapshot, identity) is None
    payload["content_digests_match"] = True
    payload["integrity_check"] = "failed"
    report.write_text(json.dumps(payload), encoding="utf-8")
    assert prep.reusable_snapshot(snapshot, identity) is None
    payload["integrity_check"] = "ok"
    payload["tables"][0]["imported_rows"] = payload["tables"][0]["imported_rows"] + 1
    report.write_text(json.dumps(payload), encoding="utf-8")
    assert prep.reusable_snapshot(snapshot, identity) is None


def test_prepare_keeps_incomplete_snapshot_and_writes_a_new_one(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    output_dir = tmp_path / "out"
    _write_root(data_root)
    original = prep.prepare(data_root, output_dir, batch_size=4)
    contract = original.snapshot_dir / "FLAT_SQLITE_CONTRACT.md"
    contract.unlink()
    database_bytes = (original.snapshot_dir / "knowledge.sqlite").read_bytes()
    manifest_bytes = (original.snapshot_dir / "manifest.json").read_bytes()
    rebuilt = prep.prepare(data_root, output_dir, batch_size=4)
    assert rebuilt.reused is False
    assert rebuilt.snapshot_dir != original.snapshot_dir
    assert rebuilt.snapshot_dir.name.endswith("--2")
    assert not contract.exists()
    assert (original.snapshot_dir / "knowledge.sqlite").read_bytes() == database_bytes
    assert (original.snapshot_dir / "manifest.json").read_bytes() == manifest_bytes
    assert (rebuilt.snapshot_dir / "FLAT_SQLITE_CONTRACT.md").is_file()
    assert (rebuilt.snapshot_dir / "validation_report.json").is_file()


def _artifact_bytes(snapshot: Path) -> dict[str, bytes]:
    names = (
        "knowledge.sqlite",
        "manifest.json",
        "validation_report.json",
        "FLAT_SQLITE_CONTRACT.md",
    )
    return {name: (snapshot / name).read_bytes() for name in names}


def _ordered_rows(database: Path) -> dict[str, list[tuple[object, ...]]]:
    connection = _connect_ro(database)
    try:
        collected: dict[str, list[tuple[object, ...]]] = {}
        for spec in prep.DATASETS:
            columns = ", ".join(prep.quote_ident(header) for header in spec.headers)
            rows = connection.execute(
                f"SELECT {columns} FROM {prep.quote_ident(spec.table_name)} ORDER BY rowid"
            ).fetchall()
            collected[spec.logical_name] = [tuple(row) for row in rows]
        return collected
    finally:
        connection.close()
