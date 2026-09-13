"""Self-hosted deploy health-check coverage for app.main (Docker/Fly/Railway/Render).

Vercel serverless deploys already report commit SHA via api/handler.py using
VERCEL_GIT_COMMIT_SHA. Self-hosted deploys of app/main.py had no exact-SHA
reporting at all, which blocked the reviewed-deployment production gate
(health must report the exact reviewed SHA). This covers that gap.
"""
import json
import os
import unittest
from http.server import HTTPServer
from threading import Thread
from urllib.request import urlopen

from app.main import Handler


class AppMainHealthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        os.environ["ALLOWED_HOSTS"] = f"127.0.0.1:{cls.port},localhost:{cls.port}"
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        os.environ.pop("ALLOWED_HOSTS", None)

    def _get(self, path):
        resp = urlopen(f"http://127.0.0.1:{self.port}{path}")
        return json.loads(resp.read())

    def test_health_reports_commit(self):
        data = self._get("/health")
        self.assertEqual(data["status"], "ok")
        self.assertIn("commit", data)
        self.assertTrue(data["commit"])

    def test_version_reports_commit(self):
        data = self._get("/version")
        self.assertIn("commit", data)
        self.assertTrue(data["commit"])

    def test_readyz_reports_commit(self):
        data = self._get("/readyz")
        self.assertIn("commit", data)
        self.assertTrue(data["commit"])

    def test_commit_env_override_takes_priority(self):
        os.environ["ACCESSDOC_COMMIT_SHA"] = "deadbeefcafef00d"
        try:
            data = self._get("/health")
            self.assertEqual(data["commit"], "deadbeefcafef00d")
        finally:
            del os.environ["ACCESSDOC_COMMIT_SHA"]


if __name__ == "__main__":
    unittest.main()
