"""Launch-critical hardening: token budgets, W3C trace propagation, chunked body reads."""
import io
import json
import os
import sys
import threading
import unittest
from contextlib import redirect_stdout
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import telemetry
from app.gateway import ModelGateway


def _ok(tokens, text="fix alt text"):
    return 200, {}, {"choices": [{"message": {"content": text}}],
                     "usage": {"total_tokens": tokens}}


class TelemetryTests(unittest.TestCase):
    def test_parse_valid_and_invalid_traceparent(self):
        tid, sid = "0af7651916cd43dd8448eb211c80319c", "b7ad6b7169203331"
        self.assertEqual(telemetry.parse_traceparent("00-%s-%s-01" % (tid, sid)), (tid, sid, "01"))
        for bad in ("", None, "garbage", "00-" + "0" * 32 + "-" + sid + "-01",
                    "ff-%s-%s-01" % (tid, sid), "<script>" * 20):
            self.assertIsNone(telemetry.parse_traceparent(bad), bad)

    def test_start_trace_adopts_inbound_trace_id_and_mints_new_span(self):
        tid, sid = "0af7651916cd43dd8448eb211c80319c", "b7ad6b7169203331"
        ctx = telemetry.start_trace("00-%s-%s-01" % (tid, sid))
        self.assertEqual(ctx["trace_id"], tid)
        self.assertEqual(ctx["parent_span_id"], sid)
        self.assertNotEqual(ctx["span_id"], sid)
        self.assertRegex(telemetry.traceparent_header(ctx), r"^00-[0-9a-f]{32}-[0-9a-f]{16}-01$")

    def test_log_event_is_single_json_line_with_trace_ids(self):
        telemetry.start_trace()
        buf = io.StringIO()
        with redirect_stdout(buf):
            telemetry.log_event("probe", status=200)
        lines = buf.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 1)
        rec = json.loads(lines[0])
        for k in ("ts", "level", "event", "trace_id", "span_id", "status"):
            self.assertIn(k, rec)

    def test_span_nests_under_current_trace(self):
        root = telemetry.start_trace()
        with redirect_stdout(io.StringIO()):
            with telemetry.span("child", model="x") as child:
                self.assertEqual(child["trace_id"], root["trace_id"])
                self.assertEqual(child["parent_span_id"], root["span_id"])
        self.assertEqual(telemetry.current()["span_id"], root["span_id"])

    def test_trace_context_is_thread_isolated(self):
        seen = {}
        def worker(i):
            seen[i] = telemetry.start_trace()["trace_id"]
        ts = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(len(set(seen.values())), 8)


class TokenBudgetTests(unittest.TestCase):
    def test_token_budget_stops_chain_and_falls_back_to_static_kb(self):
        calls = []
        def transport(model, messages):
            calls.append(model)
            # every model answers 200 but with an empty completion so the chain
            # keeps advancing; each attempt burns 3000 tokens.
            return 200, {}, {"choices": [{"message": {"content": ""}}],
                             "usage": {"total_tokens": 3000}}
        gw = ModelGateway(transport=transport, token_budget=5000, max_retries=0)
        with redirect_stdout(io.StringIO()):
            res = gw.chat("remediate 1.1.1")
        self.assertTrue(res.fallback)
        self.assertEqual(res.model, "static-kb")
        self.assertLessEqual(len(calls), 2, calls)  # 3000 + 3000 >= 5000 -> stop

    def test_token_budget_never_raises_without_static_fallback_unhandled(self):
        gw = ModelGateway(transport=lambda m, msgs: _ok(9000, ""), token_budget=100, max_retries=0)
        with redirect_stdout(io.StringIO()):
            with self.assertRaises(Exception):
                gw.chat("x", static_fallback=False)

    def test_successful_call_reports_tokens_spent_and_default_budget_from_env(self):
        os.environ["GATEWAY_TOKEN_BUDGET"] = "777"
        try:
            gw = ModelGateway(transport=lambda m, msgs: _ok(42))
        finally:
            del os.environ["GATEWAY_TOKEN_BUDGET"]
        self.assertEqual(gw.token_budget, 777)
        buf = io.StringIO()
        with redirect_stdout(buf):
            res = gw.chat("x")
        self.assertFalse(res.fallback)
        recs = [json.loads(l) for l in buf.getvalue().splitlines() if l.strip()]
        call = [r for r in recs if r["event"] == "gateway_call"][0]
        self.assertEqual(call["tokens_spent"], 42)
        self.assertIn("trace_id", call)
        health = gw.health()
        self.assertEqual(health["token_budget"], 777)
        self.assertIn(health["tracing"], ("opentelemetry", "w3c-traceparent"))


class PerModelReadTimeoutTests(unittest.TestCase):
    def test_slow_reasoning_model_gets_longer_window_clamped_to_budget(self):
        gw = ModelGateway(transport=lambda m, msgs: _ok(1), read_timeout=15.0)
        self.assertEqual(gw.read_timeout_for("glm-5.3"), 15.0)
        self.assertGreaterEqual(gw.read_timeout_for("kimi-k3"), 25.0)
        self.assertEqual(gw.read_timeout_for("kimi-k3", remaining=7.0), 7.0)
        self.assertEqual(gw.read_timeout_for("kimi-k3", remaining=0.2), 0.2)

    def test_env_override_wins(self):
        os.environ["GATEWAY_READ_TIMEOUT_QWEN3_8_27B"] = "22"
        try:
            gw = ModelGateway(transport=lambda m, msgs: _ok(1), read_timeout=15.0)
            self.assertEqual(gw.read_timeout_for("qwen3.8-27b"), 22.0)
        finally:
            del os.environ["GATEWAY_READ_TIMEOUT_QWEN3_8_27B"]


class HostedAdapterStreamingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.main import Handler
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.srv.server_address[1]
        os.environ["ALLOWED_HOSTS"] = "127.0.0.1:%d,localhost:%d" % (cls.port, cls.port)
        cls.t = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.t.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close()
        os.environ.pop("ALLOWED_HOSTS", None)

    def _conn(self):
        return HTTPConnection("127.0.0.1", self.port, timeout=10)

    def test_healthz_echoes_traceparent_with_same_trace_id(self):
        tid = "0af7651916cd43dd8448eb211c80319c"
        c = self._conn()
        c.request("GET", "/healthz", headers={"Host": "127.0.0.1:%d" % self.port,
                                                 "traceparent": "00-%s-b7ad6b7169203331-01" % tid})
        r = c.getresponse(); r.read(); c.close()
        self.assertEqual(r.status, 200)
        tp = r.getheader("traceparent")
        self.assertIsNotNone(tp)
        self.assertEqual(tp.split("-")[1], tid)
        self.assertNotEqual(tp.split("-")[2], "b7ad6b7169203331")

    def test_readyz_mints_root_trace_when_header_absent_or_malformed(self):
        for hdr in ({}, {"traceparent": "<img src=x onerror=alert(1)>"}):
            c = self._conn()
            h = {"Host": "127.0.0.1:%d" % self.port}; h.update(hdr)
            c.request("GET", "/readyz", headers=h)
            r = c.getresponse(); r.read(); c.close()
            self.assertIn(r.status, (200, 503))
            self.assertRegex(r.getheader("traceparent"), r"^00-[0-9a-f]{32}-[0-9a-f]{16}-01$")

    def test_truncated_body_is_rejected_not_hung(self):
        import socket
        s = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        req = ("POST /generate HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nContent-Type: application/json\r\n"
               "Content-Length: 200000\r\nConnection: close\r\n\r\n" % self.port).encode() + b"{" * 1000
        s.sendall(req); s.shutdown(socket.SHUT_WR)
        data = s.recv(65536); s.close()
        self.assertTrue(data.startswith(b"HTTP/1.1 4") or data == b"", data[:80])


if __name__ == "__main__":
    unittest.main()
