"""Regression: an idle keep-alive socket timeout must not be logged as a phantom HTTP 500
on the previous request's route (observed live on GET /static/app.css and /static/app.js:
`status 500, duration_ms 15015` while the client was sent nothing)."""
import io, json, os, socket, threading, unittest
from contextlib import redirect_stdout
from http.server import ThreadingHTTPServer
from unittest import mock

from app import main


class IdleKeepAliveTelemetryTests(unittest.TestCase):
    def test_idle_timeout_is_not_a_phantom_500(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), main.Handler)
        host, port = server.server_address
        with mock.patch.dict(os.environ, {"SOCKET_TIMEOUT_SECONDS": "0.3", "ALLOWED_HOSTS": f"{host}:{port}"}):
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
            thread.start()
            captured = io.StringIO()
            try:
                with redirect_stdout(captured):
                    with socket.create_connection((host, port), timeout=5) as sock:
                        sock.sendall(f"GET /static/app.css HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n".encode())
                        sock.settimeout(5)
                        head = b""
                        while b"\r\n\r\n" not in head:
                            chunk = sock.recv(65536)
                            self.assertTrue(chunk, "server closed before responding")
                            head += chunk
                        self.assertTrue(head.startswith(b"HTTP/1.1 200"), head[:80])
                        # Stay idle until the server-side socket timeout fires and it closes the connection.
                        tail = b""
                        try:
                            while True:
                                chunk = sock.recv(65536)
                                if not chunk:
                                    break
                                tail += chunk
                        except (socket.timeout, ConnectionError):
                            pass
                        self.assertNotIn(b"HTTP/1.1 500", tail, "client must not receive a 500 for idling")
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=5)
        events = [json.loads(line) for line in captured.getvalue().splitlines() if line.startswith("{")]
        requests = [e for e in events if e.get("event") == "http_request"]
        self.assertEqual([e["status"] for e in requests], [200], requests)
        self.assertFalse([e for e in events if e.get("status") == 500], events)


if __name__ == "__main__":
    unittest.main()
