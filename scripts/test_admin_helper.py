import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

from scripts.admin_helper import (
    AuditLog,
    CoreSessionVerifier,
    HelperError,
    StackController,
    build_status,
    command_for,
    safe_configuration,
)


class JsonResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class FixedMetrics:
    def snapshot(self):
        return [{"id": "cpu", "label": "CPU", "usedPercent": 12.5}]


class AdminHelperTest(unittest.TestCase):
    def test_health_failure_is_explicit_for_every_required_component(self):
        def failed_open(_request, timeout):
            self.assertEqual(4, timeout)
            raise URLError("offline")

        payload = build_status("http://127.0.0.1:8099/status", FixedMetrics(), failed_open)

        self.assertEqual("DOWN", payload["status"])
        self.assertEqual({"core", "ai", "media", "postgres", "asterisk"},
                         {item["id"] for item in payload["services"]})
        self.assertTrue(all(item["status"] == "DOWN" for item in payload["services"]))
        self.assertEqual("monitor", payload["errors"][0]["component"])

    def test_non_admin_session_is_forbidden(self):
        def teacher_open(request, timeout):
            self.assertIn("/api/auth/me", request.full_url)
            self.assertEqual("JSESSIONID=test", request.get_header("Cookie"))
            self.assertEqual(4, timeout)
            return JsonResponse(json.dumps({"username": "teacher", "role": "TEACHER"}).encode())

        with self.assertRaises(HelperError) as error:
            CoreSessionVerifier("http://127.0.0.1:8080", teacher_open).require_admin(
                "theme=dark; JSESSIONID=test; analytics=off", "request-1"
            )

        self.assertEqual(403, error.exception.status.value)

    def test_recent_admin_can_restart_core_while_core_is_unavailable(self):
        available = True

        def core_open(_request, timeout):
            self.assertEqual(4, timeout)
            if not available:
                raise URLError("core stopped")
            return JsonResponse(json.dumps({"username": "admin", "role": "ADMIN"}).encode())

        verifier = CoreSessionVerifier("http://127.0.0.1:8080", core_open)
        self.assertEqual("admin", verifier.require_admin("JSESSIONID=admin", "request-1")["username"])
        available = False
        self.assertEqual("admin", verifier.require_admin("JSESSIONID=admin", "request-2")["username"])

        with self.assertRaises(HelperError) as error:
            verifier.require_admin("JSESSIONID=unknown", "request-3")
        self.assertEqual(503, error.exception.status.value)

    def test_safe_command_uses_fixed_argv_without_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditLog(Path(directory) / "audit.jsonl")
            calls = []

            def runner(command, **kwargs):
                calls.append((command, kwargs))
                return subprocess.CompletedProcess(command, 0, "ok", "")

            with patch("scripts.admin_helper.platform.system", return_value="Windows"):
                result = StackController(audit, runner, Path(directory)).execute(
                    "restart", "core", "admin", "request-2"
                )

            self.assertEqual("OK", result["outcome"])
            command, options = calls[0]
            self.assertEqual("powershell.exe", command[0])
            self.assertEqual(["-Action", "restart", "-Service", "core"], command[-4:])
            self.assertFalse(options["shell"])

            with self.assertRaises(HelperError):
                command_for("restart; whoami", "core", Path(directory))
            with self.assertRaises(HelperError):
                command_for("restart", "core; whoami", Path(directory))

    def test_configuration_only_contains_allowlisted_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text(
                "POSTGRES_DB=sirena-test\nPOSTGRES_PASSWORD=top-secret\nLOG_LEVEL=warn\n",
                encoding="utf-8",
            )
            payload = safe_configuration(root)

        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertIn("sirena-test", encoded)
        self.assertIn("warn", encoded)
        self.assertNotIn("top-secret", encoded)
        self.assertFalse(payload["editableInBrowser"])


if __name__ == "__main__":
    unittest.main()
