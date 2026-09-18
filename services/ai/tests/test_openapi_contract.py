from pathlib import Path

import yaml
from openapi_spec_validator import validate


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_openapi_contract_is_valid() -> None:
    with (REPOSITORY_ROOT / "contracts" / "openapi.yaml").open(encoding="utf-8") as stream:
        specification = yaml.safe_load(stream)

    validate(specification)
