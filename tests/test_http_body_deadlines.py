"""Real-socket slowloris regression; clients keep dripping until rejection."""
import http.client
import os
import socket
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from app.limits import MAX_HTTP_BODY_BYTES


class HTTPBodyDeadlineTests(unittest.TestCase):
    def _exercise(self, module, handler, length=1000):
        errors = []
        class ObservedServer(ThreadingHTTPServer):
            daemon_threads = True
            def handle_error(self, *args):
                errors.append("unhandled handler error")
        server = ObservedServer(("127.0.0.1", 0), handler)
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
                    writer = threading.Thread(target=drip)
                    writers.append(writer)
                    writer.start()
                for conn in sockets:
                    with http.client.HTTPResponse(conn) as response:
                        response.begin()
                        self.assertEqual(response.status,
                                         413 if length > MAX_HTTP_BODY_BYTES else 408)
                        response.read()
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

    def test_oversized_body_drain_shares_deadline(self):
        import api.handler as hosted
        import app.main as local
        for module, handler in ((hosted, hosted.handler), (local, local.Handler)):
            with self.subTest(adapter=module.__name__):
                self._exercise(module, handler, MAX_HTTP_BODY_BYTES + 1)


if __name__ == "__main__":
    unittest.main()