"""Regression coverage: /api/generate and /api/v1/generate must actually work.

Before this fix, both routes referenced Branding/AuditRequest/parse_input/
generate_pdf/generate_html -- none of which exist in this codebase after the
evidence-bundle refactor. Every call raised NameError, caught by the generic
exception handler and returned as an opaque 500 GENERATION_FAILED. This was
the documented (docs/API_V1.md) primary hosted API contract and it was
100% non-functional. This test file locks in the fix.
"""
import json
import os
import unittest
import zipfile
from http.server import HTTPServer
from threading import Thread
from urllib.request import urlopen, Request
from urllib.error import HTTPError

from app.main import Handler

SCANNER = json.dumps({
    "violations": [
        {"id": "image-alt", "impact": "critical", "nodes": [{"html": "<img>"}]},
        {"id": "color-contrast", "impact": "serious", "nodes": [{"html": "<p>"}]},
    ]
})


class GenerateEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        os.environ["ALLOWED_HOSTS"] = f"127.0.0.1:{cls.port},localhost:{cls.port}"
        os.environ["ALLOWED_ORIGINS"] = f"http://127.0.0.1:{cls.port}"
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        os.environ.pop("ALLOWED_HOSTS", None)
        os.environ.pop("ALLOWED_ORIGINS", None)

    def _post(self, path, body):
        req = Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            resp = urlopen(req)
            return resp.status, json.loads(resp.read())
        except HTTPError as e:
            return e.code, json.loads(e.read())

    def test_generate_alias_returns_201_with_download_token(self):
        status, data = self._post("/api/generate", {"scanner_input": SCANNER, "client_name": "Acme"})
        self.assertEqual(status, 201, data)
        self.assertIn("report_token", data)
        self.assertEqual(data["finding_count"], 2)
        self.assertEqual(data["severity_counts"]["critical"], 1)
        self.assertEqual(data["severity_counts"]["serious"], 1)

    def test_v1_generate_returns_201_and_token_downloads_pdf(self):
        status, data = self._post("/api/v1/generate", {"scanner_input": SCANNER})
        self.assertEqual(status, 201, data)
        token = data["report_token"]
        pdf_resp = urlopen(f"http://127.0.0.1:{self.port}{data['download_url']}")
        self.assertEqual(pdf_resp.status, 200)
        pdf_bytes = pdf_resp.read()
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        html_resp = urlopen(f"http://127.0.0.1:{self.port}{data['html_companion_url']}")
        self.assertEqual(html_resp.status, 200)
        receipt_resp = urlopen(f"http://127.0.0.1:{self.port}{data['receipt_url']}")
        receipt = json.loads(receipt_resp.read())
        self.assertEqual(receipt["schema_version"], "1.2")

    def test_invalid_scanner_input_is_422_not_500(self):
        status, data = self._post("/api/generate", {"scanner_input": "not json"})
        self.assertEqual(status, 422, data)
        self.assertEqual(data["error"]["code"], "INVALID_INPUT")

    def test_missing_scanner_input_is_422_not_500(self):
        status, data = self._post("/api/generate", {})
        self.assertEqual(status, 422, data)

    def test_bundle_endpoint_still_returns_zip(self):
        req = Request(
            f"http://127.0.0.1:{self.port}/api/bundle",
            data=json.dumps({"scanner_input": SCANNER}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urlopen(req)
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.headers.get("Content-Type"), "application/zip")
        zf = zipfile.ZipFile(__import__("io").BytesIO(resp.read()))
        self.assertIn("report.pdf", zf.namelist())


if __name__ == "__main__":
    unittest.main()
