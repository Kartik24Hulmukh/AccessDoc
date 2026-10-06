"""Header-only rejection must not occupy scarce generation permits.

Real loopback sockets, event-observed drain entry, and explicit peer half-close
make the slow-upload schedule deterministic without changing the body deadline.
"""
import http.client
import json
import os
import socket
import threading
import unittest
from contextlib import ExitStack
from email.message import Message
from unittest.mock import patch

from app import main
from app.bundle import validate_bundle
from app.limits import LimitExceeded, MAX_HTTP_BODY_BYTES


class TrackedCapacity:
    def __init__(self, size):
        self.pool = threading.BoundedSemaphore(size)
        self.calls = 0
        self.accepted = 0
        self.released = 0
        self.lock = threading.Lock()

    def acquire(self, *args, **kwargs):
        with self.lock:
            self.calls += 1
        result = self.pool.acquire(*args, **kwargs)
        if result:
            with self.lock:
                self.accepted += 1
        return result

    def release(self):
        self.pool.release()
        with self.lock:
            self.released += 1


class HeaderAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.capacity = TrackedCapacity(2)
        self.connections = TrackedCapacity(16)
        self.observed = threading.Condition()
        self.draining = set()
        self.drain_finished = set()
        self.completed = 0
        self.errors = []
        owner = self

        class ObservedHandler(main.Handler):
            def _drain(handler, n, deadline=None):
                with owner.observed:
                    owner.draining.add(handler.client_address)
                    owner.observed.notify_all()
                try:
                    return super()._drain(n, deadline)
                finally:
                    with owner.observed:
                        owner.drain_finished.add(handler.client_address)
                        owner.observed.notify_all()

        class ObservedServer(main.Server):
            def handle_error(server, *args):
                owner.errors.append("unhandled handler error")

            def process_request_thread(server, *args):
                try:
                    return super().process_request_thread(*args)
                finally:
                    with owner.observed:
                        owner.completed += 1
                        owner.observed.notify_all()

        self.server = ObservedServer(("127.0.0.1", 0), ObservedHandler)
        self.env = {
            "ACCESSDOC_REQUIRE_AUTH": "false", "ACCESSDOC_API_KEY": "",
            "ACCESSDOC_API_KEYS": "", "ACCESSDOC_GENERATION_ENABLED": "true",
            "ACCESSDOC_REMEDIATION_ENABLED": "false",
            "RATE_LIMIT_PER_MINUTE": "100000",
            "ALLOWED_HOSTS": f"127.0.0.1:{self.server.server_port}",
            "ALLOWED_ORIGINS": "http://127.0.0.1",
            # Keep production defaults, not the edgeprobe's shortened budget.
            "BODY_TIMEOUT_SECONDS": "15", "SOCKET_TIMEOUT_SECONDS": "15",
        }
        self.stack.enter_context(patch.dict(os.environ, self.env))
        for name, value in (("GENERATION_CAPACITY", self.capacity),
                            ("CONNECTION_CAPACITY", self.connections),
                            ("ACTIVE_GENERATIONS", 0), ("READY", True),
                            ("RATE", {}), ("METRICS", {"errors_total": 0,
                             "client_disconnects_total": 0})):
            self.stack.enter_context(patch.object(main, name, value))
        self.runner = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.01))
        self.runner.start()
        self.sockets = []
        self.addCleanup(self._stop_server)

    def _stop_server(self):
        for conn in self.sockets:
            conn.close()
        self.server.shutdown()
        self.server.server_close()
        self.runner.join(2)
        self.assertFalse(self.runner.is_alive())

    def _headers(self, headers, path="/api/bundle"):
        conn = socket.create_connection(("127.0.0.1", self.server.server_port), 3)
        conn.settimeout(3)
        self.sockets.append(conn)
        head = (f"POST {path} HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{self.server.server_port}\r\n"
                "Connection: close\r\n" + headers + "\r\n")
        conn.sendall(head.encode())
        return conn

    def _response(self, conn):
        with http.client.HTTPResponse(conn) as response:
            response.begin()
            return response.status, response.read(), dict(response.getheaders())

    def _healthy(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, 3)
        try:
            conn.request("POST", "/api/bundle", json.dumps(
                {"scanner_input": {"violations": []}, "audit_date": "2026-10-06"}),
                {"Content-Type": "application/json"})
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def _finished(self, count):
        with self.observed:
            self.assertTrue(self.observed.wait_for(lambda: self.completed >= count, 3))
        self.assertEqual(main.ACTIVE_GENERATIONS, 0)
        self.assertEqual(self.capacity.accepted, self.capacity.released)
        self.assertEqual(self.connections.accepted, self.connections.released)
        self.assertFalse(self.errors)
        self.assertEqual(main.METRICS["errors_total"], 0)

    def test_two_quiet_oversize_drains_leave_healthy_bundle_capacity(self):
        sockets = [self._headers(
            "Content-Type: application/json\r\n"
            f"Content-Length: {MAX_HTTP_BODY_BYTES + 1}\r\n") for _ in range(2)]
        # No body is sent. Both handlers have entered their bounded drains.
        with self.observed:
            self.assertTrue(self.observed.wait_for(lambda: len(self.draining) == 2, 3))
        with main.ACTIVE_CONDITION:
            active_during_drains = main.ACTIVE_GENERATIONS
        calls_during_drains = self.capacity.calls
        healthy_status, healthy_body = self._healthy()
        # Explicit temporal barrier: the healthy response was received while
        # BOTH real no-body drains were still pending, not after their release.
        with self.observed:
            drains_finished_before_healthy_release = len(self.drain_finished)
        # End uploads only after the concurrent healthy request completes.
        for conn in sockets:
            conn.shutdown(socket.SHUT_WR)
        rejected = [self._response(conn) for conn in sockets]
        self._finished(3)
        statuses = [status for status, _, _ in rejected]
        print("admission receipt:", json.dumps({
            "active_during_drains": active_during_drains,
            "admission_calls_during_drains": calls_during_drains,
            "healthy_while_draining": healthy_status,
            "drains_finished_before_offender_release": drains_finished_before_healthy_release,
            "offender_statuses": statuses,
            "accepted": self.capacity.accepted, "released": self.capacity.released,
            "unhandled_errors": len(self.errors)}))
        self.assertEqual(statuses, [413, 413])
        for _, body, headers in rejected:
            self.assertEqual(json.loads(body)["error"]["code"], "INPUT_TOO_LARGE")
            self.assertEqual(headers["Connection"], "close")
            self.assertIn("X-Request-ID", headers)
        self.assertEqual(drains_finished_before_healthy_release, 0)
        self.assertEqual(healthy_status, 200)
        self.assertTrue(validate_bundle(healthy_body)["valid"])
        self.assertEqual(active_during_drains, 0)
        self.assertEqual(calls_during_drains, 0)
        self.assertTrue(self.capacity.pool.acquire(blocking=False))
        self.assertTrue(self.capacity.pool.acquire(blocking=False))
        self.assertFalse(self.capacity.pool.acquire(blocking=False))
        self.capacity.pool.release()
        self.capacity.pool.release()

    def test_invalid_headers_reject_before_saturated_generation_pool(self):
        self.capacity.pool.acquire()
        self.capacity.pool.acquire()
        cases = [
            "Content-Type: text/plain\r\nContent-Length: 2\r\n",
            "Content-Type: application/json\r\nTransfer-Encoding: chunked\r\nContent-Length: 2\r\n",
            "Content-Type: application/json\r\nContent-Encoding: gzip\r\nContent-Length: 2\r\n",
            "Content-Type: application/json\r\n",
            "Content-Type: application/json\r\nContent-Length: 2\r\nContent-Length: 5\r\n",
            "Content-Type: application/json\r\nContent-Length: invalid\r\n",
            "Content-Type: application/json\r\nContent-Length: 0\r\n",
            "Content-Type: application/json\r\nContent-Length: -1\r\n",
        ]
        try:
            for headers in cases:
                with self.subTest(headers=headers):
                    status, body, response_headers = self._response(self._headers(headers))
                    self.assertEqual(status, 422)
                    self.assertEqual(json.loads(body)["error"]["code"], "INVALID_INPUT")
                    self.assertEqual(response_headers["Connection"], "close")
        finally:
            self.capacity.pool.release()
            self.capacity.pool.release()
        self._finished(len(cases))
        self.assertEqual(self.capacity.calls, 0)
        self.assertFalse(self.draining)

    def test_policy_denials_precede_header_validation(self):
        cases = [
            ({"ALLOWED_HOSTS": "invalid.test"}, {}, "", 421, "INVALID_HOST"),
            ({"ACCESSDOC_REQUIRE_AUTH": "true"}, {}, "", 503, "AUTH_NOT_CONFIGURED"),
            ({}, {}, "Origin: http://not-allowed.test\r\n", 403, "CROSS_SITE_REQUEST"),
            ({"ACCESSDOC_GENERATION_ENABLED": "false"}, {}, "", 503, "GENERATION_DISABLED"),
            ({}, {"READY": False}, "", 503, "DRAINING"),
            ({"RATE_LIMIT_PER_MINUTE": "0"}, {}, "", 429, "RATE_LIMITED"),
        ]
        for env, objects, extra, expected, code in cases:
            with self.subTest(policy=code), ExitStack() as stack:
                stack.enter_context(patch.dict(os.environ, env))
                for name, value in objects.items():
                    stack.enter_context(patch.object(main, name, value))
                status, body, _ = self._response(self._headers(
                    extra + "Content-Type: text/plain\r\n"
                    f"Content-Length: {MAX_HTTP_BODY_BYTES + 1}\r\n"))
                self.assertEqual(status, expected)
                self.assertEqual(json.loads(body)["error"]["code"], code)
        self._finished(len(cases))
        self.assertEqual(self.capacity.calls, 0)
        self.assertFalse(self.draining)

    def test_shared_reader_retains_bounded_oversize_drain(self):
        handler = main.Handler.__new__(main.Handler)
        handler.headers = Message()
        handler.headers["Content-Type"] = "application/json"
        handler.headers["Content-Length"] = str(main.DRAIN_MAX_BYTES + 1)
        handler.rfile = object()
        handler.close_connection = False
        with patch.object(main, "body_deadline", return_value=12345.0), patch.object(
                main, "read_body", return_value=(b"", 0)) as reader:
            with self.assertRaises(LimitExceeded):
                handler._read(MAX_HTTP_BODY_BYTES, require_json=True)
            reader.assert_called_once_with(
                handler.rfile, None, main.DRAIN_MAX_BYTES,
                main.READ_CHUNK_BYTES, 12345.0, collect=False)
        self.assertTrue(handler.close_connection)
        self.assertEqual(main.DRAIN_MAX_BYTES, 16 * 1024 * 1024)
        self.assertEqual(main.READ_CHUNK_BYTES, 64 * 1024)
        self.assertEqual(self.capacity.calls, 0)

    def test_valid_upload_still_waits_inside_generation_capacity(self):
        # Header-valid uploads may NOT be buffered before admission.
        read_entries = set()
        observed = self.observed
        original = main.Handler._read_json

        def read_json(handler):
            with observed:
                read_entries.add(handler.client_address)
                observed.notify_all()
            return original(handler)

        with patch.object(main.Handler, "_read_json", read_json):
            sockets = [self._headers("Content-Type: application/json\r\n"
                                     "Content-Length: 2\r\n") for _ in range(2)]
            with observed:
                self.assertTrue(observed.wait_for(lambda: len(read_entries) == 2, 3))
            self.assertEqual(main.ACTIVE_GENERATIONS, 2)
            self.assertEqual(self._healthy()[0], 503)
            for conn in sockets:
                conn.sendall(b"{}")
            self.assertEqual([self._response(conn)[0] for conn in sockets], [422, 422])
            self._finished(3)
            status, bundle = self._healthy()
            self.assertEqual(status, 200)
            self.assertTrue(validate_bundle(bundle)["valid"])
            self._finished(4)


if __name__ == "__main__":
    unittest.main()
