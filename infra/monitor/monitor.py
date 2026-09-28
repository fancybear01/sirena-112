#!/usr/bin/env python3
"""Small dependency-free readiness dashboard for the isolated stack."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import socket
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


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(200, {"status": "UP", "service": "sirena-monitor"})
            return
        if self.path not in {"/", "/status", "/ready"}:
            self._json(404, {"status": "NOT_FOUND"})
            return
        payload = status_payload()
        code = 200 if self.path != "/ready" or payload["status"] == "UP" else 503
        self._json(code, payload)

    def _json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, _format: str, *_args: object) -> None:
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8099), Handler).serve_forever()
