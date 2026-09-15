"""Tests for the Vercel HTTP handler (v0.7.0-beta.6)."""
import json
import unittest
import zipfile
from http.server import HTTPServer
from threading import Thread
from urllib.request import urlopen, Request
from urllib.error import HTTPError
from io import BytesIO
from app.bundle import MEMBERS

SAMPLE_AXE = json.dumps({
    "url": "https://example.com",
    "testEngine": {"name": "axe-core", "version": "4.11.2"},
    "violations": [
        {"id": "image-alt", "impact": "critical",
         "description": "Images must have alternate text",
         "helpUrl": "https://dequeuniversity.com/rules/axe/4.11/image-alt",
         "nodes": [{"html": "<img src='x.png'>"}]}
    ],
    "passes": [], "incomplete": []
})


class HandlerTests(unittest.TestCase):
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

    def test_generate_alias_returns_actionable_hint(self):
        """Serverless has no artifact store; /api/generate must point to /api/bundle."""
        for path in ("/api/generate", "/api/v1/generate"):
            req = Request(f"http://127.0.0.1:{self.port}{path}",
                          data=json.dumps({"scanner_input": SAMPLE_AXE}).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
            with self.assertRaises(HTTPError) as cm:
                urlopen(req)
            self.assertEqual(cm.exception.code, 404)
            body = json.loads(cm.exception.read())
            self.assertIn("/api/bundle", body["error"])
            self.assertIn("request_id", body)
            with self.assertRaises(HTTPError) as cm2:
                urlopen(f"http://127.0.0.1:{self.port}{path}")
            self.assertEqual(cm2.exception.code, 404)
            self.assertIn("/api/bundle", json.loads(cm2.exception.read())["error"])

    def test_health_check(self):
        resp = urlopen(f"http://127.0.0.1:{self.port}/")
        data = json.loads(resp.read())
        self.assertEqual(data["status"], "ok")
        self.assertIn("adapter_version", data)

    def test_success_contract(self):
        body = json.dumps({
            "scanner_input": SAMPLE_AXE,
            "client_name": "Test",
            "agency_name": "Agency",
            "audit_date": "2026-07-23",
        }).encode()
        req = Request(
            f"http://127.0.0.1:{self.port}/",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urlopen(req)
        zip_bytes = resp.read()
        with zipfile.ZipFile(BytesIO(zip_bytes)) as z:
            self.assertEqual(set(z.namelist()), set(MEMBERS))

    def test_missing_scanner_input_returns_400(self):
        body = json.dumps({"client_name": "X"}).encode()
        req = Request(
            f"http://127.0.0.1:{self.port}/",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as ctx:
            urlopen(req)
        self.assertEqual(ctx.exception.code, 400)

    def test_empty_body_returns_400(self):
        req = Request(
            f"http://127.0.0.1:{self.port}/",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as ctx:
            urlopen(req)
        self.assertEqual(ctx.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
