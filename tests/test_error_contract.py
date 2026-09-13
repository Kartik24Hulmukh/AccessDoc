"""Stdlib-generated HTTP errors must honour the JSON/security-header contract on BOTH adapters.

Before this regression suite, BaseHTTPRequestHandler.send_error rendered an
HTML page for 400/414/431 parse failures: no CSP/nosniff/X-Frame-Options, no
X-Request-ID, the client's malformed request line reflected into the body, and
(self-hosted) the rejection logged as status 500, polluting the 5xx error budget.
"""
import http.client
import io
import json
import os
import socket
import threading
import unittest
from contextlib import redirect_stdout
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from api.handler import handler
from app.main import Handler


def _raw(port, payload, timeout=5):
    sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        sock.sendall(payload)
        chunks = []
        while True:
            try:
                chunk = sock.recv(65536)
            except (socket.timeout, OSError):
                break
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        sock.close()


class StdlibErrorContractTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"ACCESSDOC_API_KEY": "", "ACCESSDOC_API_KEYS": "",
                                           "ACCESSDOC_REQUIRE_AUTH": "false", "RATE_LIMIT_PER_MINUTE": "100000"})
        self.env.start()
        self.servers = []
        for adapter in (handler, Handler):
            server = ThreadingHTTPServer(("127.0.0.1", 0), adapter)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.servers.append((server, thread))
        os.environ["ALLOWED_HOSTS"] = ",".join(f"127.0.0.1:{s.server_port}" for s, _ in self.servers)

    def tearDown(self):
        for server, thread in self.servers:
            server.shutdown()
            server.server_close()
            thread.join()
        self.env.stop()

    def _assert_json_error(self, response, expected_status):
        head, _, body = response.partition(b"\r\n\r\n")
        status_line = head.split(b"\r\n", 1)[0]
        self.assertIn(str(expected_status).encode(), status_line, response[:200])
        lower = head.lower()
        self.assertIn(b"content-type: application/json", lower, head)
        self.assertIn(b"x-content-type-options: nosniff", lower, head)
        self.assertIn(b"x-frame-options: deny", lower, head)
        self.assertIn(b"x-request-id:", lower, head)
        self.assertNotIn(b"python", lower, "stdlib version banner leaked")
        self.assertNotIn(b"basehttp", lower, "stdlib server banner leaked")
        self.assertNotIn(b"<html", response.lower())
        payload = json.loads(body)
        self.assertIn("error", payload)
        return payload

    def test_over_long_request_line_is_json_414_on_both_adapters(self):
        for server, _ in self.servers:
            response = _raw(server.server_port, b"GET /" + b"a" * 70000 + b" HTTP/1.1\r\nHost: x\r\n\r\n")
            self._assert_json_error(response, 414)

    def test_over_long_header_is_json_431_and_logged_as_431(self):
        for server, _ in self.servers:
            captured = io.StringIO()
            with redirect_stdout(captured):
                response = _raw(server.server_port, b"GET / HTTP/1.1\r\nHost: x\r\nX-Long: " + b"b" * 70000 + b"\r\n\r\n")
            self._assert_json_error(response, 431)
            for line in captured.getvalue().splitlines():
                if line.startswith("{"):
                    entry = json.loads(line)
                    self.assertNotEqual(entry.get("status"), 500, "parse rejection must not count as a 5xx")

    def test_garbage_request_line_never_reflects_client_text(self):
        for server, _ in self.servers:
            response = _raw(server.server_port, b"GARBAGE_MARKER_7731 <script>\r\n\r\n")
            self.assertNotIn(b"GARBAGE_MARKER_7731", response)
            self.assertNotIn(b"<script>", response)
            self.assertNotIn(b"<html", response.lower())
            body = response.split(b"\r\n\r\n")[-1]
            self.assertIn("error", json.loads(body))

    def test_serverless_limits_endpoint_matches_self_hosted_contract(self):
        server = self.servers[0][0]
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        try:
            conn.request("GET", "/limits")
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader("Content-Type"), "application/json; charset=utf-8")
            payload = json.loads(response.read())
        finally:
            conn.close()
        for key in ("max_http_body_bytes", "max_violations", "max_total_nodes", "max_string_chars",
                    "max_manual_findings", "api_key_required", "max_concurrent_requests_per_process"):
            self.assertIn(key, payload)
        self.assertFalse(payload["api_key_required"])
        self.assertFalse(payload["oversize_opt_out_available_on_http"])
        with patch.dict(os.environ, {"ACCESSDOC_API_KEY": "pilot-secret"}):
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
            try:
                conn.request("GET", "/limits")
                self.assertTrue(json.loads(conn.getresponse().read())["api_key_required"])
            finally:
                conn.close()
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        try:
            conn.request("HEAD", "/limits")
            self.assertEqual(conn.getresponse().status, 200)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
