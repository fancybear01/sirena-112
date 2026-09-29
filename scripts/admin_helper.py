#!/usr/bin/env python3
"""Loopback-only administrator helper for the local Sirena-112 stack.

The helper deliberately exposes a very small API. It authenticates every
request against Core, accepts only an allowlisted stack action and never
passes browser-provided text to a shell.
"""

from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import subprocess
import threading
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import uuid


ROOT = Path(__file__).resolve().parents[1]
ALLOWED_ACTIONS = {"start", "stop", "restart", "update"}
ALLOWED_SERVICES = {"all", "core", "ai", "media", "postgres", "asterisk", "web", "monitor"}
REQUIRED_SERVICES = ("core", "ai", "media", "postgres", "asterisk")
SERVICE_LABELS = {
    "core": "Core",
    "ai": "AI",
    "media": "Media",
    "postgres": "PostgreSQL",
    "asterisk": "Asterisk",
    "web": "Web",
    "monitor": "Monitor",
}
ACTION_LABELS = {
    "start": "Запуск",
    "stop": "Остановка",
    "restart": "Перезапуск",
    "update": "Пакетное обновление",
}
SAFE_ENV_FIELDS = (
    ("sip", "Адрес SIP", "SIRENA_BIND_ADDRESS", "127.0.0.1"),
    ("sip", "Порт SIP", "ASTERISK_SIP_PORT", "5060"),
    ("sip", "Начало диапазона RTP", "ASTERISK_RTP_PORT_START", "10000"),
    ("sip", "Конец диапазона RTP", "ASTERISK_RTP_PORT_END", "10100"),
    ("database", "База данных", "POSTGRES_DB", "sirena112"),
    ("database", "Пользователь БД", "POSTGRES_USER", "sirena112"),
    ("database", "Порт БД", "POSTGRES_PORT", "5432"),
    ("limits", "Максимальная запись, секунд", "MEDIA_RECORDING_MAX_SECONDS", "900"),
    ("limits", "Хранение записей, часов", "MEDIA_RECORDING_RETENTION_HOURS", "168"),
    ("logging", "Уровень журналирования", "LOG_LEVEL", "info"),
)
SECRET_NAMES = (
    "POSTGRES_PASSWORD",
    "CORE_BOOTSTRAP_ADMIN_PASSWORD",
    "CORE_MEDIA_SERVICE_TOKEN",
    "AI_SERVICE_TOKEN",
    "ASTERISK_ARI_PASSWORD",
    "ASTERISK_SIP_1001_PASSWORD",
    "ASTERISK_SIP_1002_PASSWORD",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def session_cookie(raw_cookie: str) -> str:
    for part in raw_cookie.split(";"):
        name, separator, value = part.strip().partition("=")
        if separator and name == "JSESSIONID" and value and len(value) <= 256:
            return f"JSESSIONID={value}"
    return ""


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def safe_configuration(root: Path = ROOT) -> dict[str, Any]:
    values = _read_dotenv(root / ".env")
    sections: dict[str, list[dict[str, str]]] = {name: [] for name in ("sip", "database", "limits", "logging")}
    for section, label, key, default in SAFE_ENV_FIELDS:
        sections[section].append({"key": key, "label": label, "value": values.get(key) or default})
    return {
        "sections": sections,
        "secrets": [{"key": key, "value": None, "note": "Значение скрыто; задаётся только в .env на сервере."}
                    for key in SECRET_NAMES],
        "backup": [
            "Остановите активные занятия и создайте дамп командой из docs/postgres-core.md.",
            "Храните backup вне каталога проекта и отдельно от файла .env.",
            "После восстановления запустите restart и проверьте health всех компонентов.",
        ],
        "editableInBrowser": False,
    }


class SystemMetrics:
    def snapshot(self) -> list[dict[str, Any]]:
        cpu = self._cpu_percent()
        memory = self._memory()
        disk = shutil.disk_usage(ROOT.anchor or ROOT)
        return [
            {"id": "cpu", "label": "CPU", "usedPercent": cpu},
            {"id": "memory", "label": "RAM", "usedPercent": memory[0],
             "usedBytes": memory[1], "totalBytes": memory[2]},
            {"id": "disk", "label": "Диск", "usedPercent": round(disk.used * 100 / disk.total, 1),
             "usedBytes": disk.used, "totalBytes": disk.total},
        ]

    def _cpu_percent(self) -> float:
        first = self._cpu_times()
        time.sleep(0.08)
        second = self._cpu_times()
        if first is None or second is None:
            try:
                return round(min(100.0, os.getloadavg()[0] * 100 / max(1, os.cpu_count() or 1)), 1)
            except (AttributeError, OSError):
                return 0.0
        idle_delta = second[0] - first[0]
        total_delta = second[1] - first[1]
        return round(max(0.0, min(100.0, (1 - idle_delta / max(1, total_delta)) * 100)), 1)

    @staticmethod
    def _cpu_times() -> tuple[int, int] | None:
        if os.name == "nt":
            idle = ctypes.c_ulonglong()
            kernel = ctypes.c_ulonglong()
            user = ctypes.c_ulonglong()
            if not ctypes.windll.kernel32.GetSystemTimes(  # type: ignore[attr-defined]
                ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
            ):
                return None
            return idle.value, kernel.value + user.value
        try:
            fields = (Path("/proc/stat").read_text(encoding="ascii").splitlines()[0].split()[1:])
            numbers = [int(value) for value in fields]
            return numbers[3] + (numbers[4] if len(numbers) > 4 else 0), sum(numbers)
        except (OSError, ValueError, IndexError):
            return None

    @staticmethod
    def _memory() -> tuple[float, int, int]:
        if os.name == "nt":
            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                    ("total_phys", ctypes.c_ulonglong), ("available_phys", ctypes.c_ulonglong),
                    ("total_page", ctypes.c_ulonglong), ("available_page", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong), ("available_virtual", ctypes.c_ulonglong),
                    ("available_extended", ctypes.c_ulonglong),
                ]
            status = MemoryStatus()
            status.length = ctypes.sizeof(MemoryStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))  # type: ignore[attr-defined]
            return float(status.load), status.total_phys - status.available_phys, status.total_phys
        try:
            fields = {}
            for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
                key, value = line.split(":", 1)
                fields[key] = int(value.strip().split()[0]) * 1024
            total = fields["MemTotal"]
            available = fields["MemAvailable"]
            used = total - available
            return round(used * 100 / total, 1), used, total
        except (OSError, ValueError, KeyError):
            return 0.0, 0, 0


def _monitor_status(monitor_url: str, opener: Callable[..., Any] = urlopen) -> tuple[dict[str, Any], str | None]:
    try:
        with opener(Request(monitor_url, headers={"Accept": "application/json"}), timeout=4) as response:
            payload = json.load(response)
        if not isinstance(payload, dict) or not isinstance(payload.get("checks"), list):
            raise ValueError("monitor returned an invalid response")
        return payload, None
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as error:
        return {"status": "DOWN", "checks": []}, f"Мониторинг недоступен: {type(error).__name__}"


def build_status(monitor_url: str, metrics: SystemMetrics | None = None,
                 opener: Callable[..., Any] = urlopen, last_action: dict[str, Any] | None = None) -> dict[str, Any]:
    monitor, monitor_error = _monitor_status(monitor_url, opener)
    checks = {str(item.get("name")): item for item in monitor.get("checks", []) if isinstance(item, dict)}
    services = []
    errors = []
    for name in REQUIRED_SERVICES:
        item = checks.get(name, {})
        status = "UP" if str(item.get("status", "DOWN")).upper() == "UP" else "DOWN"
        reason = str(item.get("reason") or item.get("reportedStatus") or "Нет ответа от компонента")
        service = {"id": name, "label": SERVICE_LABELS[name], "status": status,
                   "detail": "Готов к работе" if status == "UP" else reason}
        services.append(service)
        if status != "UP":
            errors.append({"component": name, "message": reason})
    if monitor_error:
        errors.insert(0, {"component": "monitor", "message": monitor_error})
    if last_action and last_action.get("outcome") == "FAILED":
        errors.append({"component": "control", "message": str(last_action.get("message"))})
    return {
        "status": "UP" if services and all(item["status"] == "UP" for item in services) else "DOWN",
        "updatedAt": utc_now(),
        "services": services,
        "resources": (metrics or SystemMetrics()).snapshot(),
        "errors": errors,
        "lastAction": last_action,
    }


class AuditLog:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()

    def append(self, entry: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock, self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")

    def latest(self, limit: int = 30) -> list[dict[str, Any]]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()[-limit:]
        except FileNotFoundError:
            return []
        entries = []
        for line in reversed(lines):
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    entries.append(item)
            except json.JSONDecodeError:
                continue
        return entries


class TokenStore:
    def __init__(self):
        self.tokens: dict[str, tuple[str, float]] = {}
        self.lock = threading.Lock()

    @staticmethod
    def _session_key(cookie: str) -> str:
        import hashlib
        return hashlib.sha256(cookie.encode("utf-8")).hexdigest()

    def issue(self, cookie: str) -> str:
        cookie = session_cookie(cookie)
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.tokens[self._session_key(cookie)] = (token, time.monotonic() + 600)
        return token

    def consume(self, cookie: str, candidate: str) -> bool:
        cookie = session_cookie(cookie)
        key = self._session_key(cookie)
        with self.lock:
            stored = self.tokens.pop(key, None)
        return bool(stored and stored[1] >= time.monotonic() and secrets.compare_digest(stored[0], candidate))


class CoreSessionVerifier:
    def __init__(self, core_url: str, opener: Callable[..., Any] = urlopen):
        self.core_url = core_url.rstrip("/")
        self.opener = opener
        self.cache: dict[str, tuple[dict[str, Any], float]] = {}
        self.lock = threading.Lock()

    @staticmethod
    def _session_key(cookie: str) -> str:
        import hashlib
        return hashlib.sha256(cookie.encode("utf-8")).hexdigest()

    def _cached(self, cookie: str) -> dict[str, Any] | None:
        key = self._session_key(cookie)
        with self.lock:
            cached = self.cache.get(key)
            if cached and cached[1] >= time.monotonic():
                return cached[0]
            self.cache.pop(key, None)
        return None

    def require_admin(self, cookie: str, request_id: str) -> dict[str, Any]:
        cookie = session_cookie(cookie)
        if not cookie:
            raise HelperError(HTTPStatus.UNAUTHORIZED, "Требуется вход администратора.")
        request = Request(f"{self.core_url}/api/auth/me", headers={
            "Accept": "application/json", "Cookie": cookie, "X-Request-ID": request_id,
        })
        try:
            with self.opener(request, timeout=4) as response:
                user = json.load(response)
        except HTTPError as error:
            if error.code < 500:
                status = HTTPStatus.FORBIDDEN if error.code == 403 else HTTPStatus.UNAUTHORIZED
                raise HelperError(status, "Сессия администратора недействительна.") from error
            user = self._cached(cookie)
            if user is None:
                raise HelperError(HTTPStatus.SERVICE_UNAVAILABLE, "Core недоступен для проверки прав.") from error
        except (URLError, TimeoutError, ValueError, OSError) as error:
            user = self._cached(cookie)
            if user is None:
                raise HelperError(HTTPStatus.SERVICE_UNAVAILABLE, "Core недоступен для проверки прав.") from error
        if not isinstance(user, dict) or user.get("role") != "ADMIN":
            raise HelperError(HTTPStatus.FORBIDDEN, "Операция доступна только администратору.")
        principal = {"username": str(user.get("username") or "admin"), "role": "ADMIN"}
        with self.lock:
            self.cache[self._session_key(cookie)] = (principal, time.monotonic() + 900)
        return principal


class HelperError(Exception):
    def __init__(self, status: HTTPStatus, message: str):
        super().__init__(message)
        self.status = status


def command_for(action: str, service: str, root: Path = ROOT) -> list[str]:
    if action not in ALLOWED_ACTIONS:
        raise HelperError(HTTPStatus.BAD_REQUEST, "Команда не входит в разрешённый список.")
    if service not in ALLOWED_SERVICES:
        raise HelperError(HTTPStatus.BAD_REQUEST, "Компонент не входит в разрешённый список.")
    if action == "update" and service != "all":
        raise HelperError(HTTPStatus.BAD_REQUEST, "Пакетное обновление выполняется только для всего комплекса.")
    if platform.system() == "Windows":
        command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                   str(root / "scripts" / "stack.ps1"), "-Action", action]
        if service != "all":
            command += ["-Service", service]
        return command
    command = ["bash", str(root / "scripts" / "stack.sh"), action]
    if service != "all":
        command += ["--service", service]
    return command


class StackController:
    def __init__(self, audit: AuditLog, runner: Callable[..., Any] = subprocess.run, root: Path = ROOT):
        self.audit = audit
        self.runner = runner
        self.root = root
        self.lock = threading.Lock()
        self.last_action: dict[str, Any] | None = None

    def execute(self, action: str, service: str, actor: str, request_id: str) -> dict[str, Any]:
        command = command_for(action, service, self.root)
        if not self.lock.acquire(blocking=False):
            raise HelperError(HTTPStatus.CONFLICT, "Другая управляющая команда ещё выполняется.")
        started = utc_now()
        entry = {"id": str(uuid.uuid4()), "timestamp": started, "actor": actor, "action": action,
                 "service": service, "outcome": "STARTED", "requestId": request_id}
        self.audit.append(entry)
        try:
            completed = self.runner(command, cwd=self.root, capture_output=True, text=True,
                                    timeout=900, shell=False)
            success = completed.returncode == 0
            result = {**entry, "timestamp": utc_now(), "outcome": "OK" if success else "FAILED",
                      "message": "Команда выполнена." if success else f"Команда завершилась с кодом {completed.returncode}."}
            self.audit.append(result)
            self.last_action = result
            if not success:
                raise HelperError(HTTPStatus.BAD_GATEWAY, result["message"])
            return result
        except subprocess.TimeoutExpired as error:
            result = {**entry, "timestamp": utc_now(), "outcome": "FAILED",
                      "message": "Превышено время ожидания управляющей команды."}
            self.audit.append(result)
            self.last_action = result
            raise HelperError(HTTPStatus.GATEWAY_TIMEOUT, result["message"]) from error
        except OSError as error:
            result = {**entry, "timestamp": utc_now(), "outcome": "FAILED",
                      "message": "Не удалось запустить локальную управляющую команду."}
            self.audit.append(result)
            self.last_action = result
            raise HelperError(HTTPStatus.BAD_GATEWAY, result["message"]) from error
        finally:
            self.lock.release()


class AdminHelperServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], *, verifier: CoreSessionVerifier, monitor_url: str,
                 audit: AuditLog, controller: StackController, metrics: SystemMetrics | None = None):
        super().__init__(address, AdminHelperHandler)
        self.verifier = verifier
        self.monitor_url = monitor_url
        self.audit = audit
        self.controller = controller
        self.metrics = metrics or SystemMetrics()
        self.tokens = TokenStore()


class AdminHelperHandler(BaseHTTPRequestHandler):
    server: AdminHelperServer
    protocol_version = "HTTP/1.1"

    def do_OPTIONS(self) -> None:
        if not self._origin_allowed():
            self._json(HTTPStatus.FORBIDDEN, {"message": "Недопустимый источник запроса."})
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(HTTPStatus.OK, {"status": "UP", "service": "sirena-admin-helper"})
            return
        try:
            user, _ = self._admin()
            if self.path == "/api/status":
                self._json(HTTPStatus.OK, build_status(self.server.monitor_url, self.server.metrics,
                                                       last_action=self.server.controller.last_action))
            elif self.path == "/api/configuration":
                self._json(HTTPStatus.OK, safe_configuration())
            elif self.path == "/api/audit":
                self._json(HTTPStatus.OK, {"entries": self.server.audit.latest()})
            elif self.path == "/api/csrf":
                cookie = self.headers.get("Cookie", "")
                self._json(HTTPStatus.OK, {"token": self.server.tokens.issue(cookie),
                                           "headerName": "X-Admin-CSRF", "actor": user.get("username")})
            else:
                self._json(HTTPStatus.NOT_FOUND, {"message": "Ресурс не найден."})
        except HelperError as error:
            self._json(error.status, {"message": str(error)})

    def do_POST(self) -> None:
        try:
            if self.path != "/api/actions":
                raise HelperError(HTTPStatus.NOT_FOUND, "Ресурс не найден.")
            if not self._origin_allowed():
                raise HelperError(HTTPStatus.FORBIDDEN, "Недопустимый источник запроса.")
            user, request_id = self._admin()
            cookie = self.headers.get("Cookie", "")
            if not self.server.tokens.consume(cookie, self.headers.get("X-Admin-CSRF", "")):
                raise HelperError(HTTPStatus.FORBIDDEN, "Защитный токен отсутствует или устарел.")
            body = self._body()
            if body.get("confirmed") is not True:
                raise HelperError(HTTPStatus.BAD_REQUEST, "Нужно явное подтверждение команды.")
            action = body.get("action")
            service = body.get("service", "all")
            if not isinstance(action, str) or not isinstance(service, str):
                raise HelperError(HTTPStatus.BAD_REQUEST, "Некорректный формат команды.")
            result = self.server.controller.execute(action, service, str(user.get("username", "admin")), request_id)
            self._json(HTTPStatus.OK, result)
        except HelperError as error:
            self._json(error.status, {"message": str(error)})

    def _admin(self) -> tuple[dict[str, Any], str]:
        request_id = self.headers.get("X-Request-ID") or str(uuid.uuid4())
        return self.server.verifier.require_admin(self.headers.get("Cookie", ""), request_id), request_id

    def _body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise HelperError(HTTPStatus.BAD_REQUEST, "Некорректный размер запроса.") from error
        if length <= 0 or length > 16_384:
            raise HelperError(HTTPStatus.BAD_REQUEST, "Некорректный размер запроса.")
        try:
            body = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise HelperError(HTTPStatus.BAD_REQUEST, "Ожидается JSON.") from error
        if not isinstance(body, dict):
            raise HelperError(HTTPStatus.BAD_REQUEST, "Ожидается объект JSON.")
        return body

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin", "")
        return bool(re.fullmatch(r"https?://(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?", origin))

    def _cors_headers(self) -> None:
        origin = self.headers.get("Origin", "")
        if self._origin_allowed():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Admin-CSRF, X-Request-ID")
            self.send_header("Vary", "Origin")

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status.value)
        self._cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def default_state_dir() -> Path:
    if os.name == "nt":
        root = Path(os.getenv("LOCALAPPDATA", Path.home()))
    else:
        root = Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return root / "sirena-112"


def parse_args() -> argparse.Namespace:
    values = _read_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Локальный helper администрирования Sirena-112")
    parser.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1",))
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--core-url", default=f"http://127.0.0.1:{values.get('CORE_PORT', '8080')}")
    parser.add_argument("--monitor-url", default=f"http://127.0.0.1:{values.get('MONITOR_PORT', '8099')}/status")
    parser.add_argument("--audit-file", type=Path, default=default_state_dir() / "admin-actions.jsonl")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    audit = AuditLog(args.audit_file)
    controller = StackController(audit)
    server = AdminHelperServer((args.host, args.port), verifier=CoreSessionVerifier(args.core_url),
                               monitor_url=args.monitor_url, audit=audit, controller=controller)
    print(f"Sirena-112 admin helper: http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
