"""Executable smoke contracts, full SHA identity and release test collection."""
import ast
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.error import HTTPError
from urllib.request import Request
from unittest.mock import patch

import yaml

from scripts.production_smoke import (
    SameOriginRedirectHandler, error_response_matches, exact_commit_matches,
    validate_target_url, smoke_headers, redact_smoke_text,
)

ROOT = Path(__file__).resolve().parents[1]


class ReleaseValidationIntegrityTests(unittest.TestCase):
    def test_target_origins_cannot_leak_bypass_to_arbitrary_projects(self):
        validate_target_url("https://access-doc.vercel.app", bypass=True)
        validate_target_url("https://access-abc123-atlas16.vercel.app", bypass=True)
        validate_target_url("http://127.0.0.1:8000")
        for url in ("https://other-project.vercel.app", "https://attacker.example",
                    "https://access-doc.vercel.app?secret=private",
                    "https://user:private@access-doc.vercel.app",
                    "http://access-doc.vercel.app", "file:///private"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_target_url(url, bypass=True)

    def test_seven_character_collision_is_not_deployed_identity(self):
        sha = "a" * 40
        collision = "a" * 7 + "b" * 33
        self.assertFalse(exact_commit_matches(collision, sha))
        self.assertTrue(exact_commit_matches(sha.upper(), sha))
        for bad in (None, "", "unknown", sha[:7], "g" * 40):
            self.assertFalse(exact_commit_matches(bad, sha))

    def test_negative_contract_rejects_success_transport_failure_and_empty_body(self):
        body = b'{"error":"Invalid input"}'
        for status, data in ((200, body), (None, body), (422, b""),
                             (422, b"<html>error</html>"), (422, b"{}")):
            self.assertFalse(error_response_matches(status, data, 422))
        self.assertTrue(error_response_matches(422, body, 422))

    def test_negative_contract_rejects_exception_leakage(self):
        for text in ("Traceback", "Exception", 'File "private.py"'):
            body = json.dumps({"error": text}).encode()
            self.assertFalse(error_response_matches(422, body, 422))

    def test_negative_contract_rejects_exception_leakage_in_keys(self):
        for payload in (
                {"error": "Invalid input", "Traceback": "redacted"},
                {"error": "Invalid input", "diagnostics": {
                    'File "private.py"': "redacted"}},
                {"error": ["Invalid input", {"Exception": "redacted"}]}):
            with self.subTest(payload=payload):
                self.assertFalse(error_response_matches(
                    422, json.dumps(payload).encode(), 422))

    @unittest.skipIf(sys.platform == "win32", "GitHub Linux bash gate")
    def test_gsa_validator_nonzero_exit_cannot_pass_with_valid_output(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
        step = next(s for s in workflow["jobs"]["test"]["steps"]
                    if "GSA CLI validator" in s.get("name", ""))
        # Reproduce only the gate pipeline and checks, without cloning or npm.
        run = step["run"]
        run = run[run.index("npx --prefix"):].replace(
            "npx --prefix /tmp/openacr-upstream ts-node "
            "/tmp/openacr-upstream/src/openacr.ts validate -f /tmp/test_acr.yaml",
            '{ printf "Valid!\\n"; exit 42; }')
        flags = ["-e", "-o", "pipefail"] if step.get("shell") == "bash" else ["-e"]
        with tempfile.TemporaryDirectory() as directory:
            run = run.replace("/tmp/gsa.out", str(Path(directory) / "gsa.out"))
            result = subprocess.run(["bash", "--noprofile", "--norc",
                                     *flags, "-c", run], capture_output=True,
                                    text=True, timeout=5)
        self.assertEqual(result.returncode, 42, result.stdout + result.stderr)

    def test_bypass_credential_cannot_follow_cross_origin_redirect(self):
        request = Request("https://candidate.vercel.app/healthz",
                          headers={"x-vercel-protection-bypass": "local-test"})
        with self.assertRaises(HTTPError):
            SameOriginRedirectHandler().redirect_request(
                request, None, 302, "Found", {}, "https://other.example/healthz")
        redirected = SameOriginRedirectHandler().redirect_request(
            request, None, 302, "Found", {}, "https://candidate.vercel.app/readyz")
        self.assertIsNotNone(redirected)

    def test_pilot_headers_separate_platform_and_application_authorization(self):
        base = "https://access-abc123-atlas16.vercel.app"
        headers = smoke_headers(base, "POST", bypass="platform-test",
                                api_key="pilot-test")
        self.assertEqual(headers["Authorization"], "Bearer pilot-test")
        self.assertEqual(headers["x-vercel-protection-bypass"], "platform-test")
        no_auth = smoke_headers(base, "POST", bypass="platform-test",
                                api_key="pilot-test", authenticate=False)
        self.assertNotIn("Authorization", no_auth)
        self.assertEqual(no_auth["x-vercel-protection-bypass"], "platform-test")
        self.assertNotIn("Authorization", smoke_headers(base, "GET", api_key="pilot-test"))
        for unsafe in ("https://attacker.invalid", "https://other.vercel.app",
                       "https://access-doc.vercel.app?leak=1"):
            with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                smoke_headers(unsafe, "POST", api_key="pilot-test")
        for credential in ("line\nbreak", "line\rbreak"):
            with self.assertRaises(ValueError):
                smoke_headers(base, "POST", api_key=credential)
        validate_target_url("http://127.0.0.1:8000", api_key=True)

    def test_workflow_runs_shipped_smoke_and_archives_report(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/production-smoke.yml").read_text())
        job = workflow["jobs"]["smoke"]
        self.assertEqual(job["env"]["TARGET_COMMIT"], "${{ github.sha }}")
        run = next(s for s in job["steps"] if "scripts/production_smoke.py" in s.get("run", ""))
        self.assertIn("--output production-smoke.json", run["run"])
        self.assertIn("VERCEL_AUTOMATION_BYPASS_SECRET", run["env"])
        self.assertEqual(job["environment"], "accessdoc-pilot-verification")
        self.assertEqual(run["env"]["SMOKE_REQUIRE_AUTH"], "true")
        self.assertEqual(run["env"]["SMOKE_API_KEY"],
                         "${{ secrets.ACCESSDOC_PILOT_API_KEY }}")
        self.assertTrue(any(s.get("with", {}).get("path") == "production-smoke.json"
                            and s.get("if") == "always()" for s in job["steps"]))

    def test_release_verifier_collects_function_and_unittest_cases(self):
        tree = ast.parse((ROOT / "scripts/verify_release.py").read_text())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == "run"
                 and n.args and isinstance(n.args[0], ast.Constant)
                 and n.args[0].value == "tests"]
        self.assertEqual(len(calls), 1)
        flags = [n.value for n in calls[0].args[1].elts if isinstance(n, ast.Constant)]
        self.assertIn("pytest", flags)
        self.assertIn("error::ResourceWarning", flags)
        self.assertNotIn("unittest", flags)
        config = (ROOT / "pyproject.toml").read_text()
        self.assertIn('"error::pytest.PytestUnraisableExceptionWarning"', config)
        self.assertIn('"error::pytest.PytestUnhandledThreadExceptionWarning"', config)

    def test_dependency_security_gate_is_present_and_fail_closed(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
        steps = workflow["jobs"]["dependency-security"]["steps"]
        audit = next(s for s in steps if "python -m pip_audit" in s.get("run", ""))
        self.assertIn("--format cyclonedx-json", audit["run"])
        self.assertNotIn("|| true", audit["run"])
        self.assertFalse(audit.get("continue-on-error", False))
        self.assertTrue(any(s.get("if") == "always()" and
                            "dependency-audit.cdx.json" in s.get("with", {}).get("path", "")
                            for s in steps))

    def run_real_smoke(self, authenticated=False):
        from api.handler import handler
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        server.daemon_threads = True
        runner = threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.01))
        runner.start()
        # Fixture identity, not a claim of deployed production identity.
        env = {**os.environ, "PRODUCTION_URL": "http://127.0.0.1:%d" % server.server_port,
               "TARGET_COMMIT": "a" * 40, "VERCEL_GIT_COMMIT_SHA": "a" * 40,
               "EXPECTED_VERSION": (ROOT / "VERSION").read_text().strip(),
               "SMOKE_MAX_WAIT_SECONDS": "1", "SMOKE_POLL_INTERVAL_SECONDS": "0.01",
               "VERCEL_AUTOMATION_BYPASS_SECRET": "",
               "SMOKE_API_KEY": "synthetic-pilot-only" if authenticated else "",
               "SMOKE_REQUIRE_AUTH": "true" if authenticated else "false",
               "ACCESSDOC_REQUIRE_AUTH": "true" if authenticated else "false",
               "ACCESSDOC_API_KEY": "synthetic-pilot-only" if authenticated else "",
               "ACCESSDOC_API_KEYS": ""}
        try:
            with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, env):
                output = Path(directory) / "report.json"
                result = subprocess.run([sys.executable, "scripts/production_smoke.py",
                                         "--output", str(output)], cwd=ROOT, env=env,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout[-2000:] + result.stderr)
                report = json.loads(output.read_text())
                self.assertTrue(report["pass"])
                self.assertEqual(report["failures"], [])
                self.assertEqual(sum(n.startswith("Error contract: ")
                                     for n in report["checks"]), 7)
                self.assertIn("Exact target remains deployed after smoke", report["checks"])
                self.assertIn("GET /readyz reports ready", report["checks"])
                self.assertEqual(report["authenticated_pilot"], authenticated)
                self.assertTrue(all(c["pass"] for c in report["check_results"]))
                if authenticated:
                    self.assertIn("Pilot rejects missing credential", report["checks"])
                    self.assertIn("Pilot rejects wrong credential", report["checks"])
                    self.assertNotIn("synthetic-pilot-only", output.read_text())
        finally:
            server.shutdown()
            server.server_close()
            runner.join(2)
            self.assertFalse(runner.is_alive())

    def test_shipped_smoke_executes_full_contract_over_real_loopback(self):
        self.run_real_smoke()

    def test_authenticated_smoke_executes_real_loopback_with_negative_auth(self):
        self.run_real_smoke(authenticated=True)

    def test_required_pilot_missing_credential_fails_before_network(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            env = {**os.environ, "PRODUCTION_URL": "http://127.0.0.1:1",
                   "TARGET_COMMIT": "a" * 40, "EXPECTED_VERSION": "test",
                   "SMOKE_REQUIRE_AUTH": "true", "SMOKE_API_KEY": "",
                   "VERCEL_AUTOMATION_BYPASS_SECRET": ""}
            result = subprocess.run([sys.executable, "scripts/production_smoke.py",
                "--output", str(output)], env=env, cwd=ROOT,
                capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 2)
            report = json.loads(output.read_text())
            self.assertEqual(report["phase"], "configuration")
            self.assertEqual(report["checks"], [])

    def test_reflected_credentials_are_redacted(self):
        self.assertEqual(redact_smoke_text("platform-secret pilot-secret",
            "platform-secret", "pilot-secret"), "[credential] [credential]")

    def test_unsafe_target_overwrites_stale_success_without_credential_leak(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            output.write_text('{"pass":true}')
            env = {**os.environ, "PRODUCTION_URL": "https://attacker.invalid",
                   "TARGET_COMMIT": "a" * 40, "EXPECTED_VERSION": "test",
                   "SMOKE_REQUIRE_AUTH": "true", "SMOKE_API_KEY": "private-key-canary",
                   "VERCEL_AUTOMATION_BYPASS_SECRET": ""}
            result = subprocess.run([sys.executable, "scripts/production_smoke.py",
                "--output", str(output)], env=env, cwd=ROOT,
                capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 2)
            report = json.loads(output.read_text())
            self.assertFalse(report["pass"])
            self.assertEqual(report["checks"], [])
            self.assertNotIn("private-key-canary",
                             result.stdout + result.stderr + output.read_text())

    def test_sso_redirect_fails_as_authorization_without_polling(self):
        class Redirect(BaseHTTPRequestHandler):
            requests = 0
            def do_GET(self):
                type(self).requests += 1
                self.send_response(302)
                self.send_header("Location", "https://vercel.com/sso-api?private-canary=1")
                self.send_header("Content-Length", "0")
                self.end_headers()
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
        runner = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01))
        runner.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "report.json"
                env = {**os.environ, "PRODUCTION_URL": f"http://127.0.0.1:{server.server_port}",
                       "TARGET_COMMIT": "a" * 40, "EXPECTED_VERSION": "test",
                       "SMOKE_REQUIRE_AUTH": "false", "SMOKE_API_KEY": "",
                       "VERCEL_AUTOMATION_BYPASS_SECRET": "",
                       "SMOKE_MAX_WAIT_SECONDS": "30"}
                result = subprocess.run([sys.executable, "scripts/production_smoke.py",
                    "--output", str(output)], env=env, cwd=ROOT,
                    capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 2)
                report = json.loads(output.read_text())
                self.assertEqual(report["phase"], "authorization")
                self.assertEqual(report["checks"], [])
                self.assertEqual(Redirect.requests, 1)
                self.assertNotIn("private-canary", result.stdout + output.read_text())
        finally:
            server.shutdown()
            server.server_close()
            runner.join(2)
            self.assertFalse(runner.is_alive())


if __name__ == "__main__":
    unittest.main()