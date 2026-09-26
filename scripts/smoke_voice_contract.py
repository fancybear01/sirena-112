#!/usr/bin/env python3
"""Core -> real AI session creation -> fake Media HTTP -> Core event replay.

Run while Core points CORE_MEDIA_BASE_URL at this script's --media-port.
The fake implements Media's actual start/hangup JSON surface; it does not
simulate SIP, RTP or speech recognition.
"""

import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
from urllib.request import Request, urlopen
from uuid import uuid4


def request(base, path, method="GET", body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(base.rstrip("/") + path, data=data, method=method,
                  headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=10) as response:
        return json.load(response)


class FakeMedia(BaseHTTPRequestHandler):
    starts = []
    hangups = []

    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(size) or b"{}")
        if self.path == "/internal/v1/calls/start":
            assert body["sessionId"] and body["aiSessionId"] and body["sipAddress"]
            self.starts.append(body)
            result = {**body, "callId": str(uuid4()), "state": "RINGING"}
            status = 202
        elif self.path == "/internal/v1/calls/hangup":
            self.hangups.append(body)
            result = {**body, "state": "ENDED"}
            status = 200
        else:
            self.send_error(404)
            return
        encoded = json.dumps(result).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format, *_args):
        pass


def send_event(core, session_id, call, kind, **extra):
    event = {
        "eventId": str(uuid4()),
        "sessionId": session_id,
        "type": kind,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": "media",
        "payload": {"callId": call["callId"], "aiSessionId": call["aiSessionId"], **extra},
    }
    receipt = request(core, "/internal/v1/media/events", "POST", event)
    assert receipt["accepted"] and receipt["eventId"] == event["eventId"], receipt
    return event


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", default="http://127.0.0.1:8080")
    parser.add_argument("--ai", default="http://127.0.0.1:8090")
    parser.add_argument("--media-port", type=int, default=18091)
    args = parser.parse_args()

    assert request(args.ai, "/health")["status"] == "ok"
    server = ThreadingHTTPServer(("127.0.0.1", args.media_port), FakeMedia)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        session = request(args.core, "/api/teacher/sessions", "POST", {"mode": "VOICE"})
        session_id = session["id"]
        call = request(args.core, f"/api/teacher/sessions/{session_id}/call/start",
                       "POST", {"sipAddress": "PJSIP/1001"})
        assert call["sessionId"] == session_id
        assert call["aiSessionId"]
        assert len(FakeMedia.starts) == 1
        assert FakeMedia.starts[0] == {
            "sessionId": session_id,
            "aiSessionId": call["aiSessionId"],
            "sipAddress": "PJSIP/1001",
        }

        ringing = send_event(args.core, session_id, call, "call.ringing")
        duplicate = request(args.core, "/internal/v1/media/events", "POST", ringing)
        assert not duplicate["accepted"]
        send_event(args.core, session_id, call, "call.answered")
        transcript = send_event(args.core, session_id, call, "transcript.final",
                                text="Учебный адрес", simulated=True)
        hangup = request(args.core, f"/api/teacher/sessions/{session_id}/call/hangup",
                         "POST", {})
        assert hangup["state"] == "ENDED"
        send_event(args.core, session_id, call, "call.ended")
        request(args.core, f"/api/teacher/sessions/{session_id}/call/hangup", "POST", {})

        history = request(args.core, f"/api/teacher/sessions/{session_id}/events")
        ids = [event["eventId"] for event in history]
        assert len(ids) == len(set(ids)), "duplicate event in replay"
        assert transcript["eventId"] in ids
        assert {"call.ringing", "call.answered", "transcript.final", "call.ended"} <= {
            event["type"] for event in history
        }
        assert len(FakeMedia.hangups) == 1
        assert FakeMedia.hangups[0] == {"callId": call["callId"], "sessionId": session_id}
        assert request(args.core, f"/api/student/sessions/{session_id}")["state"] == "COMPLETED"
        print("PASS: real AI session creation; Core/Media IDs correlate; event replay and hangup are idempotent")
        print(f"sessionId={session_id} aiSessionId={call['aiSessionId']} callId={call['callId']}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
