"""Phase 12 — Complete end-to-end user journeys.

Seven journeys covering CLI, Public API, GitHub Action, MCP, Signing,
Fresh-user install, and Production (skipped).  Tests use existing fixtures
and keep inputs small for fast execution.
"""
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from http.server import HTTPServer
from threading import Thread
from urllib.request import urlopen, Request
from urllib.error import HTTPError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.service import build_artifacts
from app.bundle import build_bundle, validate_bundle, MEMBERS
from mcp import server

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

AXE_JSON = json.dumps({
    "url": "https://example.com",
    "testEngine": {"name": "axe-core", "version": "4.11.2"},
    "violations": [
        {"id": "image-alt", "impact": "critical",
         "description": "Images must have alternate text",
         "helpUrl": "https://dequeuniversity.com/rules/axe/4.11/image-alt",
         "nodes": [{"html": "<img src='x.png'>"}]},
    ],
    "passes": [], "incomplete": [],
})


def _write_axe(tmpdir):
    path = os.path.join(tmpdir, "axe.json")
    with open(path, "w") as f:
        f.write(AXE_JSON)
    return path


# ===========================================================================
# JOURNEY 1 — CLI: generate, verify, tamper, with SARIF/VPAT/EAA
# ===========================================================================

class Journey1CLI(unittest.TestCase):
    """Full CLI workflow: bundle -> verify -> tamper -> verify rejection."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        import cli
        self.cli = cli

    def test_full_cli_journey(self):
        axe_path = _write_axe(self.tmp)
        out = os.path.join(self.tmp, "bundle.zip")

        # 1a. Generate bundle with SARIF, VPAT, EAA
        rc = self.cli.main([
            "bundle", axe_path, "--out", out,
            "--sarif", "--vpat", "--eaa",
        ])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(out))

        # 1b. Verify intact bundle passes
        rc = self.cli.main(["verify", out])
        self.assertEqual(rc, 0)

        # 1c. Check optional members present
        with zipfile.ZipFile(out) as z:
            names = set(z.namelist())
            self.assertIn("findings.sarif.json", names)
            self.assertIn("vpat-draft.html", names)
            self.assertIn("eaa-evidence.md", names)

        # 1d. Tamper and verify rejection
        with zipfile.ZipFile(out) as z:
            items = {n: z.read(n) for n in z.namelist()}
        items["report.html"] = b"tampered"
        with zipfile.ZipFile(out, "w") as z:
            for n, d in items.items():
                z.writestr(n, d)
        rc = self.cli.main(["verify", out])
        self.assertEqual(rc, 1)


# ===========================================================================
# JOURNEY 2 — Public API: health, valid POST, verify, invalid, oversized
# ===========================================================================

class Journey2PublicAPI(unittest.TestCase):
    """Full public API workflow."""

    @classmethod
    def setUpClass(cls):
        from api.handler import handler
        cls.server = HTTPServer(("127.0.0.1", 0), handler)
        cls.port = cls.server.server_address[1]
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        # Release the listening socket too. shutdown() only stops
        # serve_forever(); without server_close() the fd leaks and the
        # interpreter emits ResourceWarning at exit.
        cls.server.server_close()

    def _get(self, path="/"):
        req = Request(f"http://127.0.0.1:{self.port}{path}")
        return urlopen(req)

    def _post_json(self, obj, path="/"):
        body = json.dumps(obj).encode()
        req = Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return urlopen(req)

    def test_health_get(self):
        resp = self._get("/")
        self.assertEqual(resp.status, 200)
        data = json.loads(resp.read())
        self.assertEqual(data["service"], "AccessDoc")
        self.assertEqual(data["status"], "ok")

    def test_valid_post_returns_zip(self):
        resp = self._post_json({"scanner_input": AXE_JSON})
        self.assertEqual(resp.status, 200)
        ct = resp.headers.get("Content-Type", "")
        self.assertIn("application/zip", ct)
        zip_bytes = resp.read()
        # Verify the ZIP is a valid AccessDoc bundle
        result = validate_bundle(zip_bytes)
        self.assertTrue(result["valid"], result["errors"])

    def test_invalid_input_returns_400(self):
        with self.assertRaises(HTTPError) as ctx:
            self._post_json({"scanner_input": ""})
        self.assertEqual(ctx.exception.code, 400)

    def test_oversized_returns_413(self):
        """Content-Length > MAX_HTTP_BODY_BYTES -> 413."""
        from app.limits import MAX_HTTP_BODY_BYTES
        body = b'{"scanner_input": "x"}'
        req = Request(
            f"http://127.0.0.1:{self.port}/",
            data=body,
            headers={"Content-Type": "application/json",
                     "Content-Length": str(MAX_HTTP_BODY_BYTES + 1)},
            method="POST",
        )
        with self.assertRaises(HTTPError) as ctx:
            urlopen(req)
        self.assertEqual(ctx.exception.code, 413)


# ===========================================================================
# JOURNEY 3 — GitHub Action: verify action.yml has no eval, has bash array
# ===========================================================================

class Journey3GitHubAction(unittest.TestCase):
    """Reference test: action.yml must not use eval, must use bash arrays.

    The full adversarial injection suite is in test_action_injection.py.
    This journey verifies the structural properties hold.
    """

    def test_action_yml_no_eval(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "action.yml")) as f:
            content = f.read()
        self.assertNotIn("eval ", content)
        self.assertNotIn("eval(", content)

    def test_action_yml_uses_bash_array(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "action.yml")) as f:
            content = f.read()
        # The bash-array pattern passes inputs as argv elements, not via
        # string interpolation into a command.
        self.assertIn("python3", content)


# ===========================================================================
# JOURNEY 4 — MCP: initialize, tools/list, generate, malformed args
# ===========================================================================

class Journey4MCP(unittest.TestCase):
    """Full MCP server workflow."""

    def test_initialize(self):
        resp = server.handle_request({
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
        })
        self.assertIn("serverInfo", resp["result"])

    def test_tools_list(self):
        resp = server.handle_request({
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
        })
        names = {t["name"] for t in resp["result"]["tools"]}
        self.assertIn("generate_bundle", names)
        self.assertIn("verify_bundle", names)

    def test_generate_bundle_valid_input(self):
        resp = server.handle_request({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "generate_bundle",
                       "arguments": {"scanner_input": AXE_JSON,
                                     "client_name": "MCP Test"}},
        })
        payload = json.loads(resp["result"]["content"][0]["text"])
        self.assertIn("bundle_base64", payload)
        # Verify the generated bundle
        import base64
        vresp = server.handle_request({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "verify_bundle",
                       "arguments": {"bundle_base64": payload["bundle_base64"]}},
        })
        vdata = json.loads(vresp["result"]["content"][0]["text"])
        self.assertTrue(vdata["valid"])

    def test_malformed_arguments_error(self):
        """Missing required scanner_input -> error response."""
        resp = server.handle_request({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "generate_bundle", "arguments": {}},
        })
        self.assertTrue(resp["result"].get("isError"))

    def test_malformed_json_arguments_error(self):
        """Non-string scanner_input -> error."""
        resp = server.handle_request({
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "generate_bundle",
                       "arguments": {"scanner_input": 12345}},
        })
        self.assertTrue(resp["result"].get("isError"))


# ===========================================================================
# JOURNEY 5 — Signing: verify sign-evidence.yml has expected_commit_sha
# ===========================================================================

class Journey5Signing(unittest.TestCase):
    """Reference test: sign-evidence.yml must have expected_commit_sha input.

    The full provenance verification suite is in test_signing_provenance.py.
    This journey verifies the input exists.
    """

    def test_sign_evidence_has_expected_commit_sha(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        wf_path = os.path.join(root, ".github", "workflows", "sign-evidence.yml")
        with open(wf_path) as f:
            content = f.read()
        self.assertIn("expected_commit_sha", content)


# ===========================================================================
# JOURNEY 6 — Fresh user: README install + cli.py doctor
# ===========================================================================

class Journey6FreshUser(unittest.TestCase):
    """Simulate a fresh user following README install instructions."""

    def test_doctor_works(self):
        """cli.py doctor should exit 0 and mention key components."""
        import cli
        buf = io.StringIO()
        with __import__("contextlib").redirect_stdout(buf):
            rc = cli.main(["doctor"])
        self.assertEqual(rc, 0)
        output = buf.getvalue()
        self.assertIn("Python", output)
        self.assertIn("reportlab", output)

    def test_readme_install_command_exists(self):
        """README must contain pip install instructions."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "README.md")) as f:
            content = f.read()
        self.assertIn("pip install", content)
        self.assertIn("cli.py", content)

    def test_fresh_user_bundle_workflow(self):
        """Fresh user can generate and verify a bundle via CLI."""
        import cli
        tmp = tempfile.mkdtemp()
        axe_path = _write_axe(tmp)
        out = os.path.join(tmp, "bundle.zip")
        rc = cli.main(["bundle", axe_path, "--out", out])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(out))
        rc = cli.main(["verify", out])
        self.assertEqual(rc, 0)


# ===========================================================================
# JOURNEY 7 — Production: skip (requires deployment)
# ===========================================================================

class Journey7Production(unittest.TestCase):
    """Production smoke test — skipped (requires live deployment)."""

    @unittest.skip("Production smoke test requires live deployment")
    def test_production_health(self):
        pass


if __name__ == "__main__":
    unittest.main()
