"""Hosted /metrics parity: the serverless adapter mirrors app/main.py.

Launch hardening turn 13: the threaded server (app/main.py) has always exposed
a Prometheus /metrics surface, but the Vercel serverless adapter
(api/handler.py) answered 404 there - SREs scraping the hosted production
target saw no counters at all. These tests pin the hosted exposition:
counter parity, circuit-open gauges for every chain model, the turn-11 RAM
floor/ceiling gauges, HEAD safety, bounded secret-free output.
"""
import os, sys, unittest
from http.server import HTTPServer
from threading import Thread
from urllib.request import urlopen, Request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api.handler import handler as serverless_handler
from app.main import Handler as threaded_handler
from app import remediate
from app.gateway import ModelGateway, CANONICAL_CHAIN

COUNTERS = ("requests_total", "errors_total", "reports_total",
            "overload_rejections_total", "client_disconnects_total")


def _parse(text):
    out = {}
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, _, value = line.rpartition(" ")
        out[name] = float(value)
    return out


def _ok_transport(model, messages):
    return 200, {}, {"choices": [{"message": {"content": "plan"}}],
                     "usage": {"total_tokens": 7}}


class HostedMetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), serverless_handler)
        cls.port = cls.server.server_address[1]
        Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _get(self, path, method="GET"):
        req = Request("http://127.0.0.1:%d%s" % (self.port, path), method=method)
        with urlopen(req, timeout=10) as r:
            return r.status, r.read(), dict(r.headers)

    def test_metrics_exposition_contract(self):
        status, body, hdrs = self._get("/metrics")
        self.assertEqual(status, 200)
        self.assertIn("text/plain; version=0.0.4", hdrs.get("Content-Type", ""))
        metrics = _parse(body.decode())
        for name in COUNTERS:
            self.assertIn("accessdoc_" + name, metrics)
        for model in CANONICAL_CHAIN:
            self.assertIn('accessdoc_gateway_circuit_open{model="%s"}' % model, metrics)
        for gauge in ("accessdoc_process_rss_kib", "accessdoc_process_max_rss_kib",
                      "accessdoc_process_threads", "accessdoc_runtime_uptime_seconds"):
            self.assertIn(gauge, metrics)

    def test_counters_move_on_traffic(self):
        before = _parse(self._get("/metrics")[1].decode())
        req = Request("http://127.0.0.1:%d/api/bundle" % self.port,
                      data=b'{"violations": "not-a-list"',
                      headers={"Content-Type": "application/json"}, method="POST")
        status = None
        try:
            with urlopen(req, timeout=10) as r:
                status = r.status
        except Exception as exc:
            status = getattr(exc, "code", None)
        self.assertEqual(status, 400)
        after = _parse(self._get("/metrics")[1].decode())
        self.assertGreater(after["accessdoc_requests_total"], before["accessdoc_requests_total"])
        self.assertGreater(after["accessdoc_errors_total"], before["accessdoc_errors_total"])

    def test_head_metrics_is_bodyless(self):
        status, body, hdrs = self._get("/metrics", method="HEAD")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")
        self.assertGreater(int(hdrs.get("Content-Length", "0")), 0)

    def test_exposition_is_bounded_and_secret_free(self):
        text = self._get("/metrics")[1].decode()
        lines = [l for l in text.splitlines() if l.strip()]
        self.assertLess(len(lines), 64)
        for line in lines:
            self.assertLess(len(line), 200)
        self.assertNotIn("sk-mel", text)
        self.assertNotIn("ghp_", text)

    def test_threaded_server_parity(self):
        server = HTTPServer(("127.0.0.1", 0), threaded_handler)
        port = server.server_address[1]
        os.environ["ALLOWED_HOSTS"] = "127.0.0.1:%d" % port
        os.environ["RATE_LIMIT_PER_MINUTE"] = "100000"
        Thread(target=server.serve_forever, daemon=True).start()
        try:
            remediate.reset_gateway(ModelGateway(transport=_ok_transport,
                                                  base_backoff=0.001, max_sleep=0.002))
            with urlopen("http://127.0.0.1:%d/metrics" % port, timeout=10) as r:
                threaded = _parse(r.read().decode())
            hosted = _parse(self._get("/metrics")[1].decode())
            for name in COUNTERS:
                self.assertIn("accessdoc_" + name, threaded)
                self.assertIn("accessdoc_" + name, hosted)
            for model in CANONICAL_CHAIN:
                gauge = 'accessdoc_gateway_circuit_open{model="%s"}' % model
                self.assertIn(gauge, threaded)
                self.assertIn(gauge, hosted)
        finally:
            server.shutdown()
            server.server_close()
            os.environ.pop("ALLOWED_HOSTS", None)
            os.environ.pop("RATE_LIMIT_PER_MINUTE", None)
            remediate.reset_gateway(None)


if __name__ == "__main__":
    unittest.main()
