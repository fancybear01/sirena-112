#!/usr/bin/env python3
"""Bounded local SIP load through Core -> Media -> real Asterisk loopback.

Only PJSIP/smoke-out is used. This script never dials an external number.
"""

from __future__ import annotations

import argparse
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
import json
import math
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import uuid


SIP_ADDRESS = "PJSIP/smoke-out"
CONTAINERS = ("media", "asterisk", "ai", "core")


class RequestFailure(RuntimeError):
    def __init__(self, method: str, path: str, status: int, detail: str):
        super().__init__(f"{method} {path}: HTTP {status}: {detail[:300]}")
        self.status = status


def local_url(value: str, allowed_path: str = "") -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in ("localhost", "127.0.0.1", "::1") or
            parsed.username or parsed.password or parsed.query or parsed.fragment or
            parsed.path.rstrip("/") != allowed_path):
        raise argparse.ArgumentTypeError(f"URL must be a local HTTP base URL ending in {allowed_path or '/'}")
    return value.rstrip("/")


def ari_url(value: str) -> str:
    return local_url(value, "/ari")


def request(base: str, path: str, method: str = "GET", body: dict | None = None,
            token: str = "", basic: tuple[str, str] | None = None, timeout: float = 20) -> dict | list:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Accept": "application/json", "X-Request-Id": str(uuid.uuid4())}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    if basic:
        import base64
        headers["Authorization"] = "Basic " + base64.b64encode(":".join(basic).encode()).decode()
    req = Request(base + path, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as error:
        raise RequestFailure(method, path, error.code, error.read().decode(errors="replace")) from error
    except URLError as error:
        raise RuntimeError(f"{method} {path}: {error.reason}") from error


def percentile(values: list[float], percentage: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentage / 100 * len(ordered)) - 1)]


def memory_bytes(value: str) -> int | None:
    match = re.match(r"^([\d.]+)(B|KiB|MiB|GiB|TiB|kB|MB|GB|TB)$", value)
    if not match:
        return None
    scales = {"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3,
              "TiB": 1024**4, "kB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4}
    return int(float(match.group(1)) * scales[match.group(2)])


def docker_memory() -> dict[str, int]:
    try:
        result = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.Name}}|{{.MemUsage}}"],
                                capture_output=True, text=True, timeout=8, check=True)
    except (FileNotFoundError, subprocess.SubprocessError):
        return {}
    memory = {}
    for line in result.stdout.splitlines():
        if "|" not in line:
            continue
        name, usage = line.split("|", 1)
        for service in CONTAINERS:
            if re.search(rf"(?:^|[-_]){service}[-_]\d+$", name):
                size = memory_bytes(usage.split("/", 1)[0].strip())
                if size is not None:
                    memory[service] = size
    return memory


@dataclass
class CallResult:
    number: int
    status: str = "failed"
    sessionId: str = ""
    callId: str = ""
    aiSessionId: str = ""
    startMs: int | None = None
    answeredMs: int | None = None
    error: str = ""
    events: list[str] = field(default_factory=list)


class Runner:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.owned: dict[str, str] = {}  # sessionId -> callId; never contains unrelated calls
        self.bridge_channels: dict[str, set[str]] = {}
        self.active = 0
        self.peak_active = 0
        self.peak_memory: dict[str, int] = {}
        self.memory_samples = 0

    def core(self, path: str, method: str = "GET", body: dict | None = None):
        return request(self.args.core, path, method, body, self.args.core_token)

    def media(self, path: str, method: str = "GET", body: dict | None = None):
        return request(self.args.media, path, method, body, self.args.media_token)

    def ari(self, path: str):
        return request(self.args.ari, path, basic=(self.args.ari_user, self.args.ari_password))

    def owned_resources(self) -> dict[str, list[str]]:
        channels = self.ari("/channels")
        bridges = self.ari("/bridges")
        with self.lock:
            ids = set(self.owned.values()) - {""}
            seen_channels = set().union(*self.bridge_channels.values()) if self.bridge_channels else set()
        return {
            "channels": sorted(c["id"] for c in channels if c.get("id") in seen_channels or c.get("id") in ids or
                               any(c.get("id") == "media-" + call for call in ids)),
            "bridges": sorted(b["id"] for b in bridges if any(b.get("id") == call + "-bridge" for call in ids)),
        }

    def sample_memory(self, done: threading.Event) -> None:
        while not done.is_set():
            sample = docker_memory()
            with self.lock:
                if sample:
                    self.memory_samples += 1
                    for service, size in sample.items():
                        self.peak_memory[service] = max(self.peak_memory.get(service, 0), size)
            done.wait(1)

    def wait_state(self, session: str, target: set[str], timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        last = {}
        while time.monotonic() < deadline and not self.stop.is_set():
            last = self.core(f"/api/teacher/sessions/{session}")
            if last.get("state") in target:
                return last
            time.sleep(0.25)
        raise RuntimeError(f"session {session} did not reach {sorted(target)}; last={last.get('state')}")

    def cleanup(self, session: str, call: str) -> None:
        # Core may not know the callId after an ambiguous start timeout.
        try:
            self.core(f"/api/teacher/sessions/{session}/call/hangup", "POST", {})
            return
        except Exception:
            pass
        try:
            self.media("/internal/v1/calls/hangup", "POST", {"sessionId": session, "callId": call})
        except Exception:
            pass

    def hold_active(self, session: str, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while not self.stop.is_set() and time.monotonic() < deadline:
            state = self.core(f"/api/teacher/sessions/{session}").get("state")
            if state != "ACTIVE":
                raise RuntimeError(f"call ended during hold: {state}")
            self.stop.wait(min(1, max(0, deadline - time.monotonic())))

    def call(self, number: int) -> CallResult:
        result = CallResult(number=number)
        if self.stop.is_set():
            result.error = "generator stopped before call start"
            return result
        start = time.monotonic()
        active = False
        try:
            session = self.core("/api/teacher/sessions", "POST", {"mode": "VOICE"})["id"]
            result.sessionId = session
            with self.lock:
                self.owned[session] = ""
            call = self.core(f"/api/teacher/sessions/{session}/call/start", "POST", {"sipAddress": SIP_ADDRESS})
            result.callId = call["callId"]
            result.aiSessionId = call["aiSessionId"]
            if not result.callId or not result.aiSessionId or call.get("sessionId") != session:
                raise RuntimeError("Core returned incomplete or mismatched call identity")
            with self.lock:
                self.owned[session] = result.callId
            result.startMs = round((time.monotonic() - start) * 1000)
            self.wait_state(session, {"ACTIVE", "FAILED", "COMPLETED"}, self.args.answer_timeout)
            state = self.core(f"/api/teacher/sessions/{session}")["state"]
            if state != "ACTIVE":
                raise RuntimeError(f"call did not answer: {state}")
            result.answeredMs = round((time.monotonic() - start) * 1000)
            with self.lock:
                self.active += 1
                self.peak_active = max(self.peak_active, self.active)
            active = True
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not self.stop.is_set():
                try:
                    bridge = self.ari(f"/bridges/{result.callId}-bridge")
                    channels = bridge.get("channels", [])
                    if result.callId in channels and "media-" + result.callId in channels:
                        with self.lock:
                            self.bridge_channels[result.callId] = set(channels)
                        break
                except RequestFailure as error:
                    if error.status != 404:
                        raise
                time.sleep(0.2)
            else:
                if not self.stop.is_set():
                    raise RuntimeError("Asterisk bridge does not contain this call and its externalMedia channel")
            if self.args.flush_after >= 0:
                self.hold_active(session, self.args.flush_after)
                if not self.stop.is_set():
                    self.media(f"/internal/v1/calls/{result.callId}/input/flush", "POST")
            self.hold_active(session, self.args.hold)
        except Exception as error:
            result.error = str(error)
            if isinstance(error, RequestFailure) and error.status in (429, 503) and any(
                    word in result.error.lower() for word in ("capacity", "too many", "предел", "лимит")):
                result.status = "rejected"
        finally:
            if active:
                with self.lock:
                    self.active -= 1
            if result.sessionId:
                self.cleanup(result.sessionId, result.callId)
                try:
                    final = self.wait_state(result.sessionId, {"COMPLETED", "FAILED"}, self.args.cleanup_timeout)
                    events = self.core(f"/api/teacher/sessions/{result.sessionId}/events")
                    result.events = [e["type"] for e in events]
                    for event in events:
                        payload = event.get("payload") or {}
                        if event.get("type") in ("call.ringing", "call.answered", "call.ended", "transcript.final"):
                            if payload.get("callId") != result.callId or payload.get("aiSessionId") != result.aiSessionId:
                                raise RuntimeError("Core event identity mismatch")
                    if final.get("state") != "COMPLETED" or not {"call.ringing", "call.answered", "call.ended"} <= set(result.events):
                        raise RuntimeError(f"incomplete call lifecycle: {final.get('state')} {result.events}")
                    if "media.error" in result.events:
                        raise RuntimeError("media.error in Core events")
                    if not result.error:
                        result.status = "success"
                except Exception as error:
                    result.error = (result.error + "; " if result.error else "") + str(error)
        return result

    def stage(self, count: int) -> dict:
        with self.lock:
            self.owned.clear()
            self.bridge_channels.clear()
            self.active = 0
            self.peak_active = 0
            self.peak_memory = {}
            self.memory_samples = 0
        before = docker_memory()
        watcher_done = threading.Event()
        watcher = threading.Thread(target=self.sample_memory, args=(watcher_done,), daemon=True)
        watcher.start()
        results: list[CallResult] = []
        futures: list[Future] = []
        slots = threading.BoundedSemaphore(self.args.max_active + self.args.queue_size)
        stage_start = time.monotonic()
        try:
            with ThreadPoolExecutor(max_workers=self.args.max_active) as pool:
                for number in range(count):
                    if self.stop.is_set():
                        break
                    target = stage_start + number / self.args.rate
                    self.stop.wait(max(0, target - time.monotonic()))
                    if self.stop.is_set():
                        break
                    if not slots.acquire(blocking=False):
                        results.append(CallResult(number=number, status="rejected", error="generator queue full"))
                        continue
                    future = pool.submit(self.call, number)
                    future.add_done_callback(lambda _future: slots.release())
                    futures.append(future)
                for future in as_completed(futures):
                    results.append(future.result())
        finally:
            watcher_done.set()
            watcher.join(timeout=10)
        # Asterisk lists are checked only against IDs created by this stage.
        remaining = self.owned_resources()
        deadline = time.monotonic() + self.args.cleanup_timeout
        while (remaining["channels"] or remaining["bridges"]) and time.monotonic() < deadline:
            time.sleep(0.5)
            remaining = self.owned_resources()
        # Give Docker and the services a short interval to release resources.
        self.stop.wait(2)
        after = docker_memory()
        with self.lock:
            peak_active = self.peak_active
            peak_memory = self.peak_memory.copy()
            samples = self.memory_samples
            channel_sets = list(self.bridge_channels.values())
        ids = [r.callId for r in results if r.callId]
        sessions = [r.sessionId for r in results if r.sessionId]
        ai_ids = [r.aiSessionId for r in results if r.aiSessionId]
        unique = len(ids) == len(set(ids)) and len(sessions) == len(set(sessions)) and len(ai_ids) == len(set(ai_ids))
        bridge_channels_unique = len(set().union(*channel_sets)) == sum(map(len, channel_sets)) if channel_sets else True
        latencies = [r.answeredMs for r in results if r.answeredMs is not None]
        report = {
            "requested": count,
            "successful": sum(r.status == "success" for r in results),
            "rejected": sum(r.status == "rejected" for r in results),
            "failed": sum(r.status == "failed" for r in results),
            "peakActive": peak_active,
            "uniqueIdentities": unique,
            "bridgeChannelsUnique": bridge_channels_unique,
            "answerLatencyMs": {"p50": percentile(latencies, 50), "p95": percentile(latencies, 95), "max": max(latencies, default=None)},
            "memoryBytes": {"before": before, "peak": peak_memory, "after": after, "samples": samples},
            "remainingAsteriskResources": remaining,
            "calls": [asdict(r) for r in sorted(results, key=lambda r: r.number)],
        }
        report["passed"] = (report["successful"] == count and peak_active == count and unique and bridge_channels_unique and
                            not remaining["channels"] and not remaining["bridges"] and samples > 0)
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", type=local_url, default="http://127.0.0.1:8080")
    parser.add_argument("--media", type=local_url, default="http://127.0.0.1:8091")
    parser.add_argument("--ai", type=local_url, default="http://127.0.0.1:8090")
    parser.add_argument("--ari", type=ari_url, default="http://127.0.0.1:8088/ari")
    parser.add_argument("--ari-user", default=os.getenv("ASTERISK_ARI_USER", "media"))
    parser.add_argument("--ari-password", default=os.getenv("ASTERISK_ARI_PASSWORD", ""))
    parser.add_argument("--core-token", default=os.getenv("CORE_TEACHER_TOKEN", ""))
    parser.add_argument("--media-token", default=os.getenv("CORE_MEDIA_SERVICE_TOKEN", ""))
    parser.add_argument("--counts", default="5,10,20", help="comma-separated stage sizes")
    parser.add_argument("--rate", type=float, default=5, help="arrival rate in calls/second")
    parser.add_argument("--max-active", type=int, default=20)
    parser.add_argument("--queue-size", type=int, default=20)
    parser.add_argument("--hold", type=float, default=12, help="seconds to hold after flush (or after answer if flush disabled)")
    parser.add_argument("--flush-after", type=float, default=5, help="seconds after answer; -1 disables flush for echo mode")
    parser.add_argument("--answer-timeout", type=float, default=30)
    parser.add_argument("--cleanup-timeout", type=float, default=15)
    parser.add_argument("--report", type=Path, default=Path("voice-load-report.json"))
    args = parser.parse_args()
    try:
        counts = [int(value) for value in args.counts.split(",")]
        if not counts or any(value < 1 for value in counts) or args.rate <= 0 or args.max_active < 1 or args.queue_size < 0 or args.hold <= 0 or args.answer_timeout <= 0 or args.cleanup_timeout <= 0:
            raise ValueError("counts, rate, max-active, hold and timeouts must be positive; queue-size must be non-negative")
    except ValueError as error:
        parser.error(str(error))
    if not args.ari_password:
        parser.error("ASTERISK_ARI_PASSWORD or --ari-password is required")
    runner = Runner(args)
    def interrupt(_signum, _frame):
        runner.stop.set()
    signal.signal(signal.SIGINT, interrupt)
    signal.signal(signal.SIGTERM, interrupt)
    try:
        if runner.core("/actuator/health/readiness").get("status") != "UP":
            raise RuntimeError("Core not ready")
        if runner.media("/ready").get("status") != "ready":
            raise RuntimeError("Media/Asterisk not ready")
        ai_ready = request(args.ai, "/ready")
        if ai_ready.get("status") != "ready":
            raise RuntimeError("AI not ready")
        runner.ari("/bridges")
        reports = []
        for count in counts:
            if runner.stop.is_set():
                break
            print(f"running {count} local SIP calls at {args.rate:g}/s", flush=True)
            report = runner.stage(count)
            reports.append(report)
            print(f"{count}: success={report['successful']} rejected={report['rejected']} failed={report['failed']} peakActive={report['peakActive']} p95={report['answerLatencyMs']['p95']}ms passed={report['passed']}", flush=True)
            if not report["passed"]:
                break
        output = {"kind": "real-asterisk-loopback", "recordedAt": datetime.now(timezone.utc).isoformat(),
                  "host": {"platform": platform.platform(), "cpuCount": os.cpu_count()},
                  "ai": {"engine": ai_ready.get("engine"), "speechSimulated": ai_ready.get("speechSimulated"),
                         "speechAvailable": ai_ready.get("speechAvailable")},
                  "sipAddress": SIP_ADDRESS, "ratePerSecond": args.rate,
                  "maxActive": args.max_active, "queueSize": args.queue_size, "stages": reports}
        args.report.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
        print(f"report: {args.report}")
        return 0 if len(reports) == len(counts) and all(report["passed"] for report in reports) else 1
    except Exception as error:
        print(f"load run failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
