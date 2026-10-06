"""Loopback hosted UI regressions: real bundle integrity; labelled synthetic state controls.

Remediation, pending responses, File.text delays and 429 responses are synthetic
controls, not provider/integration, practitioner, or recipient-acceptance evidence.
"""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

try:
    from playwright.sync_api import Error as PlaywrightError, sync_playwright
except ImportError:
    sync_playwright = None

from app.bundle import validate_bundle
from app.main import Handler, Server

ROOT = Path(__file__).resolve().parents[1]
A = {"violations": [{"id": "image-alt", "impact": "serious", "help": "Synthetic A",
                     "nodes": [{"target": ["#synthetic-a"]}]}]}


@unittest.skipUnless(sync_playwright, "Playwright required for loopback UI regression checks")
class HostedUIRevisionTests(unittest.TestCase):
    def setUp(self):
        self.server = Server(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.env = patch.dict(os.environ, {
            "ALLOWED_HOSTS": f"127.0.0.1:{self.server.server_port}",
            "ALLOWED_ORIGINS": self.base, "ACCESSDOC_REQUIRE_AUTH": "false",
            "RATE_LIMIT_PER_MINUTE": "100000",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.playwright = sync_playwright().start()
        self.addCleanup(self.playwright.stop)
        self.browser = self.playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        self.addCleanup(self.browser.close)
        self.context = self.browser.new_context(bypass_csp=True, accept_downloads=True)
        self.context.route("**/*", self.loopback_only)
        self.page = self.context.new_page()
        self.js_errors = []
        self.page.on("pageerror", lambda error: self.js_errors.append(str(error)))
        self.posts = []
        self.page.on("request", lambda request: self.posts.append((urlsplit(request.url).path, request.post_data_json))
                     if request.method == "POST" else None)
        self.downloads = []
        self.page.on("download", lambda event: self.downloads.append(event))
        self.page.goto(self.base)
        self.page.locator("#client").fill("Synthetic Client A")
        self.page.locator("#agency").fill("Synthetic Agency")
        self.upload(A)

    def tearDown(self):
        self.assertEqual(self.js_errors, [])

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def loopback_only(self, route):
        if urlsplit(route.request.url).hostname != "127.0.0.1":
            route.abort()
            raise AssertionError("Tests must never contact external services")
        route.continue_()

    def upload(self, evidence, name="synthetic-a.json"):
        self.page.locator("#evidence-file").set_input_files({
            "name": name, "mimeType": "application/json", "buffer": json.dumps(evidence).encode(),
        })

    def real_bundle(self):
        with self.page.expect_download() as event:
            self.page.locator("#generate").click()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "report.zip"
            event.value.save_as(target)
            body = target.read_bytes()
            self.assertTrue(validate_bundle(body)["valid"])
        self.page.locator("#result").wait_for(state="visible")
        return body

    def synthetic_guidance(self):
        self.page.route("**/api/remediate", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps({
                "guidance": "Synthetic guidance", "fallback": True, "violations_considered": 1,
            })))
        self.page.locator("#remediate").click()
        self.page.locator("#remediation-out").wait_for(state="visible")

    def release_synthetic_late_response(self, route):
        # Deliberately not a ZIP: state guard must discard this response entirely.
        try:
            route.fulfill(status=200, content_type="application/zip", body=b"SYNTHETIC-LATE-NOT-A-ZIP")
        except PlaywrightError:
            # Chromium may already have removed the interception after AbortController.
            pass
        self.page.wait_for_timeout(150)

    def test_file_only_real_bundle_and_synthetic_guidance_share_revision(self):
        self.real_bundle()
        self.assertEqual(self.page.locator("#scanner").input_value(), "")
        bundle = next(payload for path, payload in self.posts if path == "/api/bundle")
        self.assertEqual(json.loads(bundle["scanner_input"]), A)
        self.assertEqual(bundle["source_filename"], "synthetic-a.json")
        self.synthetic_guidance()
        guidance = next(payload for path, payload in self.posts if path == "/api/remediate")
        self.assertEqual(guidance["scanner_input"], A)
        self.assertEqual(guidance["client_name"], bundle["client_name"])
        label = self.page.locator("#result-context").inner_text()
        revision = label.split("revision ")[1].split(".")[0]
        self.assertIn("Synthetic Client A", label)
        self.assertIn("synthetic-a.json", label)
        self.assertIn("revision " + revision, self.page.locator("#remediation-meta").inner_text())
        disclosure = self.page.locator(".remediation > .hint").inner_text()
        for text in ["full scan", "same-origin", "may contain private content", "omitted", "does not call a model"]:
            self.assertIn(text, disclosure)
        self.assertEqual(self.page.evaluate("Object.keys(localStorage).length + Object.keys(sessionStorage).length"), 0)

    def test_sample_clears_upload_and_invalidates_guidance(self):
        self.real_bundle()
        self.synthetic_guidance()
        self.page.locator("#sample").click()
        self.page.wait_for_function("document.querySelector('#client').value === 'Northstar Community Bank'")
        self.assertEqual(self.page.locator("#file-name").inner_text(), "No file selected")
        self.assertEqual(self.page.locator("#evidence-file").evaluate("el => el.files.length"), 0)
        self.assertIsNotNone(self.page.locator("#scanner").get_attribute("required"))
        self.assertTrue(self.page.locator("#remediation-out").is_hidden())
        self.assertEqual(self.page.locator("#remediation-text").inner_text(), "")
        self.assertTrue(self.page.locator("#remediate").is_disabled())
        self.assertIn("previous report", self.page.locator("#result-context").inner_text())
        self.real_bundle()
        payload = [data for path, data in self.posts if path == "/api/bundle"][-1]
        self.assertEqual(payload["scanner_input"], self.page.locator("#scanner").input_value().strip())
        self.assertEqual(payload["source_filename"], "pasted-evidence")
        self.assertEqual(payload["client_name"], "Northstar Community Bank")
        self.synthetic_guidance()
        self.assertEqual([data for path, data in self.posts if path == "/api/remediate"][-1]["scanner_input"],
                         json.loads(payload["scanner_input"]))
        self.page.locator("#manual").fill("Different manual evidence")
        self.assertTrue(self.page.locator("#remediation-out").is_hidden())
        self.assertTrue(self.page.locator("#remediate").is_disabled())

    def test_failed_replacement_retains_labelled_real_download(self):
        self.real_bundle()
        href = self.page.locator("#download").get_attribute("href")
        self.page.locator("#client").fill("Synthetic Client B")
        self.page.locator("#evidence-file").set_input_files({
            "name": "corrupt.json", "mimeType": "application/json", "buffer": b"{broken",
        })
        self.page.locator("#generate").click()
        self.page.locator("#errors").wait_for(state="visible")
        self.assertEqual(self.page.locator("#download").get_attribute("href"), href)
        self.assertTrue(self.page.locator("#result").is_visible())
        self.assertIn("Synthetic Client A", self.page.locator("#result-context").inner_text())
        self.page.locator("#evidence-file").set_input_files({
            "name": "oversize.json", "mimeType": "application/json", "buffer": b"x" * 2000001,
        })
        self.page.locator("#generate").click()
        self.page.wait_for_function("document.querySelector('#errors').textContent.includes('File exceeds')")
        self.assertEqual(self.page.locator("#download").get_attribute("href"), href)
        with self.page.expect_download() as event:
            self.page.locator("#download").click()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "retained.zip"
            event.value.save_as(path)
            self.assertTrue(validate_bundle(path.read_bytes())["valid"])

    def test_cancel_and_input_change_discard_synthetic_late_bundle(self):
        self.real_bundle()
        href = self.page.locator("#download").get_attribute("href")
        held = []
        self.page.route("**/api/bundle", lambda route: held.append(route))
        for action in [lambda: self.page.locator("#cancel").click(),
                       lambda: self.page.locator("#client").fill("Synthetic Client B")]:
            count = len(self.downloads)
            self.page.locator("#generate").click()
            self.page.wait_for_timeout(100)
            self.assertTrue(held)
            action()
            self.assertTrue(self.page.locator("#generate").is_enabled())
            self.assertTrue(self.page.locator("#cancel").is_disabled())
            self.release_synthetic_late_response(held.pop())
            self.assertEqual(len(self.downloads), count)
            self.assertEqual(self.page.locator("#download").get_attribute("href"), href)
            self.assertIn("Synthetic Client A", self.page.locator("#result-context").inner_text())
        self.assertIn("server work may still finish", self.page.locator("#operation-status").inner_text())

    def test_cancel_retry_timer_prevents_synthetic_second_request(self):
        calls = []
        def rate_limit(route):
            calls.append(route.request)
            route.fulfill(status=429, headers={"Retry-After": "1"}, content_type="application/json", body='{"error":"rate limit"}')
        self.page.route("**/api/bundle", rate_limit)
        self.page.locator("#generate").click()
        self.page.wait_for_function("document.querySelector('#progress').textContent.includes('retrying')")
        self.page.locator("#cancel").click()
        self.page.wait_for_timeout(1250)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(self.downloads), 0)
        self.assertTrue(self.page.locator("#generate").is_enabled())

    def test_cancel_synthetic_file_read_and_reset_private_fields(self):
        self.real_bundle()
        self.synthetic_guidance()
        self.page.locator("#api-key").fill("synthetic-private-test-key")
        self.page.locator("#manual").fill("synthetic private manual finding")
        # Synthetic delayed File.text completion, not an actual slow filesystem.
        self.page.evaluate("""() => {
          File.prototype.text = function() {
            return new Promise(resolve => { window.releaseSyntheticRead = () => resolve('{"violations":[]}'); });
          };
        }""")
        count = len(self.posts)
        downloads = len(self.downloads)
        self.page.locator("#generate").click()
        self.page.wait_for_function("typeof window.releaseSyntheticRead === 'function'")
        self.page.locator("#cancel").click()
        self.page.evaluate("window.releaseSyntheticRead()")
        self.page.wait_for_timeout(150)
        self.assertEqual(len(self.posts), count)
        self.assertEqual(len(self.downloads), downloads)
        self.page.locator("#new-report").click()
        for selector in ["#client", "#agency", "#api-key", "#scanner", "#manual", "#evidence-file", "#logo"]:
            self.assertEqual(self.page.locator(selector).input_value(), "")
        self.assertIsNone(self.page.locator("#download").get_attribute("href"))
        self.assertTrue(self.page.locator("#result").is_hidden())
        self.assertTrue(self.page.locator("#remediation-out").is_hidden())
        for selector in ["#summary", "#result-context", "#remediation-text", "#remediation-meta", "#errors"]:
            self.assertEqual(self.page.locator(selector).inner_text(), "")
        self.assertIsNotNone(self.page.locator("#scanner").get_attribute("required"))

    def test_reset_and_evidence_change_discard_synthetic_late_guidance(self):
        self.real_bundle()
        held = []
        self.page.route("**/api/remediate", lambda route: held.append(route))
        self.page.locator("#remediate").click()
        self.page.wait_for_timeout(100)
        self.assertEqual(len(held), 1)
        self.upload({"violations": []}, "synthetic-b.json")
        try:
            held.pop().fulfill(status=200, content_type="application/json", body='{"guidance":"STALE CLIENT A"}')
        except PlaywrightError:
            pass
        self.page.wait_for_timeout(150)
        self.assertTrue(self.page.locator("#remediation-out").is_hidden())
        self.assertEqual(self.page.locator("#remediation-text").inner_text(), "")
        self.assertTrue(self.page.locator("#remediate").is_disabled())
        self.real_bundle()
        self.page.locator("#remediate").click()
        self.page.wait_for_timeout(100)
        self.page.locator("#new-report").click()
        try:
            held.pop().fulfill(status=200, content_type="application/json", body='{"guidance":"STALE AFTER RESET"}')
        except PlaywrightError:
            pass
        self.page.wait_for_timeout(150)
        self.assertTrue(self.page.locator("#result").is_hidden())
        self.assertEqual(self.page.locator("#remediation-text").inner_text(), "")
        self.assertEqual(self.page.locator("#api-key").input_value(), "")


if __name__ == "__main__":
    unittest.main()
