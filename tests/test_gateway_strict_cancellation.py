"""Strict wall-clock cancellation of slow-drip provider bodies (launch gate)."""
import socket
import threading
import time
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.gateway import ModelGateway, CANONICAL_CHAIN


class SlowDripHandler(BaseHTTPRequestHandler):
    """200 OK, then one byte every 50 ms for ~10 s (never a complete JSON body)."""
    def log_message(self, *args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", "200")
        self.end_headers()
        try:
            for _ in range(200):
                self.wfile.write(b"{")
                self.wfile.flush()
                time.sleep(0.05)
        except (BrokenPipeError, ConnectionResetError, socket.error):
            pass


class StrictCancellationTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), SlowDripHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_slow_drip_body_is_cancelled_at_wall_clock_budget(self):
        budget = 0.3
        gw = ModelGateway(api_key="test-only", chain=(CANONICAL_CHAIN[0],),
                          max_retries=0, budget_seconds=budget)
        try:
            with patch("app.gateway.MELIOUS_BASE_URL", "http://127.0.0.1:%d" % self.server.server_port), \
                 patch.object(gw, "_log"):
                t0 = time.monotonic()
                result = gw.chat("fix contrast")
                elapsed = time.monotonic() - t0
            self.assertTrue(result.fallback, "slow-drip must degrade to static KB")
            # Strict gate: total wall clock within budget + 150 ms slack
            # (previously 1104 ms observed for a 200 ms budget).
            self.assertLess(elapsed, budget + 0.15, "slow-drip outlived the admission budget: %.3fs" % elapsed)
            self.assertGreaterEqual(elapsed, budget * 0.5)
        finally:
            gw._session.close()

    def test_deadline_error_is_classified_as_504_and_opens_breaker_path(self):
        gw = ModelGateway(api_key="test-only", chain=(CANONICAL_CHAIN[0],),
                          max_retries=0, budget_seconds=0.2)
        try:
            with patch("app.gateway.MELIOUS_BASE_URL", "http://127.0.0.1:%d" % self.server.server_port), \
                 patch.object(gw, "_log") as log:
                gw.chat("fix contrast")
            statuses = [c.kwargs.get("status") for c in log.call_args_list if c.kwargs.get("event") == "gateway_call"]
            self.assertTrue(statuses and all(s == 504 for s in statuses), statuses)
        finally:
            gw._session.close()


if __name__ == "__main__":
    unittest.main()
