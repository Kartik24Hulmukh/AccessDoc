"""Real-socket slowloris regression; clients keep dripping until rejection."""
import http.client
import json
import os
import socket
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from app.limits import MAX_HTTP_BODY_BYTES


class HTTPBodyDeadlineTests(unittest.TestCase):
    def _exercise(self, module, handler, length=1000, dripping=True, force_abort=False):
        errors = []
        rejections = {}
        observed = threading.Condition()
        expected = 413 if length > MAX_HTTP_BODY_BYTES else 408
        def record(owner, status, payload):
            error = payload.get("error") if isinstance(payload, dict) else None
            valid = (status == expected and (
                (status == 408 and (error == "Request body deadline exceeded" or
                    isinstance(error, dict) and error.get("code") == "REQUEST_TIMEOUT")) or
                (status == 413 and (error == "Request body too large" or
                    isinstance(error, dict) and error.get("code") == "INPUT_TOO_LARGE"))))
            if valid:
                with observed:
                    rejections[owner.client_address] = status
                    observed.notify_all()
        class ObservedHandler(handler):
            def _send(self, status, body=b"", *args, **kwargs):
                try: payload = json.loads(body)
                except (ValueError, TypeError): payload = None
                record(self, status, payload)
                return super()._send(status, body, *args, **kwargs)
            def _send_json(self, status, payload, *args, **kwargs):
                record(self, status, payload)
                return super()._send_json(status, payload, *args, **kwargs)
        class ObservedServer(ThreadingHTTPServer):
            daemon_threads = True
            def handle_error(self, *args):
                errors.append("unhandled handler error")
        server = ObservedServer(("127.0.0.1", 0), ObservedHandler)
        runner = threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.01))
        runner.start()
        stop = threading.Event()
        sockets = []
        writers = []
        pool = threading.BoundedSemaphore(2)
        env = {"BODY_TIMEOUT_SECONDS": "0.2", "SOCKET_TIMEOUT_SECONDS": "0.15",
               "ACCESSDOC_REQUIRE_AUTH": "false", "ACCESSDOC_API_KEY": "",
               "ACCESSDOC_API_KEYS": "", "RATE_LIMIT_PER_MINUTE": "100000",
               "ALLOWED_HOSTS": "127.0.0.1:%d" % server.server_port}
        started = time.monotonic()
        try:
            with patch.dict(os.environ, env), patch.object(
                    module, "GENERATION_CAPACITY", pool):
                for _ in range(2):
                    conn = socket.create_connection(
                        ("127.0.0.1", server.server_port), timeout=0.7)
                    sockets.append(conn)
                    conn.sendall((
                        "POST /api/bundle HTTP/1.1\r\n"
                        "Host: 127.0.0.1:%d\r\n"
                        "Content-Type: application/json\r\n"
                        "Content-Length: %d\r\nConnection: close\r\n\r\n"
                        % (server.server_port, length)).encode())
                    def drip(sock=conn):
                        try:
                            while not stop.is_set():
                                sock.sendall(b" ")
                                if stop.wait(0.02):
                                    break
                        except OSError:
                            pass
                    if dripping:
                        writer = threading.Thread(target=drip)
                        writers.append(writer)
                        writer.start()
                for conn in sockets:
                    client = conn.getsockname()
                    if force_abort == "uncorrelated":
                        client = ("127.0.0.1", -1)  # impossible peer for negative control
                    try:
                        if force_abort == "uncorrelated":
                            raise ConnectionAbortedError("synthetic uncorrelated client abort")
                        if force_abort:
                            # Exercise the portable client-reset branch, but
                            # only after a real, correlated server deadline.
                            with observed:
                                self.assertTrue(observed.wait_for(lambda: client in rejections, 0.4))
                            raise ConnectionAbortedError("synthetic post-rejection client abort")
                        with http.client.HTTPResponse(conn) as response:
                            response.begin()
                            self.assertEqual(response.status, expected)
                            response.read()
                    except (ConnectionAbortedError, ConnectionResetError):
                        if not dripping:
                            raise  # Quiet clients must receive the HTTP result.
                        # A client still sending into a timed-out unread body
                        # can receive TCP abort/reset (WinError 10053 observed).
                        # Never infer rejection from a reset alone: require the
                        # exact server decision for THIS connection and retain
                        # the independent deadline + admission + error gates.
                        with observed:
                            self.assertTrue(observed.wait_for(lambda: client in rejections, 0.1),
                                            "reset without matching server rejection")
                        self.assertEqual(rejections[client], expected)
                self.assertFalse(stop.is_set(), "clients were not voluntarily stopped")
                self.assertLess(time.monotonic() - started, 0.5,
                                "body deadline exceeded 200 ms + scheduling allowance")
                # Admission is released by the handler, not by closing clients.
                probe = http.client.HTTPConnection("127.0.0.1", server.server_port,
                                                  timeout=1)
                try:
                    probe.request("POST", "/api/bundle", b"{}",
                                  {"Content-Type": "application/json"})
                    response = probe.getresponse()
                    self.assertIn(response.status, (400, 422))
                    response.read()
                finally:
                    probe.close()
        finally:
            stop.set()
            for conn in sockets:
                conn.close()
            for writer in writers:
                writer.join(1)
            server.shutdown()
            server.server_close()
            runner.join(1)
        self.assertFalse(errors, errors)
        self.assertTrue(all(not t.is_alive() for t in [runner, *writers]))

    def test_both_adapters_bound_slow_uploads_and_release_capacity(self):
        import api.handler as hosted
        import app.main as local
        for module, handler in ((hosted, hosted.handler), (local, local.Handler)):
            with self.subTest(adapter=module.__name__):
                self._exercise(module, handler)

    def test_quiet_timed_out_clients_receive_408_on_both_adapters(self):
        import api.handler as hosted
        import app.main as local
        for module, handler in ((hosted, hosted.handler), (local, local.Handler)):
            with self.subTest(adapter=module.__name__):
                self._exercise(module, handler, dripping=False)

    def test_correlated_client_abort_retains_real_deadline_and_recovery_gates(self):
        import api.handler as hosted
        import app.main as local
        for module, handler in ((hosted, hosted.handler), (local, local.Handler)):
            with self.subTest(adapter=module.__name__):
                self._exercise(module, handler, force_abort=True)

    def test_uncorrelated_reset_is_not_accepted_as_deadline_evidence(self):
        import app.main as local
        with self.assertRaisesRegex(AssertionError, "reset without matching server rejection"):
            self._exercise(local, local.Handler, force_abort="uncorrelated")

    def test_oversized_body_drain_shares_deadline(self):
        import api.handler as hosted
        import app.main as local
        for module, handler in ((hosted, hosted.handler), (local, local.Handler)):
            with self.subTest(adapter=module.__name__):
                self._exercise(module, handler, MAX_HTTP_BODY_BYTES + 1)


if __name__ == "__main__":
    unittest.main()