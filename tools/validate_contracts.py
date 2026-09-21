#!/usr/bin/env python3
"""Validate shared OpenAPI and JSON Schema contracts and their examples."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import validate as validate_openapi


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = REPOSITORY_ROOT / "contracts"


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def validate_json_instance(instance_path: Path, schema: dict[str, Any]) -> None:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(load_json(instance_path)), key=lambda error: error.json_path)
    if errors:
        details = "\n".join(f"  - {error.json_path}: {error.message}" for error in errors)
        raise ValueError(f"{instance_path.relative_to(REPOSITORY_ROOT)} is invalid:\n{details}")


def main() -> None:
    scenario_schema = load_json(CONTRACTS_DIR / "scenario.schema.json")
    classifier_schema = load_json(CONTRACTS_DIR / "classifier.schema.json")

    Draft202012Validator.check_schema(scenario_schema)
    Draft202012Validator.check_schema(classifier_schema)

    for example_path in sorted((CONTRACTS_DIR / "examples").glob("scenario-*.json")):
        validate_json_instance(example_path, scenario_schema)

    validate_json_instance(
        CONTRACTS_DIR / "catalog" / "classifier-v046-11.json",
        classifier_schema,
    )

    with (CONTRACTS_DIR / "openapi.yaml").open(encoding="utf-8") as stream:
        validate_openapi(yaml.safe_load(stream))

    print("OpenAPI, JSON Schemas, classifier catalog, and scenario examples are valid.")


if __name__ == "__main__":
    main()
