#!/usr/bin/env python3
"""Validate/import an official scenario inside Core's loopback-only demo gate."""

import argparse
import json
from pathlib import Path
import subprocess
from urllib.request import urlopen
from uuid import NAMESPACE_URL, uuid5


ROOT = Path(__file__).resolve().parents[1]
SCENARIO_ID = str(uuid5(NAMESPACE_URL, "sirena-112-postgres-import-smoke-77"))
BASE = "http://127.0.0.1:8080"


def list_scenarios():
    with urlopen(BASE + "/api/teacher/scenarios", timeout=10) as response:
        return json.load(response)


def local_post(path, body):
    command = [
        "docker", "compose", "exec", "-T", "core", "curl", "--fail-with-body",
        "--silent", "--show-error", "-X", "POST", "-H", "Content-Type: application/json",
        "--data-binary", "@-", "http://127.0.0.1:8080" + path,
    ]
    result = subprocess.run(command, input=json.dumps(body, ensure_ascii=False).encode(),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace") + result.stdout.decode(errors="replace"))
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        assert any(item["id"] == SCENARIO_ID for item in list_scenarios())
        print("PASS: imported scenario persisted across Core restart")
        return

    scenario = json.loads((ROOT / "contracts/examples/scenario-1050602.json").read_text(encoding="utf-8"))
    scenario["id"] = SCENARIO_ID
    scenario["title"] = "PostgreSQL import smoke 77"
    package = {"scenarios": [scenario]}
    preview = local_post("/api/teacher/scenarios/import/validate", package)
    assert preview["valid"] and preview["scenarioIds"] == [SCENARIO_ID], preview
    assert not any(item["id"] == SCENARIO_ID for item in list_scenarios())
    applied = local_post("/api/teacher/scenarios/import", package)
    assert applied == {"imported": 1, "scenarioIds": [SCENARIO_ID]}, applied
    assert any(item["id"] == SCENARIO_ID for item in list_scenarios())
    print("PASS: validated scenario imported in PostgreSQL")


if __name__ == "__main__":
    main()
