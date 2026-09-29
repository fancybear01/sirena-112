"""Контракт интеграции с мониторингом заказчика. Задача #95.

Проверяется то, на что заказчик будет настраивать сбор и оповещения:

- формат метрик и неизменность названий - на них настраивают алерты,
  и переименование ломает чужие настройки молча;
- отправка статуса наружу против поддельного сервера: заголовки, тело,
  авторизация;
- поведение при отказе внешней системы - автономный контур не должен
  от неё зависеть.

Реального стенда заказчика нет, поэтому сквозной тест невозможен. Это
зафиксировано как внешняя блокировка в docs/monitoring-integration.md,
а не замаскировано зелёным тестом.

Запуск:

    python -m pytest infra/monitor/test_monitor.py -q
"""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import monitor  # noqa: E402

UP = {
    "status": "UP",
    "service": "sirena-monitor",
    "timestamp": "2026-09-29T18:00:00Z",
    "checks": [
        {"name": "postgres", "status": "UP"},
        {"name": "core", "status": "UP"},
        {"name": "ai", "status": "UP", "speech": "vosk+piper",
         "speechAvailable": True, "speechSimulated": False},
    ],
}

DOWN = {
    "status": "DOWN",
    "service": "sirena-monitor",
    "timestamp": "2026-09-29T18:00:00Z",
    "checks": [
        {"name": "postgres", "status": "UP"},
        {"name": "core", "status": "DOWN", "reason": "connection refused"},
        {"name": "ai", "status": "DOWN", "speech": "unavailable+unavailable",
         "speechAvailable": False, "speechSimulated": True,
         "reason": "real_speech_models_unavailable"},
    ],
}


# --- формат метрик ------------------------------------------------------------


def test_metrics_report_stack_state():
    text = monitor.prometheus_payload(UP)

    assert "sirena_up 1" in text
    assert 'sirena_component_up{component="core"} 1' in text
    assert 'sirena_component_up{component="postgres"} 1' in text


def test_metrics_report_failure():
    text = monitor.prometheus_payload(DOWN)

    assert "sirena_up 0" in text
    assert 'sirena_component_up{component="core"} 0' in text
    # Работающий компонент рядом с упавшим обязан остаться единицей,
    # иначе по метрике не понять, что именно сломалось.
    assert 'sirena_component_up{component="postgres"} 1' in text


def test_metrics_tell_real_speech_from_stubs():
    """Подмену речи видно в мониторинге: на демонстрации это первое, что важно."""
    assert "sirena_speech_real 1" in monitor.prometheus_payload(UP)
    assert "sirena_speech_real 0" in monitor.prometheus_payload(DOWN)


def test_metric_names_are_documented_ones():
    """Названия метрик - часть контракта, менять их нельзя без согласования.

    Тест намеренно перечисляет их списком: если кто-то переименует метрику,
    у заказчика молча перестанут работать оповещения, а тест об этом скажет.
    """
    text = monitor.prometheus_payload(UP)
    for name in ("sirena_up", "sirena_component_up", "sirena_speech_real"):
        assert "# TYPE %s gauge" % name in text, name
        assert "# HELP %s " % name in text, name


def test_metrics_format_is_parseable():
    """Каждая строка - либо комментарий, либо имя со значением."""
    for line in monitor.prometheus_payload(DOWN).strip().splitlines():
        if line.startswith("#"):
            continue
        name, _, value = line.rpartition(" ")
        assert name, line
        assert value in ("0", "1"), line


# --- отправка наружу ----------------------------------------------------------


class FakeMonitoring:
    """Поддельная система мониторинга заказчика."""

    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.received = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                outer.received.append({
                    "path": self.path,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": json.loads(body) if body else None,
                })
                self.send_response(outer.status)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *_args) -> None:
                return

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d/ingest" % self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "FakeMonitoring":
        self.thread.start()
        return self

    def __exit__(self, *_args) -> None:
        self.server.shutdown()
        self.server.server_close()


def test_push_delivers_status_and_marks_request(monkeypatch):
    with FakeMonitoring() as fake:
        monkeypatch.setenv("MONITOR_PUSH_URL", fake.url)
        monkeypatch.delenv("MONITOR_PUSH_TOKEN", raising=False)

        result = monitor.push_status(UP)

        assert result["delivered"] is True
        assert result["status"] == 200
        assert len(fake.received) == 1
        sent = fake.received[0]
        assert sent["body"]["status"] == "UP"
        assert sent["headers"]["content-type"].startswith("application/json")
        # requestId уходит заголовком и возвращается в результате: иначе сбой
        # не сопоставить с записью в журнале.
        assert sent["headers"]["x-request-id"] == result["requestId"]


def test_push_sends_token_when_configured(monkeypatch):
    with FakeMonitoring() as fake:
        monkeypatch.setenv("MONITOR_PUSH_URL", fake.url)
        monkeypatch.setenv("MONITOR_PUSH_TOKEN", "stand-secret-123")

        monitor.push_status(UP)

        assert fake.received[0]["headers"]["authorization"] == "Bearer stand-secret-123"


def test_push_is_off_without_url(monkeypatch):
    """Без адреса отправки ничего не происходит, и это не ошибка.

    Автономный контур - основной режим, и он не должен зависеть от внешней
    системы мониторинга.
    """
    monkeypatch.delenv("MONITOR_PUSH_URL", raising=False)

    result = monitor.push_status(UP)

    assert result["delivered"] is False
    assert result["reason"] == "push_disabled"
    assert result["requestId"]


def test_push_reports_refusal_of_external_system(monkeypatch):
    with FakeMonitoring(status=503) as fake:
        monkeypatch.setenv("MONITOR_PUSH_URL", fake.url)

        result = monitor.push_status(UP)

        assert result["delivered"] is False
        assert result["status"] == 503
        assert result["requestId"]


def test_push_survives_unreachable_system(monkeypatch):
    """Недоступная система заказчика не должна ронять монитор."""
    monkeypatch.setenv("MONITOR_PUSH_URL", "http://127.0.0.1:9/ingest")
    monkeypatch.setenv("MONITOR_PUSH_TIMEOUT", "1")

    result = monitor.push_status(UP)

    assert result["delivered"] is False
    assert result["reason"]
    assert result["requestId"]


def test_push_does_not_leak_token_into_result(monkeypatch):
    """Секрет не должен попасть ни в результат, ни в журнал."""
    with FakeMonitoring(status=500) as fake:
        monkeypatch.setenv("MONITOR_PUSH_URL", fake.url)
        monkeypatch.setenv("MONITOR_PUSH_TOKEN", "stand-secret-123")

        result = monitor.push_status(UP)

        assert "stand-secret-123" not in json.dumps(result, ensure_ascii=False)


def test_bad_token_gives_readable_reason(monkeypatch):
    """Токен с кириллицей - ошибка настройки, и сказать о ней надо словами.

    Заголовки HTTP не переносят символы вне latin-1. До проверки здесь
    вылезала ошибка кодека, по которой причину было не угадать.
    """
    monkeypatch.setenv("MONITOR_PUSH_URL", "http://127.0.0.1:9/ingest")
    monkeypatch.setenv("MONITOR_PUSH_TOKEN", "секрет-с-кириллицей")

    result = monitor.push_status(UP)

    assert result["delivered"] is False
    assert "заголовке HTTP" in result["reason"]
    assert "секрет" not in result["reason"]


@pytest.mark.parametrize("payload", [UP, DOWN])
def test_push_sends_checks_without_changing_them(monkeypatch, payload):
    """Наружу уходит тот же статус, что отдаётся на /status.

    Если бы отправка что-то дорабатывала по пути, у заказчика и у нас были
    бы разные данные об одном и том же стенде.
    """
    with FakeMonitoring() as fake:
        monkeypatch.setenv("MONITOR_PUSH_URL", fake.url)

        monitor.push_status(payload)

        assert fake.received[0]["body"] == payload
