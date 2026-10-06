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
    response_body = b"{}"
    content_type = "application/json"
    content_encoding = None

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(n)
        _Collector.received.append((self.path, dict(self.headers), json.loads(body)))
        self.send_response(_Collector.status)
        body = b"" if _Collector.status == 204 else _Collector.response_body
        self.send_header("Content-Type", _Collector.content_type)
        if _Collector.content_encoding:
            self.send_header("Content-Encoding", _Collector.content_encoding)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
        _Collector.response_body = b"{}"
        _Collector.content_type = "application/json"
        _Collector.content_encoding = None
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
        self.assertEqual(span["kind"], 1)
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
        self.assertFalse(ex.flush(1.0))
        st = ex.stats()
        self.assertEqual(st["failed_batches"], 1)
        self.assertEqual(st["exported"], 0)
        self.assertTrue(st["last_error"])
        ex.shutdown(0.5)

    def test_collector_5xx_drops_batch_without_retry_and_recovers(self):
        _Collector.status = 503
        ex = otlp_export.OTLPExporter(endpoint=self.endpoint, flush_interval=60, timeout=2)
        ex.record("s", "a" * 32, "b" * 16, None, 1, 2)
        self.assertFalse(ex.flush(2.0))
        self.assertEqual(ex.stats()["failed_batches"], 1)
        self.assertEqual(len(_Collector.received), 1)
        _Collector.status = 200
        ex.record("s2", "a" * 32, "b" * 16, None, 1, 2)
        ex.flush(2.0)
        self.assertEqual(ex.stats()["exported"], 1)
        ex.shutdown(0.5)

    def test_record_server_kind_and_default_internal(self):
        ex = otlp_export.OTLPExporter(endpoint=self.endpoint, flush_interval=60)
        try:
            ex.record("internal", "a" * 32, "b" * 16, None, 1, 2)
            ex.record("server", "a" * 32, "c" * 16, None, 1, 2, kind=2)
            self.assertTrue(ex.flush(1))
            spans = _Collector.received[0][2]["resourceSpans"][0]["scopeSpans"][0]["spans"]
            self.assertEqual([s["kind"] for s in spans], [1, 2])
        finally:
            ex.shutdown(.5)

    def test_partial_rejection_counted_separately_and_never_retried(self):
        _Collector.response_body = json.dumps({"partialSuccess": {
            "rejectedSpans": "1", "errorMessage": "PRIVATE-COLLECTOR-MESSAGE"}}).encode()
        ex = otlp_export.OTLPExporter(endpoint=self.endpoint, flush_interval=60)
        try:
            for i in range(3):
                ex.record("s", "a" * 32, "b" * 16, None, 1, 2)
            self.assertFalse(ex.flush(1))
            st = ex.stats()
            self.assertEqual(st["exported"], 2)
            self.assertEqual(st["rejected_spans"], 1)
            self.assertEqual(st["failed_spans"], 0)
            self.assertEqual(st["failed_batches"], 1)
            self.assertEqual(st["last_error"], "COLLECTOR_REJECTED")
            self.assertNotIn("PRIVATE", json.dumps(st))
            self.assertTrue(ex.flush(1))  # empty call, NOT historical-loss recovery
            self.assertEqual(len(_Collector.received), 1)
        finally:
            ex.shutdown(.5)

    def test_reject_unexpected_http_status(self):
        for status in (201, 202, 204, 301, 302, 307, 429, 500):
            with self.subTest(status=status):
                _Collector.status = status
                ex = otlp_export.OTLPExporter(endpoint=self.endpoint, flush_interval=60)
                try:
                    before = len(_Collector.received)
                    ex.record("s", "a" * 32, "b" * 16, None, 1, 2)
                    self.assertFalse(ex.flush(1))
                    self.assertEqual(ex.stats()["exported"], 0)
                    self.assertEqual(ex.stats()["last_error"], "HTTP_STATUS")
                    self.assertEqual(len(_Collector.received), before + 1)
                finally:
                    ex.shutdown(.5)

    def test_conservative_malformed_acknowledgement(self):
        bodies = [b"", b"not json", b"[]", b"null", b'{"unknown":1}',
                  b'{"partialSuccess":null}', b'{"partialSuccess":{"rejectedSpans":true}}',
                  b'{"partialSuccess":{"rejectedSpans":-1}}',
                  b'{"partialSuccess":{"rejectedSpans":"2"}}',
                  b'{"partialSuccess":{"rejectedSpans":1.0}}',
                  b'{"partialSuccess":{"rejectedSpans":"1.0"}}',
                  b'{"partialSuccess":{"errorMessage":123}}',
                  b'{"partialSuccess":{"rejectedSpans":0,"rejectedSpans":1}}',
                  b'{"partialSuccess":{"rejectedSpans":NaN}}', b'\xff']
        for body in bodies:
            with self.subTest(body=body):
                _Collector.response_body = body
                ex = otlp_export.OTLPExporter(endpoint=self.endpoint, flush_interval=60)
                try:
                    ex.record("s", "a" * 32, "b" * 16, None, 1, 2)
                    self.assertFalse(ex.flush(1))
                    self.assertEqual(ex.stats()["exported"], 0)
                    self.assertEqual(ex.stats()["failed_spans"], 1)
                    self.assertEqual(ex.stats()["rejected_spans"], 0)
                    self.assertEqual(ex.stats()["last_error"], "INVALID_RESPONSE")
                finally:
                    ex.shutdown(.5)

    def test_zero_rejections_and_full_rejection(self):
        for part, exported, rejected in [({}, 1, 0), ({"rejectedSpans": "0",
                "errorMessage": "PRIVATE-WARNING"}, 1, 0), ({"rejectedSpans": 1}, 0, 1)]:
            _Collector.response_body = json.dumps({"partialSuccess": part}).encode()
            ex = otlp_export.OTLPExporter(endpoint=self.endpoint, flush_interval=60)
            try:
                ex.record("s", "a" * 32, "b" * 16, None, 1, 2)
                self.assertEqual(ex.flush(1), not rejected)
                self.assertEqual(ex.stats()["exported"], exported)
                self.assertEqual(ex.stats()["rejected_spans"], rejected)
                self.assertNotIn("PRIVATE", json.dumps(ex.stats()))
            finally:
                ex.shutdown(.5)

    def test_response_type_and_compressed_decoded_bounds(self):
        import gzip
        for content_type, coding, body in [("text/html", None, b"{}"),
                ("application/json", "gzip", gzip.compress(b" " * 100_000 + b"{}"))]:
            with self.subTest(content_type=content_type, coding=coding):
                _Collector.content_type, _Collector.content_encoding = content_type, coding
                _Collector.response_body = body
                ex = otlp_export.OTLPExporter(endpoint=self.endpoint, flush_interval=60)
                try:
                    ex.record("s", "a" * 32, "b" * 16, None, 1, 2)
                    self.assertFalse(ex.flush(1))
                    self.assertEqual(ex.stats()["exported"], 0)
                    self.assertEqual(ex.stats()["failed_spans"], 1)
                finally:
                    ex.shutdown(.5)

    def test_record_fields_and_attribute_count_are_bounded(self):
        ex = otlp_export.OTLPExporter(endpoint=self.endpoint, service_name="s" * 1000,
                                      flush_interval=60)
        try:
            attrs = {str(i) + "k" * 300: "v" * 1000 for i in range(100)}
            ex.record("n" * 1000, "a" * 32, "b" * 16, None, 1, 2, attrs)
            self.assertTrue(ex.flush(1))
            span = _Collector.received[0][2]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
            self.assertEqual(len(span["name"]), 128)
            self.assertEqual(len(span["attributes"]), 32)
            self.assertTrue(all(len(a["key"]) == 128 for a in span["attributes"]))
            self.assertTrue(all(len(a["value"]["stringValue"]) == 256 for a in span["attributes"]))
        finally:
            ex.shutdown(.5)

    def test_queue_batch_and_time_configuration_bounds(self):
        for kwargs in ({"max_queue": 0}, {"max_queue": 2049}, {"max_batch": 0},
                       {"max_batch": 257}, {"timeout": 0}, {"timeout": float("nan")},
                       {"flush_interval": float("inf")}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                otlp_export.OTLPExporter(endpoint=self.endpoint, **kwargs)


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
        self.assertEqual(hz[0]["kind"], 2)
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
