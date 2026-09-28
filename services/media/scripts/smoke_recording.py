#!/usr/bin/env python3
"""Download and optionally play finished training calls through Core access checks."""
import argparse
import getpass
import json
import os
import shutil
import struct
import subprocess
import tempfile
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--session", action="append", required=True, help="completed VOICE session UUID; repeat for two calls")
parser.add_argument("--core", default="http://127.0.0.1:8080")
parser.add_argument("--username", required=True)
parser.add_argument("--play", action="store_true")
args = parser.parse_args()
password = os.environ.get("CORE_TEACHER_PASSWORD") or getpass.getpass("Teacher password: ")
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))


def get(path):
    with opener.open(args.core.rstrip("/") + path, timeout=15) as response:
        return response.read()


csrf = json.loads(get("/api/auth/csrf"))
login = urllib.request.Request(args.core.rstrip("/") + "/api/auth/login",
                              data=json.dumps({"username": args.username, "password": password}).encode(),
                              headers={"Content-Type": "application/json", csrf["headerName"]: csrf["token"]})
with opener.open(login, timeout=15):
    pass
password = ""

with tempfile.TemporaryDirectory(prefix="sirena-recording-smoke-") as tmp:
    for session in args.session:
        path = f"/api/teacher/sessions/{session}"
        review = json.loads(get(path + "/review"))
        wav = get(path + "/recording")
        assert review["sessionId"] == session
        assert len(wav) == review["bytes"]
        assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE" and wav[36:40] == b"data"
        assert struct.unpack_from("<H", wav, 22)[0] == 2
        assert struct.unpack_from("<I", wav, 24)[0] == 8000
        assert struct.unpack_from("<I", wav, 40)[0] == len(wav) - 44
        sequences = [e["payload"].get("sequence") for e in review["transcript"]]
        assert sequences == sorted(sequences)
        assert all(e["payload"]["callId"] == review["callId"] for e in review["transcript"])
        print(f"session={session} call={review['callId']} duration={review['durationMs']}ms "
              f"transcripts={len(sequences)} wav={len(wav)} bytes")
        if args.play:
            player = shutil.which("afplay") or shutil.which("ffplay") or shutil.which("aplay")
            if not player:
                raise RuntimeError("No afplay, ffplay or aplay installed")
            file = Path(tmp) / f"{review['callId']}.wav"
            file.write_bytes(wav)
            command = [player, str(file)] if Path(player).name != "ffplay" else [player, "-nodisp", "-autoexit", str(file)]
            subprocess.run(command, check=True)
