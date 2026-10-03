"""Optional real Chromium+axe -> AccessDoc bundle handoff, no public target."""
import importlib.util
import json
import os
from pathlib import Path
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

from app.scan import run_scan
from app.service import build_artifacts
from app.bundle import build_bundle, validate_bundle


ROOT = Path(__file__).resolve().parents[1]
AXE = ROOT / "node_modules" / "axe-core" / "axe.min.js"


class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'<!doctype html><html lang="en"><title>Fixture</title><main><h1>Fixture</h1><img src="/missing.png"></main></html>'
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


@unittest.skipUnless(importlib.util.find_spec("playwright") and AXE.exists(),
                     "Install Playwright Chromium and pinned local axe-core")
class ScanHandoffTests(unittest.TestCase):
    def test_local_authorized_state_to_verifiable_bundle(self):
        server = HTTPServer(("127.0.0.1", 0), FixtureHandler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/"
        try:
            # Explicit opt-in only for this trusted loopback fixture. The
            # hosted service never accepts arbitrary URLs for browser scans.
            with patch.dict(os.environ, {"ACCESSDOC_AXE_PATH": str(AXE)}):
                scan = run_scan(url, allow_private_network=True)
            self.assertEqual(scan["url"], url)
            self.assertEqual(scan["testEngine"]["version"], "4.11.0")
            self.assertTrue(any(v["id"] == "image-alt" for v in scan["violations"]))
            artifacts = build_artifacts({"scanner_input": scan,
                                         "audit_date": "2026-09-29",
                                         "client_name": "Local fixture"})
            receipt = json.loads(artifacts.receipt_json)
            self.assertEqual(receipt["url"], url)
            self.assertEqual(receipt["engine_version"], "4.11.0")
            self.assertTrue(any(v["id"] == "image-alt" and "img" in v["target"]
                                for v in receipt["violations"]))
            self.assertTrue(validate_bundle(build_bundle(artifacts))["valid"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()