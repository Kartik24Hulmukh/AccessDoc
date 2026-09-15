"""Authenticated real-browser sample -> verified ZIP, with axe on the UI."""
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

from app.bundle import validate_bundle
from app.main import Handler, Server

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sync_playwright and (ROOT / "node_modules/axe-core/axe.min.js").exists(), "Install Playwright Chromium and axe-core for browser validation")
class HostedUITests(unittest.TestCase):
    def test_authenticated_sample_to_bundle_and_accessible_ui(self):
        server = Server(("127.0.0.1", 0), Handler)
        base = f"http://127.0.0.1:{server.server_port}"
        env = {"ALLOWED_HOSTS": f"127.0.0.1:{server.server_port}", "ALLOWED_ORIGINS": base,
               "ACCESSDOC_REQUIRE_AUTH": "true", "ACCESSDOC_API_KEY": "local-browser-test-only",
               "RATE_LIMIT_PER_MINUTE": "100000"}
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ, env), tempfile.TemporaryDirectory() as temp, sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                try:
                    # The UI ships CSP script-src 'self' (no unsafe-eval). Playwright's
                    # evaluate/wait_for_function inject eval'd strings into the main
                    # world and are blocked by that policy on current Chromium builds,
                    # so the test harness bypasses CSP for its own instrumentation and
                    # asserts the production policy header explicitly below instead.
                    page = browser.new_page(bypass_csp=True)
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    response = page.goto(base)
                    self.assertIsNotNone(response)
                    csp = response.headers.get("content-security-policy", "")
                    self.assertIn("script-src 'self'", csp)
                    self.assertNotIn("unsafe-eval", csp)
                    self.assertNotIn("unsafe-inline", csp)
                    page.locator("#sample").click()
                    page.wait_for_function("document.querySelector('#scanner').value.length > 0")
                    # Auth-required error must be accessible and recoverable.
                    page.locator("#generate").click()
                    page.locator("#errors").wait_for(state="visible")
                    self.assertIn("API access denied", page.locator("#errors").inner_text())
                    page.locator("#api-key").fill("local-browser-test-only")
                    with page.expect_download() as info:
                        page.locator("#generate").click()
                    target = Path(temp) / "report.zip"
                    info.value.save_as(target)
                    self.assertTrue(validate_bundle(target.read_bytes())["valid"])
                    page.locator("#result").wait_for(state="visible")
                    self.assertEqual(page.evaluate("Object.keys(localStorage).length"), 0)
                    self.assertEqual(page.evaluate("Object.keys(sessionStorage).length"), 0)
                    self.assertEqual(errors, [])
                    # Automation evaluation injects the auditor without weakening app CSP.
                    page.evaluate((ROOT / "node_modules/axe-core/axe.min.js").read_text())
                    violations = page.evaluate("async () => (await axe.run()).violations.map(v => v.id)")
                    self.assertEqual(violations, [])
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
