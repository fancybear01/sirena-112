#!/usr/bin/env python3
"""One real offline voice turn through Core, Media, Asterisk, RTP and AI."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request(
    base: str,
    path: str,
    method: str = "GET",
    body: dict | None = None,
    token: str | None = None,
) -> dict | list:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = Request(base.rstrip("/") + path, data=payload, method=method, headers=headers)
    try:
        with urlopen(req, timeout=15) as response:
            return json.load(response)
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path}: HTTP {error.code}: {details}") from error
    except URLError as error:
        raise RuntimeError(f"{method} {path}: {error.reason}") from error


def check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def wait_for(description: str, timeout: float, probe):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = probe()
        if last:
            return last
        time.sleep(0.5)
    raise RuntimeError(f"Не дождались: {description}; последнее состояние: {last!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", default="http://127.0.0.1:8080")
    parser.add_argument("--ai", default="http://127.0.0.1:8090")
    parser.add_argument("--media", default="http://127.0.0.1:8091")
    parser.add_argument("--media-token", default=os.getenv("CORE_MEDIA_SERVICE_TOKEN", ""))
    parser.add_argument("--sip-address", default="PJSIP/smoke-out")
    args = parser.parse_args()

    session_id = None
    call_id = None
    try:
        ai = request(args.ai, "/ready")
        check(ai.get("status") == "ready", f"AI не готов: {ai}")
        check(ai.get("speechAvailable") is True, "AI не загрузил речевые модели")
        check(ai.get("speechSimulated") is False, "AI использует речевую подмену")
        check(request(args.media, "/ready").get("status") == "ready", "Media/Asterisk не готовы")
        check(bool(args.media_token), "Для voice smoke нужен CORE_MEDIA_SERVICE_TOKEN")

        session = request(args.core, "/api/teacher/sessions", "POST", {"mode": "VOICE"})
        session_id = session["id"]
        call = request(
            args.core,
            f"/api/teacher/sessions/{session_id}/call/start",
            "POST",
            {"sipAddress": args.sip_address},
        )
        call_id = call["callId"]
        check(call.get("aiSessionId"), "Core не вернул aiSessionId")

        def active():
            current = request(args.core, f"/api/teacher/sessions/{session_id}")
            return current if current.get("state") == "ACTIVE" else None

        wait_for("голосовая сессия ACTIVE", 30, active)
        # The loopback endpoint waits two seconds and then plays a synthetic
        # operator phrase. Five seconds lets the whole phrase reach Media.
        time.sleep(5)
        request(
            args.media,
            f"/internal/v1/calls/{call_id}/input/flush",
            "POST",
            token=args.media_token,
        )

        def transcript():
            events = request(args.core, f"/api/teacher/sessions/{session_id}/events")
            for event in events:
                if event.get("type") != "transcript.final":
                    continue
                payload = event.get("payload") or {}
                if payload.get("text") and payload.get("simulated") is False:
                    return event
            return None

        transcript_event = wait_for("настоящий transcript.final", 30, transcript)
        request(args.core, f"/api/teacher/sessions/{session_id}/call/hangup", "POST", {})

        def completed():
            current = request(args.core, f"/api/teacher/sessions/{session_id}")
            return current if current.get("state") == "COMPLETED" else None

        wait_for("голосовая сессия COMPLETED", 20, completed)
        events = request(args.core, f"/api/teacher/sessions/{session_id}/events")
        kinds = {event.get("type") for event in events}
        check(
            {"call.ringing", "call.answered", "transcript.final", "call.ended"} <= kinds,
            f"Неполная история голосового вызова: {sorted(kinds)}",
        )
        print(
            "PASS: Core -> Asterisk loopback -> RTP -> Media -> Vosk/Piper -> Core; "
            f"transcript={transcript_event['payload']['text']!r} simulated=false"
        )
        print(f"sessionId={session_id} callId={call_id}")
        return 0
    except (RuntimeError, KeyError, TypeError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        if session_id:
            try:
                request(args.core, f"/api/teacher/sessions/{session_id}/call/hangup", "POST", {})
            except Exception:
                pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
