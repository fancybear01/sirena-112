#!/usr/bin/env python3
"""End-to-end HTTP smoke for the shared 1050602 card fixture (stdlib only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "contracts" / "examples" / "scenario-1050602.json"


def request(base: str, path: str, method: str = "GET", body: dict | None = None) -> dict | list:
    payload = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = Request(base.rstrip("/") + path, data=payload, headers=headers, method=method)
    try:
        with urlopen(req, timeout=10) as response:
            return json.load(response)
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path}: HTTP {error.code}: {details}") from error
    except URLError as error:
        raise RuntimeError(f"{method} {path}: {error.reason}") from error


def check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def run_once(core: str, fixture: dict, expect_ai: bool, expect_fallback: bool) -> tuple:
    truth = fixture["groundTruth"]
    scenarios = request(core, "/api/teacher/scenarios")
    scenario = next((item for item in scenarios if item["id"] == fixture["id"]), None)
    check(scenario is not None, "Core не выдал сценарий 1050602")
    check(scenario["groundTruth"]["classifierVersion"] == truth["classifierVersion"],
          "Версия классификатора Core не совпадает с общей фикстурой")

    session = request(core, "/api/teacher/sessions", "POST", {"scenarioId": fixture["id"]})
    session_id = session["id"]
    started = request(core, f"/api/teacher/sessions/{session_id}/start", "POST")
    check(started["state"] == "ACTIVE", "Занятие не перешло в ACTIVE")

    assignments = request(core, "/api/student/assignments")
    check(any(item["session"]["id"] == session_id for item in assignments),
          "Обучающийся не видит новое назначение")
    form = request(core, f"/api/student/sessions/{session_id}/card-form")
    check(form["classifierVersion"] == truth["classifierVersion"],
          "Динамическая форма использует другую версию классификатора")

    input_data = truth["expectedInput"]
    draft = request(core, f"/api/student/sessions/{session_id}/card", "PATCH",
                    {"input": input_data, "expectedRevision": 0})
    calculation = draft["card"]["calculation"]
    check(calculation["status"] == "RESOLVED", "Core не завершил классификацию")
    for field in ("classifierCode", "incidentType", "ekp35IncidentType", "responseScenarioCode"):
        check(calculation[field] == truth[field], f"Поле {field} расходится с общей фикстурой")
    expected_services = {item["id"] for item in truth["requiredServices"]}
    actual_services = {item["id"] for item in calculation["services"]}
    check(actual_services == expected_services, "Маршрутизация служб расходится с общей фикстурой")

    report = request(core, f"/api/student/sessions/{session_id}/submit", "POST",
                     {"input": input_data, "expectedRevision": draft["cardRevision"]})
    check(report["sessionId"] == session_id, "Отчёт относится к другой сессии")
    check(report["classifierVersion"] == truth["classifierVersion"],
          "Версия классификатора в отчёте не совпадает")
    check(report["classifierCode"] == truth["classifierCode"],
          "Код классификатора в отчёте не совпадает")
    check(bool(report["criteria"]), "Отчёт не содержит объяснимых критериев")
    if expect_ai:
        check(len(report["criteria"]) >= 8,
              "Core вернул упрощённый отчёт: AI не участвовал в оценке")
    if expect_fallback:
        check(len(report["criteria"]) == 4,
              "Ожидался резервный отчёт Core с четырьмя критериями")

    saved = request(core, f"/api/teacher/sessions/{session_id}/report")
    check(saved == report, "Преподаватель не видит сохранённый отчёт")
    reread = request(core, f"/api/student/sessions/{session_id}")
    check(reread["state"] == "SCORED" and reread["report"] == report,
          "Повторный запрос потерял итоговое состояние")
    dds = request(core, f"/api/teacher/sessions/{session_id}/service-assignments")
    check({item["serviceId"] for item in dds} == expected_services,
          "Назначения ДДС отличаются от вычисленных служб")
    print(f"session={session_id} version={report['classifierVersion']} "
          f"services={len(dds)} score={report['score']}/{report['maxScore']} "
          f"criteria={len(report['criteria'])}")
    return report["score"], report["maxScore"], tuple(
        (item["code"], item["points"], item["maxPoints"]) for item in report["criteria"]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", default="http://127.0.0.1:8080")
    parser.add_argument("--ai", default="http://127.0.0.1:8090")
    expected_source = parser.add_mutually_exclusive_group()
    expected_source.add_argument("--expect-ai", action="store_true",
                                 help="Fail if Core falls back to its four-criterion report")
    expected_source.add_argument("--expect-fallback", action="store_true",
                                 help="Require Core's four-criterion fallback report")
    args = parser.parse_args()
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    try:
        check(request(args.core, "/ready")["status"] == "UP", "Core не готов")
        if args.expect_ai:
            check(request(args.ai, "/health")["status"] == "ok", "AI не готов")
        first = run_once(args.core, fixture, args.expect_ai, args.expect_fallback)
        second = run_once(args.core, fixture, args.expect_ai, args.expect_fallback)
        check(first == second, "Одинаковый ввод дал разную оценку")
        print("PASS: two complete 1050602 sessions produced the same result")
        return 0
    except (RuntimeError, KeyError, TypeError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
