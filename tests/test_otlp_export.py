"""OTLP/HTTP span exporter: bounded, non-blocking, collector-failure safe."""
import json
import os
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app import otlp_export, telemetry


class _Collector(BaseHTTPRequestHandler):
    received = []
    status = 200

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(n)
        _Collector.received.append((self.path, dict(self.headers), json.loads(body)))
        self.send_response(_Collector.status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass


class OTLPExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), _Collector)
        cls.port = cls.srv.server_address[1]
        cls.t = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.t.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.t.join(2)

    def setUp(self):
        _Collector.received.clear()
        _Collector.status = 200
        self.endpoint = "http://127.0.0.1:%d/v1/traces" % self.port

    def tearDown(self):
        otlp_export.reset_exporter(None)

    def test_disabled_without_endpoint(self):
        os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
        os.environ.pop("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", None)
        ex = otlp_export.OTLPExporter(endpoint="")
        self.assertFalse(ex.enabled)
        self.assertFalse(ex.record("x", "a" * 32, "b" * 16, None, 1, 2))
        self.assertEqual(ex.stats()["exported"], 0)
        ex.shutdown()

    def test_base_endpoint_gets_v1_traces_suffix(self):
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://collector:4318/"
        os.environ.pop("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", None)
        try:
            self.assertEqual(otlp_export._endpoint(), "http://collector:4318/v1/traces")
        finally:
            os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)

    def test_spans_reach_collector_as_otlp_json(self):
        ex = otlp_export.OTLPExporter(endpoint=self.endpoint, service_name="accessdoc-test", flush_interval=60, timeout=2)
        otlp_export.reset_exporter(ex)
        telemetry.start_trace("00-" + "a" * 32 + "-" + "b" * 16 + "-01")
        with telemetry.span("ingest", size=1234, fmt="axe", ok=True):
            pass
        self.assertTrue(ex.flush(2.0))
        self.assertEqual(len(_Collector.received), 1)
        path, headers, payload = _Collector.received[0]
        self.assertEqual(path, "/v1/traces")
        self.assertEqual(headers["Content-Type"], "application/json")
        rs = payload["resourceSpans"][0]
        attrs = {a["key"]: a["value"] for a in rs["resource"]["attributes"]}
        self.assertEqual(attrs["service.name"], {"stringValue": "accessdoc-test"})
        span = rs["scopeSpans"][0]["spans"][0]
        self.assertEqual(span["name"], "ingest")
        self.assertEqual(span["traceId"], "a" * 32)
        self.assertEqual(len(span["spanId"]), 16)
        self.assertTrue(span["parentSpanId"])
        self.assertLess(int(span["startTimeUnixNano"]), int(span["endTimeUnixNano"]) + 1)
        sa = {a["key"]: a["value"] for a in span["attributes"]}
        self.assertEqual(sa["size"], {"intValue": "1234"})
        self.assertEqual(sa["fmt"], {"stringValue": "axe"})
        self.assertEqual(sa["ok"], {"boolValue": True})
        self.assertEqual(span["status"]["code"], 1)
        self.assertEqual(ex.stats()["exported"], 1)

    def test_exception_marks_span_error_and_propagates(self):
        ex = otlp_export.OTLPExporter(endpoint=self.endpoint, flush_interval=60)
        otlp_export.reset_exporter(ex)
        with self.assertRaises(ValueError):
            with telemetry.span("boom"):
                raise ValueError("x")
        ex.flush(2.0)
        span = _Collector.received[0][2]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        self.assertEqual(span["status"]["code"], 2)

    def test_bounded_queue_drops_oldest_never_blocks(self):
        ex = otlp_export.OTLPExporter(endpoint="http://127.0.0.1:9/v1/traces", flush_interval=60, timeout=0.2, max_queue=8, max_batch=100)
        t0 = time.monotonic()
        for i in range(1000):
            ex.record("s%d" % i, "a" * 32, "b" * 16, None, 1, 2)
        self.assertLess(time.monotonic() - t0, 1.0)
        st = ex.stats()
        self.assertEqual(st["queued"], 8)
        self.assertEqual(st["dropped"], 992)
        ex.shutdown(0.5)

    def test_collector_down_is_counted_not_raised(self):
        ex = otlp_export.OTLPExporter(endpoint="http://127.0.0.1:9/v1/traces", flush_interval=60, timeout=0.3)
        ex.record("s", "a" * 32, "b" * 16, None, 1, 2)
        ex.flush(1.0)
        st = ex.stats()
        self.assertEqual(st["failed_batches"], 1)
        self.assertEqual(st["exported"], 0)
        self.assertTrue(st["last_error"])
        ex.shutdown(0.5)

    def test_collector_5xx_drops_batch_and_resets_connection(self):
        _Collector.status = 503
        ex = otlp_export.OTLPExporter(endpoint=self.endpoint, flush_interval=60, timeout=2)
        ex.record("s", "a" * 32, "b" * 16, None, 1, 2)
        ex.flush(2.0)
        self.assertEqual(ex.stats()["failed_batches"], 1)
        self.assertIsNone(ex._conn)
        _Collector.status = 200
        ex.record("s2", "a" * 32, "b" * 16, None, 1, 2)
        ex.flush(2.0)
        self.assertEqual(ex.stats()["exported"], 1)
        ex.shutdown(0.5)

    def test_headers_env_parsed(self):
        os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = "Authorization=Bearer%20abc,x-team=sre"
        try:
            h = otlp_export._headers()
        finally:
            os.environ.pop("OTEL_EXPORTER_OTLP_HEADERS", None)
        self.assertEqual(h["Authorization"], "Bearer abc")
        self.assertEqual(h["x-team"], "sre")

    def test_http_server_span_exported_with_inbound_parent(self):
        from app.main import Handler, Server
        import urllib.request
        ex = otlp_export.OTLPExporter(endpoint=self.endpoint, flush_interval=60, timeout=2)
        otlp_export.reset_exporter(ex)
        srv = Server(("127.0.0.1", 0), Handler)
        os.environ["ALLOWED_HOSTS"] = "127.0.0.1:%d" % srv.server_address[1]
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            req = urllib.request.Request("http://127.0.0.1:%d/healthz" % srv.server_address[1],
                                         headers={"traceparent": "00-" + "c" * 32 + "-" + "d" * 16 + "-01"})
            with urllib.request.urlopen(req, timeout=5) as r:
                self.assertEqual(r.status, 200)
            req = urllib.request.Request("http://127.0.0.1:%d/readyz" % srv.server_address[1])
            with urllib.request.urlopen(req, timeout=5) as r:
                body = json.loads(r.read())
            self.assertIn("tracing", body)
            self.assertTrue(body["tracing"]["enabled"])
        finally:
            os.environ.pop("ALLOWED_HOSTS", None)
            srv.shutdown()
            srv.server_close()
            th.join(2)
        self.assertTrue(ex.flush(2.0))
        spans = [s for _, _, p in _Collector.received for s in p["resourceSpans"][0]["scopeSpans"][0]["spans"]]
        hz = [s for s in spans if s["name"] == "GET /healthz"]
        self.assertEqual(len(hz), 1)
        self.assertEqual(hz[0]["traceId"], "c" * 32)
        self.assertEqual(hz[0]["parentSpanId"], "d" * 16)
        sa = {a["key"]: a["value"] for a in hz[0]["attributes"]}
        self.assertEqual(sa["http.response.status_code"], {"intValue": "200"})
        self.assertEqual(sa["http.route"], {"stringValue": "/healthz"})

    def test_export_status_shape(self):
        st = telemetry.export_status()
        for k in ("enabled", "exported", "dropped", "failed_batches", "queued", "sdk"):
            self.assertIn(k, st)


if __name__ == "__main__":
    unittest.main()
