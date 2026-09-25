# Flat SQLite knowledge contract

Schema version: `1` (`PRAGMA user_version`).
Preparation version: `flat-sqlite-1`.

This database is a flat copy of four source CSVs. It is the lexical engine's sole runtime knowledge input. The CSV directory is a provenance and rebuild input for this utility only. Consumers do not need those CSVs when the snapshot manifest accompanies the database.

There is no normalized entity, term, link, or provenance graph. There are no `terms`, `lexical_entries`, `entry_sources`, or `source_records` tables, and no join workflow. A SQL index locates catalogue rows. It does not search document text and it does not replace a later multi-pattern document matcher.

Import success does not certify pharmaceutical correctness.

## Tables

Four ordinary SQLite rowid tables. Every source column is `TEXT NOT NULL`. Empty source cells are empty strings, not SQL NULL. Values such as `NA`, `N/A`, `unknown`, `None`, `FALSE`, and `0` stay literal text. Leading zeros, Unicode, case, punctuation, leading and trailing whitespace, and embedded newlines stay as parsed cell values. CSV quoting syntax is not part of the cell.

`row_id` is `TEXT NOT NULL PRIMARY KEY`. It is the source record id and is not regenerated. SQLite's implicit `rowid` is only a snapshot-local pagination cursor. It is not `row_id` and it is not stable across rebuilds. These tables are not `WITHOUT ROWID`.

No foreign keys. Repeated operation, material, and model ids are legitimate and are not UNIQUE. No technical columns are added to these tables.

The only indexes are the primary-key indexes SQLite creates for `row_id` (`sqlite_autoindex_*`). Demonstrated reads are `row_id` lookup and `rowid` pagination, so no second search index is created.

A fully blank record (every cell empty or whitespace-only) is skipped and counted. Any other record with a missing or whitespace-only `row_id`, a duplicate `row_id`, a duplicate or blank header, or the wrong number of fields is rejected. A quoted multiline CSV record is one logical record.

Preparation reads those CSVs with the standard library parser in strict mode (`strict=True`), `utf-8-sig`, and `newline=""`. An unterminated quote is a malformed record and is not imported. Strict mode is that supported CSV contract; it is not a separate custom validator.

### `materials_fda_ema`

Source: `Materials/final/Unified_Materials_with_SMS.csv`.

Columns, in order:

`UNII`, `material_name`, `CAS_NUMBER`, `alias_name`, `alias_type`, `SMS_ID`, `Language`, `Is_Preferred_Name`, `source`, `match_status`, `row_id`, `lexical_term_id`.

Search fields are `material_name` and `alias_name`. Keep `UNII`, `SMS_ID`, `alias_type`, `Language`, `Is_Preferred_Name`, `source`, and `match_status` from the same row. `Is_Preferred_Name` text `False` is not a Boolean false for FDA rows that leave the cell empty. Equal names in another table do not establish the same chemical identity.

### `materials_chebi`

Source: `Materials/final/ChEBI_Materials.csv`.

Columns, in order:

`CHEBI_ID`, `material_name`, `CAS_NUMBER`, `alias_name`, `alias_type`, `alias_category`, `alias_source`, `source`, `source_version`, `source_record`, `star_rating`, `row_id`, `lexical_term_id`.

Search fields are `material_name` and `alias_name`. Keep `CHEBI_ID`, alias relation (`alias_type`, `alias_category`, `alias_source`), `source`, `source_version`, `source_record`, and `star_rating` from the same row. `hasRelatedSynonym` is not an exact synonym. There is no merge with FDA/EMA identifiers. Related synonyms and canonical-only rows (empty alias cells) stay in the table.

### `equipment`

Source: `Equipment/final/Equipment.csv`.

Columns, in order:

`Equipment type (EN)`, `Τύπος εξοπλισμού (GR)`, `Brand / Manufacturer`, `Model`, `Operating parameter (EN)`, `Παράμετρος λειτουργίας (GR)`, `Unit`, `Published range`, `Source / section`, `row_id`, `equipment_type_id`, `manufacturer_id`, `model_id`, `parameter_id`.

Equipment vocabulary is the English and Greek type, manufacturer, and model, with `equipment_type_id`, `manufacturer_id`, and `model_id`. Parameter names are `Operating parameter (EN)`, `Παράμετρος λειτουργίας (GR)`, and `parameter_id`. A blank grouping id means the source left that id empty; the original label cell is still preserved. Placeholders and qualifications inside model, parameter, unit, range, or source text stay as written.

`Unit` and `Published range` are catalogue context, not observed batch quantities or measured parameter values. A model–parameter row is not a detected document association.

### `unit_operations`

Source: `Unit-Operations/final/UnitOperations.csv`. All 37 source columns, in source order:

`record_type`, `row_id`, `category_id`, `process_step_id`, `lexical_term_id`, `source_evidence_id`, `link_id`, `link_direction`, `Category`, `Unit operation (EN)`, `Unit operation (GR)`, `Purpose (EN)`, `Purpose (GR)`, `Process step (EN)`, `Process step (GR)`, `Relationship / order`, `Source / supporting evidence`, `Source layer`, `Original operation label`, `Language / review note`, `Operation ID`, `Operation role`, `Search term (EN)`, `Normalized search key`, `Canonical unit operation`, `Term relation`, `Match policy`, `Index this row`, `Provenance / source`, `Scope / ambiguity rule`, `Review status`, `Operation ID A`, `Operation A`, `Relationship type`, `Operation ID B`, `Operation B`, `Inference rule`.

The lexical field is `Search term (EN)`, read with `Index this row`, `Match policy`, `Term relation`, `Operation role`, `Scope / ambiguity rule`, and `Review status` on that same flat row. `Index this row` remains original text. A nonempty `FALSE` string is not true. Inactive rows stay imported and stay inactive until a later reader applies that flag explicitly.

Process-step fields are `Process step (EN)`, `Process step (GR)`, and `process_step_id`. Catalogue operation scope on the same row is metadata, not evidence that the document performed those steps.

Generic cues keep blank operation ids and `Operation role` `step_cue`. Flat repetitions of one lexical record across steps and links stay as separate source rows. The later engine may collapse duplicate document hits; this preparation does not delete those rows.

Operation–step and operation–link context is not a detected document association. Three previously discussed policy wordings (`cell culture expansion`, `liquid bottle filling`, `controlled rate freezing`) are source-content review items. Preparation reports stored values and does not edit them.

## Read-only consumer queries

Open the snapshot database read-only. Do not write it and do not use a WAL sidecar. Pin one snapshot directory; do not mix files from two builds.

```text
file:<snapshot>/knowledge.sqlite?mode=ro
```

```sql
PRAGMA query_only = ON;
PRAGMA user_version; -- expect 1
```

Bounded FDA/EMA scan. `scan_cursor` is local to this pinned file:

```sql
SELECT rowid AS scan_cursor, row_id, lexical_term_id,
       material_name, alias_name, alias_type, UNII, SMS_ID
FROM materials_fda_ema
WHERE rowid > :after_rowid
ORDER BY rowid
LIMIT :batch_size;
```

Recover one original FDA/EMA record:

```sql
SELECT *
FROM materials_fda_ema
WHERE row_id = :source_row_id;
```

ChEBI scan:

```sql
SELECT rowid AS scan_cursor, row_id, lexical_term_id, CHEBI_ID,
       material_name, alias_name, alias_type, alias_category, alias_source
FROM materials_chebi
WHERE rowid > :after_rowid
ORDER BY rowid
LIMIT :batch_size;
```

ChEBI record lookup:

```sql
SELECT *
FROM materials_chebi
WHERE row_id = :source_row_id;
```

Equipment and parameter scan:

```sql
SELECT rowid AS scan_cursor, row_id,
       "Equipment type (EN)", "Τύπος εξοπλισμού (GR)",
       "Brand / Manufacturer", "Model",
       "equipment_type_id", "manufacturer_id", "model_id",
       "Operating parameter (EN)", "Παράμετρος λειτουργίας (GR)",
       "parameter_id"
FROM equipment
WHERE rowid > :after_rowid
ORDER BY rowid
LIMIT :batch_size;
```

Equipment record lookup:

```sql
SELECT *
FROM equipment
WHERE row_id = :source_row_id;
```

Unit-operation scan:

```sql
SELECT rowid AS scan_cursor, row_id, lexical_term_id,
       "Search term (EN)", "Operation ID", "Index this row",
       "Match policy", "Operation role", "Scope / ambiguity rule"
FROM unit_operations
WHERE rowid > :after_rowid
ORDER BY rowid
LIMIT :batch_size;
```

Unit-operation record lookup:

```sql
SELECT *
FROM unit_operations
WHERE row_id = :source_row_id;
```

Start `:after_rowid` at `0`. Advance it to the last `scan_cursor` returned. Stop when a batch is empty.

The later engine needs this field mapping and these four tables. It does not need CSV parsing, source-file discovery, or relational joins. Choosing search fields is not a normalized storage model.

## Snapshot identity and provenance

`manifest.json` records schema version, preparation version, snapshot identity, preparation-code SHA-256, each source logical name, path, SHA-256, byte size, headers, and nonblank row count, plus the database SHA-256, byte size, and `completion_status`. The snapshot identity is the schema version, preparation version, and the four source SHA-256 values. Timestamps are recorded separately and are not part of that identity. The database hash is outside the database and is computed only after the connection is closed.

`validation_report.json` records integrity, content-digest reconciliation, lookup plans, and build measurements.

Before use, confirm `completion_status` is `complete`, `PRAGMA user_version` is `1`, `PRAGMA integrity_check` is `ok`, and the database file hash matches the manifest. Treat a published snapshot as read-only.

Reusing a snapshot requires all four artifacts to be present and readable: `knowledge.sqlite`, `manifest.json`, `validation_report.json`, and `FLAT_SQLITE_CONTRACT.md`. The contract text must be nonempty. The manifest and validation report must be JSON objects. The report must record `integrity_check` as `ok`, boolean true values for content-digest, source-preservation, and WAL-absence flags, and four table summaries whose names and row counts match the manifest. A snapshot that fails these checks is left in place. A new preparation writes a separate directory and does not repair the old one. Reuse does not require the stored contract text or producer-code hash to match a later repository revision.

## Rebuild

After a deliberate source-data update, create a new snapshot. Do not overwrite a previous complete snapshot.

```powershell
poetry run python scripts/prepare_lexical_knowledge_sqlite.py --data-root "C:\Users\User\Desktop\MBR_core\RAG-Core-data\Agregate-Items" --output-dir "C:\Users\User\Desktop\MBR_core\RAG-Core-data\Agregate-Items\Prepared\flat-sqlite"
```

Current filenames are `Unified_Materials_with_SMS.csv`, `ChEBI_Materials.csv`, `Equipment.csv`, and `UnitOperations.csv` under the `final` directories above. Those names supersede historical `*_enhanced.csv` names. The enhanced columns and ids remain in these files.
