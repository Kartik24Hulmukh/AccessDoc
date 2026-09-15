"""Hosted abuse-control coverage: optional API-key gate + /limits discovery endpoint.

Addresses the "Hosted Abuse Controls" production gate from the 13 Sept 2026
hardening plan: when ACCESSDOC_API_KEYS is unset (the default, e.g. local CLI
use or a private deployment), behavior is unchanged and no key is required.
When an operator sets ACCESSDOC_API_KEYS for a public hosted deployment, every
POST to a generation endpoint must present a matching X-API-Key header or is
rejected with 401 before any capacity/parsing work happens.
"""
import json
import os
import unittest
from http.server import HTTPServer
from threading import Thread
from urllib.request import urlopen, Request
from urllib.error import HTTPError

from app.main import Handler

SAMPLE = json.dumps({
    "scanner_input": json.dumps({
        "violations": [
            {"id": "image-alt", "impact": "critical", "nodes": [{"html": "<img>"}]}
        ]
    }),
    "client_name": "Acme",
}).encode()


class ApiKeyAuthTests(unittest.TestCase):
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

    def tearDown(self):
        os.environ.pop("ACCESSDOC_API_KEYS", None)

    def _post(self, body, headers=None):
        req = Request(
            f"http://127.0.0.1:{self.port}/api/generate",
            data=body,
            headers=dict(headers or {}, **{"Content-Type": "application/json"}),
            method="POST",
        )
        try:
            resp = urlopen(req)
            return resp.status, json.loads(resp.read())
        except HTTPError as e:
            with e:
                return e.code, json.loads(e.read())

    def test_no_keys_configured_allows_request(self):
        status, data = self._post(SAMPLE)
        self.assertEqual(status, 201)

    def test_missing_key_rejected_when_configured(self):
        os.environ["ACCESSDOC_API_KEYS"] = "secret-key-1,secret-key-2"
        status, data = self._post(SAMPLE)
        self.assertEqual(status, 401)
        self.assertEqual(data["error"]["code"], "UNAUTHORIZED")

    def test_wrong_key_rejected(self):
        os.environ["ACCESSDOC_API_KEYS"] = "secret-key-1"
        status, data = self._post(SAMPLE, {"X-API-Key": "wrong"})
        self.assertEqual(status, 401)

    def test_correct_key_accepted(self):
        os.environ["ACCESSDOC_API_KEYS"] = "secret-key-1,secret-key-2"
        status, data = self._post(SAMPLE, {"X-API-Key": "secret-key-2"})
        self.assertEqual(status, 201)

    def test_limits_endpoint_reports_auth_state(self):
        resp = urlopen(f"http://127.0.0.1:{self.port}/limits")
        data = json.loads(resp.read())
        self.assertIn("max_violations", data)
        self.assertIn("api_key_required", data)
        self.assertIn("rate_limit_per_minute", data)
        self.assertFalse(data["api_key_required"])

    def test_limits_endpoint_reflects_key_requirement(self):
        os.environ["ACCESSDOC_API_KEYS"] = "secret-key-1"
        resp = urlopen(f"http://127.0.0.1:{self.port}/limits")
        data = json.loads(resp.read())
        self.assertTrue(data["api_key_required"])


if __name__ == "__main__":
    unittest.main()
