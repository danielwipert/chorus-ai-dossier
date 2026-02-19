import json
from pathlib import Path
from jsonschema import Draft202012Validator

from chorus_ai.core.errors import ChorusFatalError

SCHEMA_DIR = Path(__file__).parent / "schemas"

NAME_TO_SCHEMA = {
    "ingestion_record": "ingestion_record.schema.json",
    "fact_list": "fact_list.schema.json",
    "summary": "summary.schema.json",
    "verification_report": "verification_report.schema.json",
    "compiled_summary": "compiled_summary.schema.json",
    "final_dossier": "final_dossier.schema.json",
}

def validate_artifact(name: str, obj: dict) -> None:
    schema_file = NAME_TO_SCHEMA.get(name)
    if not schema_file:
        raise ChorusFatalError("UNKNOWN_SCHEMA", f"No schema registered for artifact '{name}'", {"name": name})

    schema_path = SCHEMA_DIR / schema_file
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(obj), key=lambda e: e.path)

    if errors:
        raise ChorusFatalError(
            "SCHEMA_VALIDATION_FAILED",
            f"Artifact '{name}' failed schema validation",
            {
                "artifact": name,
                "errors": [{"path": list(e.path), "message": e.message} for e in errors[:25]],
            },
        )
