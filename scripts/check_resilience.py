#!/usr/bin/env python3
"""Destructive local acceptance check for issue #92 (stdlib only).

The script expects the resilience Compose overlay to be running. It never
deletes volumes: stopped or crashed services are restored in ``finally``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "contracts" / "examples" / "scenario-1050602.json"
COMPOSE = ("docker", "compose", "-f", "compose.yaml", "-f", "compose.resilience.yaml")
STACK_SERVICES = ("postgres", "ai", "asterisk", "media", "core", "core-2", "core-gateway", "web", "monitor")


class CheckFailed(RuntimeError):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailed(message)


def command(arguments: list[str] | tuple[str, ...], *, check_result: bool = True) -> str:
    completed = subprocess.run(
        list(arguments), cwd=ROOT, capture_output=True, text=True, timeout=300, shell=False
    )
    if check_result and completed.returncode != 0:
        details = (completed.stderr or completed.stdout).strip()
        raise CheckFailed(f"Команда {' '.join(arguments)} завершилась с кодом "
                          f"{completed.returncode}: {details[-1200:]}")
    return completed.stdout.strip()


def compose(*arguments: str, check_result: bool = True) -> str:
    return command((*COMPOSE, *arguments), check_result=check_result)


def request(base: str, path: str, method: str = "GET", body: dict | None = None,
            timeout: float = 8) -> dict | list:
    payload = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = Request(base.rstrip("/") + path, data=payload, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise CheckFailed(f"{method} {path}: HTTP {error.code}: {details[:500]}") from error
    except (URLError, TimeoutError, OSError) as error:
        raise CheckFailed(f"{method} {path}: {error}") from error


def wait_until(label: str, predicate: Callable[[], bool], timeout: float = 30) -> float:
    started = time.monotonic()
    last_error: Exception | None = None
    while time.monotonic() - started <= timeout:
        try:
            if predicate():
                return time.monotonic() - started
        except Exception as error:  # noqa: BLE001 - preserve the last diagnostic
            last_error = error
        time.sleep(0.5)
    suffix = f": {last_error}" if last_error else ""
    raise CheckFailed(f"{label}: превышен лимит {timeout:.0f} с{suffix}")


def container_id(service: str) -> str:
    value = compose("ps", "-a", "-q", service)
    check(bool(value), f"Контейнер {service} не найден")
    return value.splitlines()[0]


def inspect_value(service: str, template: str) -> str:
    return command(("docker", "inspect", "--format", template, container_id(service)))


def wait_healthy(service: str, timeout: float = 30) -> float:
    return wait_until(
        f"{service} не стал healthy",
        lambda: inspect_value(service, "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}")
        in {"healthy", "running"},
        timeout,
    )


def crash_and_recover(service: str) -> tuple[float, str]:
    container = container_id(service)
    policy = command(("docker", "inspect", "--format",
                      "{{.HostConfig.RestartPolicy.Name}}:{{.HostConfig.RestartPolicy.MaximumRetryCount}}",
                      container))
    check(policy == "on-failure:5", f"{service}: ожидалась restart-policy on-failure:5, получено {policy}")
    before = int(command(("docker", "inspect", "--format", "{{.RestartCount}}", container)))
    started = time.monotonic()
    # PID 1 is terminated from inside the container so Docker treats this as a
    # process exit, not an operator-issued `docker stop`. Linux PID 1 ignores
    # an unhandled SIGKILL from its own namespace. TERM lets the service expose
    # whether this is an abnormal exit (automatic restart) or a clean shutdown.
    signal = "INT" if service == "postgres" else "TERM"
    compose("exec", "-T", service, "sh", "-c", f"kill -{signal} 1", check_result=False)

    def restarted_and_healthy() -> bool:
        return int(command(("docker", "inspect", "--format", "{{.RestartCount}}", container))) > before and command((
            "docker", "inspect", "--format",
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}", container,
        )) in {"healthy", "running"}

    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        if restarted_and_healthy():
            return time.monotonic() - started, "automatic"
        state = command(("docker", "inspect", "--format", "{{.State.Status}}", container))
        count = int(command(("docker", "inspect", "--format", "{{.RestartCount}}", container)))
        if state == "exited" and count == before:
            break
        time.sleep(0.5)

    # Some runtimes (notably Uvicorn and PostgreSQL) handle TERM and exit
    # cleanly, so on-failure correctly does not fire. Policy is verified
    # above; start the cleanly stopped service to measure readiness without
    # misreporting it as an automatic crash recovery.
    compose("start", service)
    remaining = max(1.0, 30 - (time.monotonic() - started))
    wait_healthy(service, remaining)
    return time.monotonic() - started, "clean-exit-manual-start"


def unique_event_ids(session_id: str) -> list[str]:
    # The REST /events endpoint is intentionally limited to voice sessions;
    # card events are still persisted in the shared session_events table and
    # delivered by the common WebSocket endpoint.
    output = compose(
        "exec", "-T", "postgres", "psql", "-U", "sirena112", "-d", "sirena112",
        "-tAc", f"SELECT event_id FROM session_events WHERE session_id = '{session_id}' ORDER BY occurred_at, event_id",
    )
    ids = [line.strip() for line in output.splitlines() if line.strip()]
    check(bool(ids), "В PostgreSQL нет событий проверяемой сессии")
    check(len(ids) == len(set(ids)), "После восстановления появились дубли eventId")
    return ids


def start_card(base: str, fixture: dict) -> tuple[str, dict, int]:
    scenario_id = fixture["id"]
    scenarios = request(base, "/api/teacher/scenarios")
    check(any(item["id"] == scenario_id for item in scenarios), "Сценарий 1050602 недоступен")
    session = request(base, "/api/teacher/sessions", "POST", {"scenarioId": scenario_id})
    session_id = str(session["id"])
    started = request(base, f"/api/teacher/sessions/{session_id}/start", "POST")
    check(started["state"] == "ACTIVE", "Сессия не перешла в ACTIVE")
    input_data = fixture["groundTruth"]["expectedInput"]
    draft = request(base, f"/api/student/sessions/{session_id}/card", "PATCH", {
        "input": input_data,
        "expectedRevision": 0,
    })
    check(draft["cardRevision"] == 1, "Черновик карточки не сохранён в ревизии 1")
    return session_id, input_data, int(draft["cardRevision"])


def finish_card(base: str, session_id: str, input_data: dict, revision: int) -> dict:
    draft = request(base, f"/api/student/sessions/{session_id}/card", "PATCH", {
        "input": input_data,
        "expectedRevision": revision,
    })
    report = request(base, f"/api/student/sessions/{session_id}/submit", "POST", {
        "input": input_data,
        "expectedRevision": draft["cardRevision"],
    })
    check(report["sessionId"] == session_id, "После reconnect получен отчёт другой сессии")
    check(bool(report["criteria"]), "После reconnect отчёт не содержит критериев")
    return report


def disconnect_web(duration: int, web_base: str, session_id: str) -> float:
    web_container = container_id("web")
    networks = json.loads(command(("docker", "inspect", "--format", "{{json .NetworkSettings.Networks}}",
                                   web_container)))
    check(bool(networks), "У Web нет Compose-сети")
    network = next(iter(networks))
    aliases = [str(value) for value in networks[network].get("Aliases", []) if value]
    command(("docker", "network", "disconnect", network, web_container))
    started = time.monotonic()
    try:
        unavailable = False
        try:
            request(web_base, f"/api/student/sessions/{session_id}", timeout=3)
        except CheckFailed:
            unavailable = True
        check(unavailable, "Разрыв сети не изолировал Web от Core")
        remaining = duration - (time.monotonic() - started)
        if remaining > 0:
            time.sleep(remaining)
    finally:
        connect = ["docker", "network", "connect"]
        for alias in aliases:
            connect.extend(("--alias", alias))
        connect.extend((network, web_container))
        command(connect, check_result=False)
    return time.monotonic() - started


def wait_session(base: str, session_id: str, expected_state: str | None = None) -> float:
    def available() -> bool:
        payload = request(base, f"/api/student/sessions/{session_id}", timeout=3)
        return expected_state is None or payload.get("state") == expected_state

    return wait_until("Сессия не восстановилась", available, 30)


def restore_stack() -> None:
    for service in STACK_SERVICES:
        try:
            container = container_id(service)
            status = command(("docker", "inspect", "--format", "{{.State.Status}}", container))
            health = command(("docker", "inspect", "--format",
                              "{{if .State.Health}}{{.State.Health.Status}}{{end}}", container))
            if status == "running" and health == "unhealthy":
                compose("restart", service, check_result=False)
            elif status != "running":
                compose("start", service, check_result=False)
        except (CheckFailed, ValueError, subprocess.TimeoutExpired):
            pass
    compose(
        "up", "--detach", "--wait", "--wait-timeout", "180", "--no-build",
        *STACK_SERVICES,
        check_result=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web", default="http://127.0.0.1:5173")
    parser.add_argument("--core-primary", default="http://127.0.0.1:8080")
    parser.add_argument("--network-outage-seconds", type=int, default=30)
    parser.add_argument("--skip-network-outage", action="store_true",
                        help="Skip only the already-proven 30-second stage during local debugging")
    args = parser.parse_args()
    check(args.skip_network_outage or args.network_outage_seconds >= 30,
          "Приёмочный разрыв сети должен длиться не менее 30 секунд")
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    measurements: dict[str, float] = {}
    recovery_modes: dict[str, str] = {}

    try:
        restore_stack()
        check(request(args.web, "/health")["status"] == "ok", "Web не готов")
        session_id, input_data, revision = start_card(args.web, fixture)
        event_ids_before = unique_event_ids(session_id)

        if not args.skip_network_outage:
            measurements["networkOutageSeconds"] = disconnect_web(
                args.network_outage_seconds, args.web, session_id
            )
            measurements["webReconnectSeconds"] = wait_session(args.web, session_id, "ACTIVE")
        report = finish_card(args.web, session_id, input_data, revision)
        event_ids_after = unique_event_ids(session_id)
        check(set(event_ids_before).issubset(event_ids_after), "После reconnect потеряны старые события")

        # With primary stopped, the same PostgreSQL-backed session must be read
        # and scored through the secondary node. The alert proves the failure is
        # visible instead of triggering an unbounded restart loop.
        compose("stop", "core")
        measurements["secondaryFailoverSeconds"] = wait_session(args.web, session_id, "SCORED")
        check(request(args.web, f"/api/teacher/sessions/{session_id}/report") == report,
              "Второй Core вернул другой результат")
        compose("start", "core")
        wait_healthy("core")

        compose("stop", "core-2")
        measurements["primaryFailoverSeconds"] = wait_session(args.web, session_id, "SCORED")
        check(request(args.core_primary, f"/api/teacher/sessions/{session_id}/report") == report,
              "Первый Core потерял результат после переключения")
        compose("start", "core-2")
        wait_healthy("core-2")

        compose("restart", "core", "core-2")
        measurements["coreRestartSeconds"] = wait_session(args.web, session_id, "SCORED")
        check(unique_event_ids(session_id) == event_ids_after,
              "Перезапуск Core изменил журнал или создал дубли")

        for service in ("core", "ai", "media", "postgres"):
            elapsed, mode = crash_and_recover(service)
            measurements[f"{service}CrashRecoverySeconds"] = elapsed
            recovery_modes[service] = mode
            wait_session(args.web, session_id, "SCORED")
            check(request(args.web, f"/api/teacher/sessions/{session_id}/report") == report,
                  f"После отказа {service} потерян результат")

        check(all(value <= 30 for key, value in measurements.items() if key != "networkOutageSeconds"),
              "Один из этапов восстановления превысил 30 секунд")
        print(json.dumps({
            "status": "PASS",
            "sessionId": session_id,
            "eventCount": len(event_ids_after),
            "measurements": {key: round(value, 3) for key, value in measurements.items()},
            "recoveryModes": recovery_modes,
        }, ensure_ascii=False, indent=2))
        return 0
    except (CheckFailed, KeyError, TypeError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    finally:
        restore_stack()


if __name__ == "__main__":
    raise SystemExit(main())
