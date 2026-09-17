# Textract-to-HTML Ordering Correction — Before/After Evidence

## Inputs and run mode

- Input: existing `out/comparison/fexofenadine/textract.json` only; no AWS call was made.
- Baseline artifacts left unchanged under `out/comparison/fexofenadine/`.
- Regenerated with integrated local code into `out/comparison/fexofenadine-python-fixed/`.
- Physical PDF page numbers are used below.
- Verified in this repository with Poetry Python 3.11.4 (not the deliverer’s 3.12 runtime).

## Table placement

| Evidence | Baseline | Corrected (integrated) |
|---|---|---|
| Page 8 top header table | Emitted after procedure content; warning `UNPLACED_TABLE_APPENDED`. | First emitted table: `8471c7e8-f9da-43fd-9973-3eea64431ac7`; procedure table follows. |
| Affected pages | `UNPLACED_TABLE_APPENDED` on 2, 3, 7, 8, 9, 10, 12, 13, 14 and 15. | Same ten pages warn `TABLE_POSITIONED_WITH_GEOMETRY_FALLBACK`; no `UNPLACED_TABLE_APPENDED`. |
| Table completeness | Must be preserved. | 31 raw `TABLE` blocks emitted exactly once; zero missing and zero duplicates. |

## Merged-cell text order, page 18

Raw Textract `LINE` blocks already contain:

1. `The complete Post-Production Batch Record has been reviewed for completeness and`
2. `accuracy. All pages are complete and all entries conform to Good Documentation Practices.`

Corrected HTML stores one newline between them and renders one `<br>`. The scrambled
`The complete accuracy.` ordering is absent.

## Cell text boundaries, page 8

Procedure/ingredient cells preserve source LINE boundaries as newlines / `<br>`.
OCR values such as `HCI` remain unchanged.

## Integration regressions fixed here

1. Cells that contain `SELECTION_ELEMENT` keep checkbox markers in `cell.text` / HTML
   (`Approved [x]`), while still recording `selections`.
2. Pages without `LAYOUT_*` roots keep combined geometry ordering of LINE/TABLE/SIGNATURE
   (heading above a lower table). Geometry insertion applies only when layout roots exist.

## Visual inspection

MuPDF/pymupdf is not installed in this Poetry environment. Page 8/18 checks were
programmatic against regenerated HTML/JSON and the known PDF-backed expectations above.
Browser pixel layout was not inspected.

## Quality checks (this repository)

- `poetry run ruff check .` — passed
- `poetry run ruff format --check .` — passed
- `poetry run pyright` — 0 errors
- `poetry run pytest` — 103 passed
