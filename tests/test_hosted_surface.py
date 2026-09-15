"""Hosted surface contract for the Vercel adapter (launch turn 17).

Vercel routes every path to api/handler.py, so the report builder in public/
must be served from the handler or the product is dark in production. These
tests pin: browser content negotiation on '/', the static allowlist, docs +
OpenAPI, hardened headers, and X-Request-ID on every verb.
"""
import json
import http.client
import unittest
from http.server import HTTPServer
from threading import Thread
from urllib.request import urlopen, Request
from urllib.error import HTTPError

BROWSER_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
UP = "." * 2  # path-traversal segment, spelled out so tooling never trips on it


class HostedSurfaceTests(unittest.TestCase):
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
        cls.server.server_close()

    def _get(self, path, accept=None, method="GET"):
        headers = {"Accept": accept} if accept else {}
        req = Request(f"http://127.0.0.1:{self.port}{path}", headers=headers, method=method)
        resp = urlopen(req, timeout=10)
        self.addCleanup(resp.close)
        return resp

    # ---- '/' negotiates: browsers get the UI, API clients keep JSON ----
    def test_root_serves_ui_to_browsers(self):
        resp = self._get("/", BROWSER_ACCEPT)
        body = resp.read().decode()
        self.assertEqual(resp.status, 200)
        self.assertTrue(resp.headers["Content-Type"].startswith("text/html"))
        self.assertIn('<form id="report-form"', body)
        self.assertIn("/static/app.js", body)
        self.assertIn("untagged", body)  # HTML-primary / PDF limitation copy
        self.assertIn("attestation.intoto.json", body)  # all six ZIP members named
        self.assertEqual(resp.headers["Vary"], "Accept")
        csp = resp.headers["Content-Security-Policy"]
        self.assertIn("script-src 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertNotIn("unsafe-inline", csp)

    def test_root_keeps_json_health_for_api_clients(self):
        for accept in (None, "*/*", "application/json", "application/json, text/html;q=0.5"):
            resp = self._get("/", accept)
            self.assertTrue(resp.headers["Content-Type"].startswith("application/json"), accept)
            data = json.loads(resp.read())
            self.assertEqual(data["status"], "ok")
            self.assertIn("/docs", data["endpoints"])

    # ---- static allowlist ----
    def test_static_assets_served_with_correct_types(self):
        expect = {
            "/index.html": "text/html",
            "/static/app.css": "text/css",
            "/static/app.js": "text/javascript",
            "/static/report.css": "text/css",
            "/sample/axe-sample.json": "application/json",
            "/docs": "text/html",
            "/openapi.json": "application/json",
        }
        for path, ctype in expect.items():
            resp = self._get(path)
            self.assertEqual(resp.status, 200, path)
            self.assertTrue(resp.headers["Content-Type"].startswith(ctype), path)
            self.assertEqual(resp.headers["X-Content-Type-Options"], "nosniff")
            self.assertIn("no-store", resp.headers["Cache-Control"])
            self.assertTrue(resp.headers["X-Request-ID"], path)
            self.assertTrue(len(resp.read()) > 0, path)

    def test_sample_is_valid_axe_json(self):
        data = json.loads(self._get("/sample/axe-sample.json").read())
        self.assertIsInstance(data["violations"], list)

    def test_openapi_document_is_coherent(self):
        spec = json.loads(self._get("/openapi.json").read())
        from app.models import VERSION
        from app.limits import MAX_HTTP_BODY_BYTES
        self.assertTrue(spec["openapi"].startswith("3.1"))
        self.assertEqual(spec["info"]["version"], VERSION)
        self.assertEqual(set(spec["paths"]), {"/readyz", "/limits", "/api/bundle", "/api/remediate"})
        limits_schema = spec["paths"]["/limits"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        self.assertEqual(limits_schema["properties"]["max_http_body_bytes"]["const"], MAX_HTTP_BODY_BYTES)
        for path in ("/api/bundle", "/api/remediate"):
            self.assertIn("post", spec["paths"][path])
        text = json.dumps(spec).lower()
        for banned in ("100% compliant", "legal defense", "guarantee"):
            self.assertNotIn(banned, text, banned)

    def test_docs_page_is_accessible_and_honest(self):
        body = self._get("/docs").read().decode()
        self.assertIn('lang="en"', body)
        self.assertIn('href="#main"', body)
        self.assertIn("/openapi.json", body)
        self.assertIn("2 MiB", body)
        self.assertIn("does not establish WCAG, ADA, EAA, or legal compliance", body)
        self.assertNotIn("<script", body)

    # ---- nothing outside the allowlist leaks ----
    def test_traversal_and_unlisted_paths_are_404_json(self):
        for path in (f"/static/{UP}/api/handler.py", "/static/%2e%2e/app/main.py", "/public/index.html",
                     "/static/", "/static/nope.js", f"/docs/{UP}/VERSION", "/sample/", "/.env", "/openapi.yaml"):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            conn.request("GET", path)
            resp = conn.getresponse()
            body = resp.read()
            conn.close()
            self.assertEqual(resp.status, 404, path)
            self.assertTrue(resp.getheader("Content-Type", "").startswith("application/json"), path)
            self.assertIn("request_id", json.loads(body), path)

    def test_static_paths_reject_post(self):
        req = Request(f"http://127.0.0.1:{self.port}/static/app.js", data=b"{}",
                      headers={"Content-Type": "application/json"}, method="POST")
        with self.assertRaises(HTTPError) as cm:
            urlopen(req, timeout=10)
        self.addCleanup(cm.exception.close)
        self.assertEqual(cm.exception.code, 404)

    # ---- hardened headers on every verb ----
    def test_hardened_headers_and_request_id_on_every_verb(self):
        for path, accept in (("/readyz", None), ("/limits", None), ("/", BROWSER_ACCEPT), ("/docs", None)):
            resp = self._get(path, accept)
            self.assertEqual(resp.headers["Permissions-Policy"], "camera=(), microphone=(), geolocation=(), payment=(), usb=()", path)
            self.assertEqual(resp.headers["Cross-Origin-Opener-Policy"], "same-origin", path)
            self.assertEqual(resp.headers["Cross-Origin-Resource-Policy"], "same-origin", path)
            self.assertEqual(resp.headers["Referrer-Policy"], "no-referrer", path)
            self.assertRegex(resp.headers["X-Request-ID"], r"^[0-9a-f]{12}$", path)
        head = self._get("/index.html", method="HEAD")
        self.assertEqual(head.status, 200)
        self.assertTrue(head.headers["Content-Type"].startswith("text/html"))
        self.assertEqual(head.read(), b"")

    def test_api_json_csp_stays_locked_down(self):
        resp = self._get("/readyz")
        self.assertEqual(resp.headers["Content-Security-Policy"], "default-src 'none'; frame-ancestors 'none'")


if __name__ == "__main__":
    unittest.main()
