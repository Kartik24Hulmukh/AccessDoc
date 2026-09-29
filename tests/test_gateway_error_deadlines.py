"""Real-socket regression: error peeks must not bypass the body deadline."""
import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import requests

from app.gateway import BILLING_MARKER, CANONICAL_CHAIN, GatewayError, ModelGateway


class ErrorDeadlineTests(unittest.TestCase):
    def upstream(self, status, body, drip=False):
        stop = threading.Event()
        hits = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                hits.append(time.monotonic())
                # The second request proves that a failed stream did not poison
                # the gateway's reusable connection pool.
                data = body if len(hits) == 1 else b'{"recovered":true}'
                self.send_response(status if len(hits) == 1 else 200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                try:
                    if drip and len(hits) == 1:
                        for byte in data:
                            self.wfile.write(bytes([byte]))
                            self.wfile.flush()
                            if stop.wait(0.02):
                                break
                    else:
                        self.wfile.write(data)
                except OSError:
                    pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        thread = threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
        thread.start()

        def close():
            stop.set()
            server.shutdown()
            server.server_close()
            thread.join(2)
        self.addCleanup(close)
        p = patch("app.gateway.MELIOUS_BASE_URL",
                  "http://127.0.0.1:%d" % server.server_port)
        p.start()
        self.addCleanup(p.stop)
        gw = ModelGateway(api_key="local-test-only", chain=(CANONICAL_CHAIN[0],))
        self.addCleanup(gw._session.close)
        return gw

    def test_slow_drip_429_obeys_deadline_and_pool_recovers(self):
        body = json.dumps({"error": {"code": "insufficient_quota"}}).encode()
        gw = self.upstream(429, body, drip=True)
        started = time.monotonic()
        with self.assertRaises((GatewayError, requests.Timeout)):
            gw._post(CANONICAL_CHAIN[0], [], remaining=0.1)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 0.25, "429 peek exceeded budget + 150 ms")
        self.assertEqual(gw._post(CANONICAL_CHAIN[0], [], remaining=1)[2],
                         {"recovered": True})

    def test_402_does_not_wait_for_optional_slow_body(self):
        gw = self.upstream(402, b"x" * 100, drip=True)
        started = time.monotonic()
        status, headers, _ = gw._post(CANONICAL_CHAIN[0], [], remaining=0.1)
        self.assertEqual(status, 402)
        self.assertEqual(headers[BILLING_MARKER], "1")
        self.assertLess(time.monotonic() - started, 0.2)

    def test_fast_billing_429_still_classifies(self):
        body = json.dumps({"error": {"code": "insufficient_quota"}}).encode()
        gw = self.upstream(429, body)
        self.assertEqual(gw._post(CANONICAL_CHAIN[0], [], remaining=1)[1]
                         [BILLING_MARKER], "1")

    def test_plain_rate_limit_still_classifies(self):
        gw = self.upstream(429, b'{"error":{"code":"rate_limited"}}')
        self.assertNotIn(BILLING_MARKER,
                         gw._post(CANONICAL_CHAIN[0], [], remaining=1)[1])

    def test_oversized_error_prefix_does_not_raise_size_error(self):
        gw = self.upstream(429, b"x" * 8192)
        status, headers, payload = gw._post(CANONICAL_CHAIN[0], [], remaining=1)
        self.assertEqual(status, 429)
        self.assertNotIn(BILLING_MARKER, headers)
        self.assertEqual(payload, {})