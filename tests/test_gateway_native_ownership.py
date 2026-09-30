"""Real loopback headers, cancelled DNS, global admission and owned shutdown."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
import socket
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from app.gateway import ModelGateway, CANONICAL_CHAIN
from app.gateway_budget import prompt_token_bound


class NativeGatewayOwnershipTests(unittest.TestCase):
    def setUp(self):
        # Each capacity/lifecycle fixture starts a fresh process engine; the
        # global limit is configured once at engine startup, not per caller.
        from app.gateway_transport import shutdown_transport
        shutdown_transport()
        self.addCleanup(shutdown_transport)

    def server(self, drip=False, missing_usage=False, overspend=False):
        received = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                data["received_traceparent"] = self.headers.get("traceparent")
                received.append(data)
                try:
                    if drip:
                        self.connection.sendall(b"HTTP/1.1 200 OK\r\nX-Drip: ")
                        for _ in range(30):
                            self.connection.sendall(b"x")
                            threading.Event().wait(0.02)
                        self.connection.sendall(b"\r\nContent-Length: 2\r\n\r\n{}")
                        return
                    out = {"choices": [{"message": {"content":
                        "" if missing_usage and len(received) == 1 else "ok"}}]}
                    if not missing_usage:
                        out["usage"] = {"total_tokens": 20 if not overspend else
                            prompt_token_bound(data["messages"]) + data["max_tokens"] + 1}
                    body = json.dumps(out).encode()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except OSError:
                    pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        runner = threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.01))
        runner.start()
        self.addCleanup(runner.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server, received

    def test_slow_headers_share_deadline_in_serial_and_hedged_modes(self):
        server, received = self.server(drip=True)
        for delay in ("-1", "30"):
            gw = ModelGateway(api_key="synthetic", chain=(CANONICAL_CHAIN[0],),
                              budget_seconds=0.15, max_retries=0)
            try:
                with patch.dict(os.environ, {"GATEWAY_HEDGE_DELAY_MS": delay}), patch(
                        "app.gateway.MELIOUS_BASE_URL",
                        "http://127.0.0.1:%d" % server.server_port), patch.object(gw, "_log"):
                    start = time.monotonic()
                    result = gw.chat("fix contrast")
                    elapsed = time.monotonic() - start
                self.assertTrue(result.fallback)
                self.assertLess(elapsed, 0.20, "headers escaped total budget")
                self.assertEqual(gw._session.snapshot()["active_calls"], 0)
                self.assertEqual(gw._session.snapshot()["inflight"], 0)
            finally:
                gw._session.close()
        self.assertEqual(len(received), 2, "must actually exercise response headers")

    def test_cancelled_dns_cannot_transmit_late_primary_request(self):
        server, received = self.server()
        cancelled = threading.Event()
        class Resolver:
            calls = 0
            future = None
            async def resolve(self, host, port=0, family=socket.AF_INET):
                Resolver.calls += 1
                if Resolver.calls == 1:
                    Resolver.future = asyncio.get_running_loop().create_future()
                    try:
                        await Resolver.future
                    except asyncio.CancelledError:
                        cancelled.set()
                        raise
                return [{"hostname": host, "host": "127.0.0.1", "port": port,
                         "family": socket.AF_INET, "proto": 0, "flags": 0}]
            async def close(self):
                pass
        gw = ModelGateway(api_key="synthetic", chain=CANONICAL_CHAIN[:2],
                          budget_seconds=0.3, max_retries=0)
        gw._session.resolver_factory = lambda loop: Resolver()
        try:
            with patch.dict(os.environ, {"GATEWAY_HEDGE_DELAY_MS": "30",
                    "NO_PROXY": "native-test.invalid", "HTTP_PROXY": "", "HTTPS_PROXY": ""}), patch(
                    "app.gateway.MELIOUS_BASE_URL",
                    "http://native-test.invalid:%d" % server.server_port), patch.object(gw, "_log"):
                from app import telemetry
                trace_id = "1234567890abcdef1234567890abcdef"
                telemetry.start_trace("00-" + trace_id + "-1234567890abcdef-01")
                try:
                    result = gw.chat("fix contrast")
                finally:
                    telemetry.clear()
                self.assertEqual(received[0]["received_traceparent"].split("-")[1], trace_id)
                self.assertEqual(result.model, CANONICAL_CHAIN[1])
                self.assertTrue(cancelled.wait(0.2))
                self.assertTrue(Resolver.future.cancelled())
                self.assertEqual(gw._session.snapshot()["active_calls"], 0)
                self.assertEqual([r["model"] for r in received], [CANONICAL_CHAIN[1]])
                self.assertFalse(any(t.name == "gateway-hedge" for t in threading.enumerate()))
                self.assertFalse(result.token_usage_known)
                self.assertLessEqual(result.token_budget["peak_reserved_tokens"], gw.token_budget)
        finally:
            gw._session.close()
        self.assertFalse(gw._session.snapshot()["loop_alive"])

    def test_process_wide_admission_is_retained_until_actual_io_terminates(self):
        server, received = self.server(drip=True)
        gw = ModelGateway(api_key="synthetic", chain=(CANONICAL_CHAIN[0],),
                          budget_seconds=0.2, max_retries=0)
        try:
            with patch.dict(os.environ, {"GATEWAY_MAX_UPSTREAM_REQUESTS": "2",
                        "GATEWAY_HEDGE_DELAY_MS": "-1"}), patch(
                    "app.gateway.MELIOUS_BASE_URL",
                    "http://127.0.0.1:%d" % server.server_port), patch.object(gw, "_log"):
                with ThreadPoolExecutor(max_workers=12) as pool:
                    results = list(pool.map(lambda _: gw.chat("fix contrast"), range(12)))
                self.assertTrue(all(r.fallback for r in results))
                stats = gw._session.snapshot()
                self.assertEqual(stats["capacity"], 2)
                self.assertLessEqual(stats["peak_inflight"], 2)
                self.assertEqual(stats["active_calls"], 0)
                self.assertEqual(stats["inflight"], 0)
                self.assertGreater(len(received), 0)
        finally:
            gw._session.close()
        self.assertFalse(gw._session.snapshot()["loop_alive"])

    def test_circuit_skip_does_not_wait_past_absolute_deadline(self):
        gw = ModelGateway(api_key="synthetic", chain=CANONICAL_CHAIN[:1], budget_seconds=0.03)
        self.addCleanup(gw._session.close)
        gw.breakers[CANONICAL_CHAIN[0]].trip()
        with patch.dict(os.environ, {"GATEWAY_HEDGE_DELAY_MS": "500"}), patch.object(gw, "_log"):
            started = time.monotonic()
            result = gw.chat("fix contrast")
        self.assertTrue(result.fallback)
        self.assertLess(time.monotonic() - started, 0.10)

    def test_408_retry_wait_is_cancelled_when_sibling_wins(self):
        received = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                received.append(data["model"])
                if data["model"] == CANONICAL_CHAIN[0]:
                    self.send_response(408)
                    self.send_header("Retry-After", "2")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                else:
                    body = json.dumps({"choices": [{"message": {"content": "ok"}}],
                                       "usage": {"total_tokens": 20}}).encode()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        runner = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01))
        runner.start()
        try:
            for budget in (3.0, 0.2):
                received.clear()
                gw = ModelGateway(api_key="synthetic", chain=CANONICAL_CHAIN[:2],
                                  budget_seconds=budget, base_backoff=0, max_sleep=2, max_retries=1)
                try:
                    with patch.dict(os.environ, {"GATEWAY_HEDGE_DELAY_MS": "30"}), patch(
                            "app.gateway.MELIOUS_BASE_URL", "http://127.0.0.1:%d" % server.server_port), patch.object(gw, "_log"):
                        started = time.monotonic()
                        result = gw.chat("fix contrast")
                        elapsed = time.monotonic() - started
                    self.assertEqual(result.model, CANONICAL_CHAIN[1])
                    self.assertLess(elapsed, 0.2)
                    self.assertEqual(received, list(CANONICAL_CHAIN[:2]))
                    self.assertFalse(any(t.name == "gateway-hedge" for t in threading.enumerate()))
                    self.assertEqual(gw._session.snapshot()["active_calls"], 0)
                finally:
                    gw._session.close()
        finally:
            server.shutdown(); server.server_close(); runner.join(2)

    def test_ambient_proxy_and_netrc_discovery_are_not_enabled(self):
        server, received = self.server()
        with patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:1",
                "http_proxy": "http://127.0.0.1:1", "GATEWAY_PROXY_URL": "",
                "NO_PROXY": "", "no_proxy": "", "GATEWAY_HEDGE_DELAY_MS": "-1"}):
            gw = ModelGateway(api_key="synthetic", chain=CANONICAL_CHAIN[:1], max_retries=0)
            try:
                with patch("app.gateway.MELIOUS_BASE_URL", "http://127.0.0.1:%d" % server.server_port), patch.object(gw, "_log"):
                    result = gw.chat("fix contrast")
                self.assertFalse(result.fallback)
                self.assertEqual(len(received), 1)
                self.assertIsNone(gw._session.proxy)
                self.assertTrue(all(not client.trust_env for client, _ in gw._session._engine.clients.values()))
            finally:
                gw._session.close()

    def test_known_billing_hold_cancels_stalled_speculative_sibling(self):
        received, release, hedge_seen = [], threading.Event(), threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                received.append(data["model"])
                if data["model"] != CANONICAL_CHAIN[0]:
                    hedge_seen.set()
                    release.wait(3)
                    return
                hedge_seen.wait(1)  # controlled unknown-billing interval, no timing guess
                body = json.dumps({"error": {"type": "billing_error", "code": "insufficient_quota"}}).encode()
                self.send_response(429)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try: self.wfile.write(body)
                except OSError: pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        runner = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01))
        runner.start()
        gw = ModelGateway(api_key="synthetic", chain=CANONICAL_CHAIN[:2], budget_seconds=3)
        observed_hold = []
        hold = gw._hold_billing
        def record_hold(model):
            hold(model)
            observed_hold.append(time.monotonic())
        try:
            with patch.dict(os.environ, {"GATEWAY_HEDGE_DELAY_MS": "30"}), patch(
                    "app.gateway.MELIOUS_BASE_URL", "http://127.0.0.1:%d" % server.server_port), patch.object(gw, "_log"), patch.object(gw, "_hold_billing", side_effect=record_hold):
                result = gw.chat("fix contrast")
                returned = time.monotonic()
                self.assertTrue(result.fallback)
                self.assertTrue(gw.billing_exhausted())
                self.assertTrue(observed_hold)
                self.assertLess(returned - observed_hold[0], 0.2)
                self.assertEqual(received, list(CANONICAL_CHAIN[:2]))
                initial = len(received)
                for _ in range(5): self.assertTrue(gw.chat("again").fallback)
                self.assertEqual(len(received), initial)
                self.assertEqual(gw._session.snapshot()["active_calls"], 0)
                self.assertFalse(any(t.name == "gateway-hedge" for t in threading.enumerate()))
        finally:
            release.set(); gw._session.close()
            server.shutdown(); server.server_close(); runner.join(2)

    def test_missing_usage_cannot_reauthorize_the_same_budget(self):
        server, received = self.server(missing_usage=True)
        prompt = "fix contrast"
        messages = [{"role": "system", "content": "You are an accessibility remediation engineer."},
                    {"role": "user", "content": prompt}]
        ceiling = prompt_token_bound(messages) + 100
        gw = ModelGateway(api_key="synthetic", chain=CANONICAL_CHAIN[:2],
                          token_budget=ceiling, max_retries=0)
        try:
            with patch.dict(os.environ, {"GATEWAY_HEDGE_DELAY_MS": "-1",
                        "GATEWAY_MAX_TOKENS": "100"}), patch(
                    "app.gateway.MELIOUS_BASE_URL",
                    "http://127.0.0.1:%d" % server.server_port), patch.object(gw, "_log"):
                result = gw.chat(prompt)
            self.assertTrue(result.fallback)
            self.assertEqual([r["max_tokens"] for r in received], [100])
            self.assertEqual(result.tokens, ceiling)
            self.assertFalse(result.token_usage_known)
        finally:
            gw._session.close()

    def test_reported_overspend_is_not_a_successful_answer(self):
        server, received = self.server(overspend=True)
        gw = ModelGateway(api_key="synthetic", chain=CANONICAL_CHAIN[:2],
                          token_budget=500, max_retries=0)
        try:
            with patch.dict(os.environ, {"GATEWAY_HEDGE_DELAY_MS": "-1"}), patch(
                    "app.gateway.MELIOUS_BASE_URL",
                    "http://127.0.0.1:%d" % server.server_port), patch.object(gw, "_log"):
                result = gw.chat("fix contrast")
            self.assertTrue(result.fallback)
            self.assertEqual(len(received), 1)
            self.assertTrue(result.token_budget["contract_violation"])
            self.assertGreater(result.token_budget["observed_tokens"], 500)
            self.assertLessEqual(result.token_budget["peak_reserved_tokens"], 500)
        finally:
            gw._session.close()