"""Local unit checks; they do not claim 20 real Asterisk calls."""

import argparse
import importlib.util
from pathlib import Path
import time
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("load_voice_stack", Path(__file__).with_name("load_voice_stack.py"))
load = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = load
spec.loader.exec_module(load)


class LoadVoiceStackTest(unittest.TestCase):
    def test_local_ari_and_no_external_target(self):
        self.assertEqual(load.ari_url("http://127.0.0.1:8088/ari"), "http://127.0.0.1:8088/ari")
        for value in ("http://example.com:8088/ari", "https://localhost:8088/ari", "http://localhost:8088/other"):
            with self.assertRaises(argparse.ArgumentTypeError):
                load.ari_url(value)
        self.assertEqual(load.SIP_ADDRESS, "PJSIP/smoke-out")

    def test_queue_overload_is_bounded_and_explicit(self):
        args = argparse.Namespace(max_active=1, queue_size=0, rate=1000, cleanup_timeout=0.1)
        runner = load.Runner(args)
        runner.owned_resources = lambda: {"channels": [], "bridges": []}

        def call(number):
            time.sleep(0.1)
            return load.CallResult(number=number, status="success")

        runner.call = call
        with patch.object(load, "docker_memory", return_value={"media": 100}):
            report = runner.stage(3)
        self.assertEqual(report["successful"], 1)
        self.assertEqual(report["rejected"], 2)
        self.assertEqual(report["failed"], 0)

    def test_percentiles_and_memory_units(self):
        self.assertEqual(load.percentile([100, 200, 300, 400, 500], 95), 500)
        self.assertEqual(load.memory_bytes("2MiB"), 2 * 1024 * 1024)

    def test_cleanup_fallback_targets_only_owned_session(self):
        runner = load.Runner(argparse.Namespace())
        calls = []

        def core(path, method="GET", body=None):
            calls.append(("core", path, body))
            raise RuntimeError("Core temporarily unavailable")

        def media(path, method="GET", body=None):
            calls.append(("media", path, body))
            return {}

        runner.core = core
        runner.media = media
        runner.cleanup("owned-session", "owned-call")
        self.assertEqual(calls[-1], ("media", "/internal/v1/calls/hangup",
                                     {"sessionId": "owned-session", "callId": "owned-call"}))


if __name__ == "__main__":
    unittest.main()
