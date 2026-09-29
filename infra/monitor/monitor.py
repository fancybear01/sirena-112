#!/usr/bin/env python3
"""Small dependency-free readiness dashboard for the isolated stack."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import socket
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _http_check(name: str, url: str, expected: str, headers: dict[str, str] | None = None) -> dict:
    try:
        request = Request(url, headers=headers or {})
        with urlopen(request, timeout=3) as response:
            payload = json.load(response)
        actual = str(payload.get("status", ""))
        ok = not expected or actual.upper() == expected.upper()
        result = {"name": name, "status": "UP" if ok else "DOWN", "reportedStatus": actual}
        if name == "ai":
            result.update(
                speech=payload.get("speech"),
                speechAvailable=payload.get("speechAvailable"),
                speechSimulated=payload.get("speechSimulated"),
            )
            if _truthy(os.getenv("AI_REQUIRE_REAL_SPEECH")):
                ok = bool(payload.get("speechAvailable")) and not bool(payload.get("speechSimulated"))
                result["status"] = "UP" if ok else "DOWN"
                if not ok:
                    result["reason"] = "real_speech_models_unavailable"
        return result
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as error:
        return {"name": name, "status": "DOWN", "reason": str(error)[:240]}


def _tcp_check(name: str, host: str, port: int) -> dict:
    try:
        with socket.create_connection((host, port), timeout=3):
            return {"name": name, "status": "UP"}
    except OSError as error:
        return {"name": name, "status": "DOWN", "reason": str(error)[:240]}


def _asterisk_headers() -> dict[str, str]:
    raw = "{user}:{password}".format(
        user=os.getenv("ASTERISK_ARI_USER", ""),
        password=os.getenv("ASTERISK_ARI_PASSWORD", ""),
    ).encode("utf-8")
    return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}


def status_payload() -> dict:
    checks = [
        _tcp_check("postgres", "postgres", 5432),
        _http_check("asterisk", "http://asterisk:8088/ari/asterisk/info", "", _asterisk_headers()),
        _http_check("ai", "http://ai:8090/health", "ok"),
        _http_check("media", "http://media:8091/ready", "ready"),
        _http_check("core", "http://core:8080/actuator/health/readiness", "UP"),
        _http_check("web", "http://web:8080/health", "ok"),
    ]
    # ARI returns build/system metadata rather than a status field. A successful
    # authenticated JSON response is the readiness signal.
    asterisk = next(item for item in checks if item["name"] == "asterisk")
    if "reason" not in asterisk:
        asterisk["status"] = "UP"
    ready = all(item["status"] == "UP" for item in checks)
    return {
        "status": "UP" if ready else "DOWN",
        "service": "sirena-monitor",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "checks": checks,
    }


def prometheus_payload(payload: dict) -> str:
    """Тот же статус в текстовом формате Prometheus. Задача #95.

    Формат выбран потому, что его читают все распространённые системы
    мониторинга - Prometheus, VictoriaMetrics, Zabbix через HTTP-агент.
    Так интеграция не привязана к одному закрытому продукту: заказчику
    достаточно настроить сбор с этого адреса.

    Названия метрик и метки не меняются между версиями: на них настраивают
    оповещения, и переименование ломает чужие настройки молча.
    """
    lines = [
        "# HELP sirena_up Готовность стенда целиком: 1 готов, 0 нет.",
        "# TYPE sirena_up gauge",
        "sirena_up %d" % (1 if payload["status"] == "UP" else 0),
        "# HELP sirena_component_up Готовность отдельного компонента.",
        "# TYPE sirena_component_up gauge",
    ]
    for check in payload["checks"]:
        lines.append('sirena_component_up{component="%s"} %d'
                     % (check["name"], 1 if check["status"] == "UP" else 0))

    speech = next((c for c in payload["checks"] if c["name"] == "ai"), None)
    if speech is not None and "speechAvailable" in speech:
        lines += [
            "# HELP sirena_speech_real Работают настоящие речевые модели, а не подмены.",
            "# TYPE sirena_speech_real gauge",
            "sirena_speech_real %d" % (
                1 if speech.get("speechAvailable") and not speech.get("speechSimulated") else 0),
        ]
    return "\n".join(lines) + "\n"


def push_status(payload: dict) -> dict:
    """Отправляет статус во внешнюю систему мониторинга. Задача #95.

    Адаптер заменяемый: адрес и заголовок авторизации задаются окружением,
    никакого конкретного продукта в коде нет. Выключен по умолчанию -
    автономный контур не должен зависеть от внешней системы.

    Ошибку не проглатывает: возвращает результат с requestId, чтобы сбой
    интеграции было видно в журнале, а не только по отсутствию данных
    на другой стороне.
    """
    url = os.getenv("MONITOR_PUSH_URL", "").strip()
    request_id = str(uuid.uuid4())
    if not url:
        return {"delivered": False, "reason": "push_disabled", "requestId": request_id}

    headers = {"Content-Type": "application/json", "X-Request-Id": request_id}
    token = os.getenv("MONITOR_PUSH_TOKEN", "").strip()
    if token:
        # Заголовки HTTP не переносят символы вне latin-1. Без этой проверки
        # токен с кириллицей давал ошибку кодека вместо внятного сообщения,
        # и разбираться пришлось бы долго.
        try:
            token.encode("latin-1")
        except UnicodeEncodeError:
            return {"delivered": False,
                    "reason": "MONITOR_PUSH_TOKEN содержит символы, недопустимые в заголовке HTTP",
                    "requestId": request_id}
        headers["Authorization"] = "Bearer " + token

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        request = Request(url, data=body, headers=headers, method="POST")
        with urlopen(request, timeout=float(os.getenv("MONITOR_PUSH_TIMEOUT", "5"))) as response:
            return {"delivered": True, "status": response.status, "requestId": request_id}
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as error:
        code = getattr(error, "code", None)
        result = {"delivered": False, "reason": str(error)[:240], "requestId": request_id}
        if code is not None:
            result["status"] = code
        print(json.dumps({"level": "WARN", "event": "monitor_push_failed", **result},
                         ensure_ascii=False), flush=True)
        return result


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(200, {"status": "UP", "service": "sirena-monitor"})
            return
        if self.path == "/metrics":
            self._text(200, prometheus_payload(status_payload()))
            return
        if self.path not in {"/", "/status", "/ready"}:
            self._json(404, {"status": "NOT_FOUND"})
            return
        payload = status_payload()
        code = 200 if self.path != "/ready" or payload["status"] == "UP" else 503
        self._json(code, payload)

    def do_POST(self) -> None:
        # Отправку статуса наружу инициирует администратор или планировщик:
        # сам монитор наружу по расписанию не стучится, чтобы автономный
        # контур не зависел от внешней системы.
        if self.path != "/push":
            self._json(404, {"status": "NOT_FOUND"})
            return
        result = push_status(status_payload())
        # Выключенная отправка - это состояние настройки, а не сбой шлюза,
        # поэтому 200 с delivered=false. 502 остаётся для настоящего отказа
        # внешней системы: по нему администратор поймёт, что дело не у нас.
        if result.get("reason") == "push_disabled":
            self._json(200, result)
            return
        self._json(200 if result["delivered"] else 502, result)

    def _json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _text(self, status: int, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        # Версия 0.0.4 указана намеренно: это формат, который умеют читать
        # все распространённые системы сбора.
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, _format: str, *_args: object) -> None:
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8099), Handler).serve_forever()
