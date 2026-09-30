"""Regenerate standard JSON Schema files from the three Pydantic models."""

from __future__ import annotations

import json
from pathlib import Path

from app.page_classification.page_classification_schemas import (
    DocumentSupportingResponse,
    MaterialEquipmentResponse,
    ProcessOperationsResponse,
)


def main() -> None:
    destination = Path(__file__).resolve().parent / "json_schemas"
    destination.mkdir(exist_ok=True)
    outputs = (
        ("01-materials-equipment.schema.json", MaterialEquipmentResponse),
        ("02-process-operations-controls.schema.json", ProcessOperationsResponse),
        ("03-document-supporting-records.schema.json", DocumentSupportingResponse),
    )
    for filename, model in outputs:
        path = destination / filename
        path.write_text(
            json.dumps(model.model_json_schema(mode="validation"), indent=2) + "\n",
            encoding="utf-8",
        )
        print(path.name)


if __name__ == "__main__":
    main()
