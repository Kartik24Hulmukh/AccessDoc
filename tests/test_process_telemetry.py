"""Process/telemetry surface on health probes (launch turn 11).

Sessions 8, 9 and 10 all recorded the same launch-telemetry gap: no RAM
floor/ceiling numbers were ever emitted by either runtime, so capacity claims
were unverifiable. These tests pin the fix: /healthz (both the Vercel adapter
and the threaded server) now reports a bounded process block (peak + live
RSS, active threads) and a runtime block (python version, uptime).
"""
import json
import unittest
from http.server import HTTPServer
from threading import Thread
from urllib.request import urlopen, Request


class HostedHealthProcessTests(unittest.TestCase):
    """api/handler.py (Vercel serverless adapter)."""

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

    def _get(self, path):
        resp = urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=10)
        self.addCleanup(resp.close)
        return resp

    def test_healthz_reports_process_memory_and_runtime(self):
        body = json.loads(self._get("/healthz").read())
        proc = body["process"]
        self.assertGreater(proc["max_rss_kib"], 0)
        self.assertGreater(proc["rss_kib"], 0)
        self.assertGreaterEqual(proc["threads"], 1)
        rt = body["runtime"]
        self.assertRegex(rt["python"], r"^\d+\.\d+")
        self.assertGreaterEqual(rt["uptime_seconds"], 0)

    def test_readyz_reports_same_process_block(self):
        body = json.loads(self._get("/readyz").read())
        self.assertGreater(body["process"]["max_rss_kib"], 0)
        self.assertIn("python", body["runtime"])


class ThreadedHealthProcessTests(unittest.TestCase):
    """app/main.py (Docker/Fly/Render threaded server)."""

    @classmethod
    def setUpClass(cls):
        import os
        from app.main import Server, Handler
        cls.server = Server(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        os.environ["ALLOWED_HOSTS"] = f"127.0.0.1:{cls.port}"
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        import os
        cls.server.shutdown()
        cls.server.server_close()
        os.environ.pop("ALLOWED_HOSTS", None)

    def _get(self, path):
        req = Request(f"http://127.0.0.1:{self.port}{path}")
        resp = urlopen(req, timeout=10)
        self.addCleanup(resp.close)
        return resp

    def test_healthz_reports_process_memory_and_runtime(self):
        body = json.loads(self._get("/healthz").read())
        self.assertEqual(body["status"], "ok")
        proc = body["process"]
        self.assertGreater(proc["max_rss_kib"], 0)
        self.assertGreater(proc["rss_kib"], 0)
        self.assertGreaterEqual(proc["threads"], 1)
        self.assertGreaterEqual(body["runtime"]["uptime_seconds"], 0)

    def test_process_stats_helper_is_bounded_and_int(self):
        from app.main import process_stats
        s = process_stats()
        for k in ("max_rss_kib", "rss_kib", "threads"):
            self.assertIsInstance(s[k], int)
            self.assertGreater(s[k], 0)
            self.assertLess(s[k], 1 << 40)  # absurd-value guard
