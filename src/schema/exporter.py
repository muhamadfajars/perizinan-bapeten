"""Schema exporter to generate standard JSON Schema files for Laravel / API integration."""

from pathlib import Path
import json

from src.schema.entities import ApplicationEntity
from src.schema.matching import CrossCheckReport, EntityCrossCheck, FieldCrossCheck


def export_schemas(output_dir: Path = None) -> dict:
    """Exports Pydantic v2 schemas as JSON Schema files."""
    if output_dir is None:
        from config import DATA_DIR
        output_dir = DATA_DIR / "schemas"

    output_dir.mkdir(parents=True, exist_ok=True)

    schemas = {
        "application_entity.schema.json": ApplicationEntity.model_json_schema(),
        "cross_check_report.schema.json": CrossCheckReport.model_json_schema(),
        "entity_cross_check.schema.json": EntityCrossCheck.model_json_schema(),
        "field_cross_check.schema.json": FieldCrossCheck.model_json_schema(),
    }

    generated_paths = {}
    for filename, schema_dict in schemas.items():
        file_path = output_dir / filename
        file_path.write_text(json.dumps(schema_dict, indent=2, ensure_ascii=False), encoding="utf-8")
        generated_paths[filename] = str(file_path)

    return generated_paths


if __name__ == "__main__":
    paths = export_schemas()
    print("Exported JSON Schemas:")
    for name, path in paths.items():
        print(f" - {name} -> {path}")
