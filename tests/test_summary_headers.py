"""Contract: /api/bundle must emit X-AccessDoc-* summary headers (plan P1-1)."""

import json
import os
import threading
import unittest
import urllib.request

from app.main import Server, Handler


def _payload():
    # mirrors the repo SCANNER fixture: 1 critical + 1 serious, no unknown
    return {"scanner_input": json.dumps({
        "violations": [
            {"id": "image-alt", "impact": "critical", "nodes": [{"html": "<img>"}]},
            {"id": "color-contrast", "impact": "serious", "nodes": [{"html": "<p>"}]},
        ]
    })}


class BundleCountHeaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = Server(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        os.environ["ALLOWED_HOSTS"] = f"127.0.0.1:{cls.port},localhost:{cls.port}"
        os.environ["ALLOWED_ORIGINS"] = f"http://127.0.0.1:{cls.port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        os.environ.pop("ALLOWED_HOSTS", None)
        os.environ.pop("ALLOWED_ORIGINS", None)

    def _bundle(self):
        req = urllib.request.Request(
            "http://127.0.0.1:%d/api/bundle" % self.port,
            data=json.dumps(_payload()).encode(),
            headers={"Content-Type": "application/json", "Accept": "application/zip"},
            method="POST",
        )
        return urllib.request.urlopen(req, timeout=30)

    def test_bundle_emits_summary_count_headers(self):
        resp = self._bundle()
        self.assertEqual(resp.status, 200)
        hdr = resp.headers
        self.assertIsNotNone(hdr.get("X-AccessDoc-Finding-Count"))
        self.assertIsNotNone(hdr.get("X-AccessDoc-Instance-Count"))
        self.assertIsNotNone(hdr.get("X-AccessDoc-Unmapped-Count"))
        self.assertEqual(int(hdr["X-AccessDoc-Finding-Count"]), 2, "2 violations")
        self.assertGreaterEqual(int(hdr["X-AccessDoc-Instance-Count"]), 2, "instances")
        self.assertEqual(int(hdr["X-AccessDoc-Unmapped-Count"]), 0, "0 unknown")

    def test_bundle_headers_are_digits_not_em_dash(self):
        resp = self._bundle()
        for name in ("X-AccessDoc-Finding-Count", "X-AccessDoc-Instance-Count", "X-AccessDoc-Unmapped-Count"):
            value = resp.headers.get(name)
            self.assertIsNotNone(value)
            self.assertNotIn("—", value or "", "em-dash must never ship as a count")
            self.assertTrue(value.isdigit(), "%s must be a digit, got %r" % (name, value))


if __name__ == "__main__":
    unittest.main()
