"""Account-wide credit exhaustion must not be treated as a per-model 429.

Reproduces the live Melious response observed 2026-09-29:
HTTP 429 {"error":{"type":"billing_error","code":"insufficient_quota"}}.
Before the fix every model was probed in turn (4 billable-path round trips,
~1.6 s) and re-probed after each 30 s breaker window.
"""
import json
import os
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from app import gateway as gw

BILLING = json.dumps({"error": {"message": "Insufficient credits for request.", "type": "billing_error",
                                "param": None, "code": "insufficient_quota"}}).encode()
RATE = json.dumps({"error": {"message": "slow down", "type": "rate_limit", "code": "rate_limited"}}).encode()


class _H(BaseHTTPRequestHandler):
    body = BILLING
    hits = []

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        _H.hits.append(json.loads(self.rfile.read(n))["model"])
        self.send_response(429)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(_H.body)))
        self.end_headers()
        self.wfile.write(_H.body)

    def log_message(self, *a):
        pass


class ClassifierTests(unittest.TestCase):
    def test_pure_classifier(self):
        f = gw.ModelGateway.is_billing_error
        self.assertTrue(f(402, {}))
        self.assertTrue(f(429, json.loads(BILLING)))
        self.assertFalse(f(429, json.loads(RATE)))
        self.assertFalse(f(429, {}))
        self.assertFalse(f(429, {"error": "x"}))
        self.assertFalse(f(500, json.loads(BILLING)))
        self.assertFalse(f(429, [1, 2]))


class LiveHttpBillingTests(unittest.TestCase):
    def setUp(self):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        _H.hits = []
        self.p = mock.patch.object(gw, "MELIOUS_BASE_URL", "http://127.0.0.1:%d/v1" % self.srv.server_address[1])
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.srv.shutdown()
        self.srv.server_close()
        _H.body = BILLING

    def _gw(self):
        gateway = gw.ModelGateway(api_key="sk-test", chain=gw.CANONICAL_CHAIN, budget_seconds=10)
        self.addCleanup(gateway._session.close)
        return gateway

    def test_billing_429_holds_whole_chain_after_bounded_speculation(self):
        g = self._gw()
        r = g.chat("fix alt text")
        self.assertTrue(r.fallback)
        self.assertEqual(r.model, "static-kb")
        # A cold/scheduled primary may not reveal billing failure before the
        # hedge timer. At most two authorized lanes can precede that knowledge.
        initial_hits = len(_H.hits)
        self.assertGreaterEqual(initial_hits, 1)
        self.assertLessEqual(initial_hits, 2)
        self.assertEqual(_H.hits[0], gw.CANONICAL_CHAIN[0])
        self.assertTrue(g.health()["billing_exhausted"])
        t0 = time.monotonic()
        for _ in range(50):
            self.assertEqual(g.chat("again").model, "static-kb")
        per_call_ms = (time.monotonic() - t0) * 1000 / 50
        self.assertEqual(len(_H.hits), initial_hits, "held chain must dispatch nothing")
        self.assertLess(per_call_ms, 200.0, "static-KB recovery must be < 200 ms")

    def test_hold_expires_after_cooldown(self):
        g = self._gw()
        g.billing_cooldown = 0.05
        g.chat("x")
        time.sleep(0.1)  # test-only: wait out the configured 50 ms cooldown
        self.assertFalse(g.billing_exhausted())

    def test_plain_rate_limit_is_not_billing(self):
        _H.body = RATE
        g = self._gw()
        g.chat("x")
        self.assertFalse(g.health()["billing_exhausted"])
        self.assertGreater(len(_H.hits), 1, "a per-model 429 must still fail over across the chain")

    def test_serial_path_also_holds(self):
        g = self._gw()
        with self.assertRaises(gw.GatewayError) as cm:
            g._chat_serial("x", static_fallback=False)
        self.assertEqual(cm.exception.status, 402)
        self.assertEqual(len(_H.hits), 1)


if __name__ == "__main__":
    unittest.main()
