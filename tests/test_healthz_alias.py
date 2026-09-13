"""Probe parity: /healthz is an exact alias of /health on app.main."""
import json
import os
import sys
import unittest
from http.server import HTTPServer
from threading import Thread
from urllib.request import urlopen

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.main import Handler


class HealthzAliasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        os.environ["ALLOWED_HOSTS"] = "127.0.0.1:%d" % cls.port
        Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close()
        os.environ.pop("ALLOWED_HOSTS", None)

    def _get(self, path):
        with urlopen("http://127.0.0.1:%d%s" % (self.port, path)) as r:
            return r.status, json.loads(r.read())

    def test_healthz_matches_health(self):
        s1, health = self._get("/health")
        s2, healthz = self._get("/healthz")
        self.assertEqual((s1, health), (s2, healthz))
        self.assertEqual(healthz["status"], "ok")
        self.assertIn("commit", healthz)

    def test_readyz_parity(self):
        s, body = self._get("/readyz")
        self.assertEqual(s, 200)
        self.assertEqual(body["status"], "ready")
        self.assertIn("commit", body)


if __name__ == "__main__":
    unittest.main()
