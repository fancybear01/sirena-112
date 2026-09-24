#!/usr/bin/env python3
"""Interactive softphone smoke using existing READY VOICE sessions in Core."""
import argparse
import json
import time
from urllib.request import Request, urlopen

parser = argparse.ArgumentParser()
parser.add_argument("--session", action="append", required=True,
                    help="Existing READY VOICE session UUID; repeat for a second call")
parser.add_argument("--sip", default="PJSIP/1001")
parser.add_argument("--core", default="http://127.0.0.1:8080")
parser.add_argument("--media", default="http://127.0.0.1:8091")
args = parser.parse_args()


def request(base, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = Request(base.rstrip("/") + path, data=data,
                  headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=15) as response:
        return json.load(response)


def wait_for(fn, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(0.2)
    raise RuntimeError("Timed out waiting for call/events")


for session in args.session:
    prefix = f"/api/teacher/sessions/{session}"
    call = request(args.core, prefix + "/call/start", {"sipAddress": args.sip})
    call_id, ai_id = call["callId"], call["aiSessionId"]
    print(f"sessionId={session} callId={call_id} aiSessionId={ai_id}")
    try:
        print("Ответь на softphone. Сейчас дождусь ACTIVE.")
        wait_for(lambda: request(args.media, f"/internal/v1/calls/{call_id}")["state"] == "ACTIVE")
        for turn in (1, 2):
            print(f"Ход {turn}: говори сейчас, через 4 секунды будет input.flush.")
            time.sleep(4)
            request(args.media, f"/internal/v1/calls/{call_id}/input/flush", {})
            def transcripts():
                events = request(args.core, prefix + "/events")
                return [e for e in events if e["type"] == "transcript.final"
                        and e["payload"].get("callId") == call_id]
            events = wait_for(lambda: (rows if len(rows := transcripts()) >= turn else None))
            for event in events:
                assert event["sessionId"] == session
                assert event["payload"]["aiSessionId"] == ai_id
                assert event["eventId"]
            print(f"Ход {turn}: transcript.final в Core, simulated={events[-1]['payload'].get('simulated')}")
            print("Жду окончания ответа (scripted/silence должен дать тишину).")
            time.sleep(11)  # playback queue is bounded to ten seconds
    finally:
        request(args.core, prefix + "/call/hangup", {})
    def ended_events():
        rows = request(args.core, prefix + "/events")
        return rows if any(e["type"] == "call.ended" and
                           e["payload"].get("callId") == call_id for e in rows) else None
    events = wait_for(ended_events)
    observed = {e["type"] for e in events if e["payload"].get("callId") == call_id}
    assert {"call.ringing", "call.answered", "call.ended", "transcript.final"} <= observed
    print("PASS: lifecycle + two transcripts correlated in Core; call ended")
