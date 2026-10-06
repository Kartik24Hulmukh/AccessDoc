"""Synthetic loopback/cancellable-resolver proof of absolute exporter budgets.

No provider calls. Event waits pace the intentionally hostile collector or
synchronize native ownership; no production sleep/grace is added.
"""
import asyncio
import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import aiohttp
from app import otlp_export
from app.deadline import wait as wait_until
from app.gateway_transport import PooledSession


class Collector(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        s = self.server
        with s.guard:
            s.received += 1
            s.active += 1
            s.peak = max(s.peak, s.active)
        s.started.set()
        try:
            if s.mode == "headers":
                s.release.wait(2)
            if s.mode == "hold":
                s.release.wait(2)
            if s.mode == "multi":
                wait_until(s.release, time.monotonic() + .05)  # same absolute per-response delay
            if s.mode == "header-trickle":
                self.connection.sendall(b"HTTP/1.1 200 OK\r\nX-Trickle: ")
                for _ in range(30):
                    if s.release.wait(.02):
                        break
                    self.connection.sendall(b"x")
                return
            body = b" " * 14 + b"{}" if s.mode == "body" else b"{}"
            if s.mode == "oversized":
                body = b" " * 65_536 + b"{}"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            if s.mode == "body":
                for byte in body:
                    if s.release.wait(.02):
                        break
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()
            else:
                self.wfile.write(body)
        except OSError:
            pass
        finally:
            with s.guard:
                s.active -= 1


class ExportDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Collector)
        self.srv.mode = "ok"
        self.srv.started = threading.Event()
        self.srv.release = threading.Event()
        self.srv.guard = threading.Lock()
        self.srv.received = self.srv.active = self.srv.peak = 0
        self.runner = threading.Thread(target=lambda: self.srv.serve_forever(poll_interval=.01))
        self.runner.start()
        self.exporters = []
        self.endpoint = "http://127.0.0.1:%d/v1/traces" % self.srv.server_port

    def tearDown(self):
        self.srv.release.set()
        for ex in self.exporters:
            ex.shutdown(.5)
        self.srv.shutdown()
        self.srv.server_close()
        self.runner.join(2)

    def exporter(self, **kw):
        ex = otlp_export.OTLPExporter(endpoint=kw.pop("endpoint", self.endpoint),
                                     flush_interval=60, timeout=kw.pop("timeout", .12), **kw)
        self.exporters.append(ex)
        return ex

    def record(self, ex, n=1):
        for i in range(n):
            self.assertTrue(ex.record("synthetic-%d" % i, "a" * 32, "b" * 16, None, 1, 2))

    def measured(self, fn, upper=.24):
        before = time.monotonic()
        result = fn()
        elapsed = time.monotonic() - before
        self.assertLess(elapsed, upper)
        return result

    def test_native_body_and_headers_enforce_absolute_not_inactivity_deadline(self):
        for mode in ("body", "headers", "header-trickle"):
            with self.subTest(mode=mode):
                self.srv.mode = mode
                ex = self.exporter()
                self.record(ex)
                self.assertFalse(self.measured(lambda: ex.flush(1)))
                self.assertEqual(ex.stats()["failed_batches"], 1)
                self.assertEqual(ex.stats()["exported"], 0)
                self.assertEqual(ex.stats()["last_error"], "TIMEOUT")
                self.assertEqual(ex._session.snapshot()["active_calls"], 0)
                self.srv.release.set()
                ex.shutdown(.3)
                # Separate server barriers before the next hostile-response mode.
                self.srv.release = threading.Event()

    def test_dns_is_cancelled_inside_budget_without_late_post(self):
        cancelled = threading.Event()
        class Resolver:
            async def resolve(self, *a, **kw):
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            async def close(self):
                pass
        ex = self.exporter(endpoint="http://synthetic.invalid:%d/v1/traces" % self.srv.server_port)
        ex._session.resolver_factory = lambda loop: Resolver()
        self.record(ex)
        self.assertFalse(self.measured(lambda: ex.flush(.12)))
        self.assertTrue(cancelled.wait(.1))
        self.assertEqual(ex._session.snapshot()["active_calls"], 0)
        self.assertEqual(self.srv.received, 0)
        self.assertEqual(ex.stats()["last_error"], "TIMEOUT")

    def test_connect_cancellation_uses_same_absolute_budget(self):
        cancelled = threading.Event()
        async def stalled_connect(*a, **kw):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        ex = self.exporter()
        self.record(ex)
        with patch.object(aiohttp.TCPConnector, "_create_connection", stalled_connect):
            self.assertFalse(self.measured(lambda: ex.flush(.12)))
            self.assertTrue(cancelled.wait(.1))
        self.assertEqual(ex._session.snapshot()["active_calls"], 0)
        self.assertEqual(self.srv.received, 0)

    def test_real_tls_handshake_stall_is_inside_native_connect_budget(self):
        import socketserver
        accepted, release = threading.Event(), threading.Event()
        class Stall(socketserver.BaseRequestHandler):
            def handle(self):
                accepted.set()
                release.wait(2)  # accepts TCP, intentionally never replies to TLS
        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
        srv = Server(("127.0.0.1", 0), Stall)
        runner = threading.Thread(target=lambda: srv.serve_forever(poll_interval=.01))
        runner.start()
        try:
            ex = self.exporter(endpoint="https://127.0.0.1:%d/v1/traces" % srv.server_address[1])
            self.record(ex)
            self.assertFalse(self.measured(lambda: ex.flush(.12)))
            self.assertTrue(accepted.is_set())
            self.assertEqual(ex.stats()["last_error"], "TIMEOUT")
            self.assertEqual(ex._session.snapshot()["active_calls"], 0)
        finally:
            release.set()
            srv.shutdown()
            srv.server_close()
            runner.join(2)

    def test_decoded_response_is_bounded(self):
        self.srv.mode = "oversized"
        ex = self.exporter()
        self.record(ex)
        self.assertFalse(ex.flush(.5))
        self.assertEqual(ex.stats()["exported"], 0)
        self.assertEqual(ex.stats()["failed_spans"], 1)
        self.assertEqual(ex._session.snapshot()["active_calls"], 0)

    def test_many_batches_share_one_flush_budget(self):
        self.srv.mode = "multi"
        ex = self.exporter(timeout=.5)
        self.record(ex, 10)
        ex.max_batch = 1  # after enqueue: avoid waking daemon while arranging test
        self.assertFalse(self.measured(lambda: ex.flush(.14)))
        self.assertGreater(ex.stats()["queued"], 0)
        self.assertLess(self.srv.received, 10)
        self.assertEqual(ex._session.snapshot()["active_calls"], 0)

    def test_flush_waits_for_background_sender_and_never_sends_concurrently(self):
        self.srv.mode = "hold"
        ex = self.exporter(timeout=1, max_batch=1)
        self.record(ex)
        self.assertTrue(self.srv.started.wait(.5))
        self.record(ex)
        self.assertFalse(self.measured(lambda: ex.flush(.03), upper=.1))
        self.assertEqual(ex.stats()["queued"], 1)
        self.assertEqual(ex.stats()["inflight"], 1)
        self.assertEqual(self.srv.received, 1)
        self.srv.release.set()
        self.assertTrue(ex.flush(.5))
        self.assertEqual(ex.stats()["exported"], 2)
        self.assertEqual(self.srv.received, 2)
        self.assertEqual(self.srv.peak, 1)

    def test_flush_false_when_queue_overflow_is_observed_during_call(self):
        self.srv.mode = "hold"
        ex = self.exporter(timeout=1, max_queue=1)
        self.record(ex)
        result = []
        worker = threading.Thread(target=lambda: result.append(ex.flush(.5)))
        worker.start()
        try:
            self.assertTrue(self.srv.started.wait(.5))
            self.record(ex, 2)  # one queued record must be dropped
            self.srv.release.set()
            worker.join(1)
            self.assertEqual(result, [False])
            self.assertEqual(ex.stats()["exported"], 2)
            self.assertEqual(ex.stats()["dropped"], 1)
        finally:
            self.srv.release.set()
            worker.join(1)

    def test_flush_observes_background_failure_while_waiting(self):
        self.srv.mode = "hold"
        ex = self.exporter(max_batch=1)
        self.record(ex)
        self.assertTrue(self.srv.started.wait(.5))
        self.assertFalse(ex.flush(.5))
        self.assertEqual(ex.stats()["failed_batches"], 1)
        self.assertEqual(ex.stats()["queued"], 0)

    def test_shutdown_cancels_active_sender_and_counts_unsent_queue(self):
        self.srv.mode = "hold"
        ex = self.exporter(timeout=1, max_batch=1)
        self.record(ex)
        self.assertTrue(self.srv.started.wait(.5))
        self.record(ex, 5)
        self.assertFalse(self.measured(lambda: ex.shutdown(.05), upper=.15))
        self.assertFalse(ex.record("late", "a" * 32, "b" * 16, None, 1, 2))
        self.assertTrue(ex._session.closed)
        self.assertEqual(ex.stats()["queued"], 0)
        self.assertEqual(ex.stats()["shutdown_dropped"], 5)
        self.srv.release.set()
        ex._thread.join(.5)
        self.assertFalse(ex._thread.is_alive())
        self.assertEqual(ex._session.snapshot()["active_calls"], 0)
        self.assertEqual(self.srv.received, 1)

    def test_shutdown_uses_one_budget_for_drain_join_and_close(self):
        self.srv.mode = "body"
        ex = self.exporter(timeout=1)
        self.record(ex)
        self.assertFalse(self.measured(lambda: ex.shutdown(.1), upper=.2))
        self.assertEqual(ex.stats()["failed_batches"], 1)
        self.assertEqual(ex._session.snapshot()["active_calls"], 0)
        self.assertFalse(ex._thread.is_alive())

    def test_zero_budget_does_not_transmit_and_drops_queue_on_shutdown(self):
        ex = self.exporter()
        self.record(ex, 2)
        self.assertFalse(ex.flush(0))
        self.assertEqual(self.srv.received, 0)
        self.assertFalse(ex.shutdown(0))
        self.assertEqual(ex.stats()["shutdown_dropped"], 2)
        self.assertEqual(ex.stats()["queued"], 0)

    def test_collector_owner_close_does_not_stop_gateway_owner(self):
        other = PooledSession(1024)
        try:
            response = other.post(self.endpoint, headers={}, json={}, timeout=(1, 1))
            response.close()
            ex = self.exporter()
            self.record(ex)
            self.assertTrue(ex.flush(.5))
            self.assertIs(ex._session._engine, other._engine)
            self.assertTrue(ex.shutdown(.5))
            self.assertFalse(other.closed)
            response = other.post(self.endpoint, headers={}, json={}, timeout=(1, 1))
            response.close()
            self.assertEqual(other.snapshot()["active_calls"], 0)
        finally:
            other.close()

    def test_collector_does_not_inherit_gateway_proxy(self):
        with patch.dict("os.environ", {"GATEWAY_PROXY_URL": "http://127.0.0.1:9"}):
            ex = self.exporter()
            self.assertIsNone(ex._session.proxy)
            self.record(ex)
            self.assertTrue(ex.flush(.5))

    def test_process_shared_native_admission_wait_is_inside_export_budget(self):
        self.srv.mode = "hold"
        other = PooledSession(1024)
        entered = threading.Event()
        def occupy():
            entered.set()
            try:
                response = other.post(self.endpoint, headers={}, json={}, timeout=(1, 1))
                response.close()
            except Exception:
                pass
        with patch.dict("os.environ", {"GATEWAY_MAX_UPSTREAM_REQUESTS": "1"}):
            worker = threading.Thread(target=occupy)
            worker.start()
            try:
                self.assertTrue(entered.wait(.5))
                self.assertTrue(self.srv.started.wait(.5))
                ex = self.exporter()
                self.record(ex)
                self.assertFalse(self.measured(lambda: ex.flush(.12)))
                self.assertEqual(ex._session.snapshot()["capacity"], 1)
                self.assertEqual(self.srv.received, 1)  # only other owner sent
                self.assertEqual(ex.stats()["last_error"], "TIMEOUT")
                ex.shutdown(.2)
                self.assertFalse(other.closed)
            finally:
                self.srv.release.set()
                worker.join(2)
                other.close()

    def test_close_cleanup_wait_does_not_get_extra_grace_or_stop_other_owner(self):
        other = PooledSession(1024)
        cleanup_entered = threading.Event()
        cleanup_gate = []
        class Resolver:
            async def resolve(self, host, port=0, family=0):
                return [{"hostname": host, "host": "127.0.0.1", "port": port,
                         "family": 2, "proto": 0, "flags": 0}]
            async def close(self):
                cleanup_entered.set()
                gate = asyncio.Event()
                cleanup_gate.append(gate)
                await gate.wait()
        try:
            response = other.post(self.endpoint, headers={}, json={}, timeout=(1, 1))
            response.close()
            ex = self.exporter(endpoint="http://synthetic.invalid:%d/v1/traces" % self.srv.server_port)
            ex._session.resolver_factory = lambda loop: Resolver()
            self.record(ex)
            self.assertTrue(ex.flush(.5))
            self.assertFalse(self.measured(lambda: ex.shutdown(.03), upper=.12))
            self.assertTrue(cleanup_entered.is_set())
            self.assertFalse(ex._session.close(timeout=0))  # not a false idempotent success
            self.assertFalse(other.closed)
        finally:
            ex._session._engine.loop.call_soon_threadsafe(cleanup_gate[0].set)
            future = ex._session._close_future
            future.result(timeout=.5)
            other.close()
        self.assertTrue(ex._session.close(timeout=0))

    def test_payload_size_guard_fails_before_network(self):
        ex = self.exporter()
        self.record(ex)
        with patch.object(otlp_export, "_MAX_PAYLOAD_BYTES", 1):
            self.assertFalse(ex.flush(.5))
        self.assertEqual(ex.stats()["last_error"], "EXPORT_TOO_LARGE")
        self.assertEqual(self.srv.received, 0)


if __name__ == "__main__":
    unittest.main()
