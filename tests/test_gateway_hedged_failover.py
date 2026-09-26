"""Issue #86: stalled upstream must fail over in <200 ms with PRODUCTION read windows.

Real HTTP over loopback through the real requests.Session (no transport double).
No read-window overrides: MODEL_READ_TIMEOUTS / GATEWAY_BUDGET_SECONDS defaults.
"""
import json
import os
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from app import gateway

PRIMARY, FALLBACK = gateway.CANONICAL_CHAIN[0], gateway.CANONICAL_CHAIN[1]


class _Upstream:
    def __init__(self, behaviours):
        self.behaviours = behaviours  # model -> "stall" | "ok" | "slow_ok"
        self.arrivals = []
        self.release = threading.Event()
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                model = json.loads(self.rfile.read(n))["model"]
                outer.arrivals.append((model, time.monotonic()))
                mode = outer.behaviours.get(model, "ok")
                if mode == "stall":
                    outer.release.wait(10)  # bounded: released on teardown
                    return
                if mode == "slow_ok":
                    time.sleep(0.4)
                body = json.dumps({"choices": [{"message": {"content": "fix from " + model}}],
                                   "usage": {"total_tokens": 7}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:%d/v1" % self.server.server_address[1]

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


class HedgedFailoverTests(unittest.TestCase):
    def _run(self, behaviours, env=None, **gw_kwargs):
        up = _Upstream(behaviours)
        self.addCleanup(up.close)
        env = dict(env or {})
        with mock.patch.object(gateway, "MELIOUS_BASE_URL", up.url), \
                mock.patch.dict(os.environ, env):
            if "GATEWAY_HEDGE_DELAY_MS" not in env:
                os.environ.pop("GATEWAY_HEDGE_DELAY_MS", None)  # exercise the production default
            for k in [k for k in os.environ if k.startswith("GATEWAY_READ_TIMEOUT")]:
                os.environ.pop(k)
            gw = gateway.ModelGateway(api_key="sk-test", chain=(PRIMARY, FALLBACK), **gw_kwargs)
            t0 = time.monotonic()
            res = gw.chat("alt text", static_fallback=True)
            return res, time.monotonic() - t0, up, gw

    def test_stalled_primary_dispatches_fallback_under_200ms_with_production_windows(self):
        res, elapsed, up, gw = self._run({PRIMARY: "stall", FALLBACK: "ok"})
        self.assertEqual(gateway.MODEL_READ_TIMEOUTS[PRIMARY], 25.0)  # production window untouched
        self.assertEqual(res.model, FALLBACK)
        self.assertFalse(res.fallback)
        models = [m for m, _ in up.arrivals]
        self.assertEqual(models[:2], [PRIMARY, FALLBACK])
        interval_ms = (up.arrivals[1][1] - up.arrivals[0][1]) * 1000
        self.assertLess(interval_ms, 200.0, interval_ms)
        self.assertLess(elapsed, 1.0)

    def test_fast_primary_is_not_hedged(self):
        res, elapsed, up, gw = self._run({PRIMARY: "ok", FALLBACK: "ok"})
        self.assertEqual(res.model, PRIMARY)
        time.sleep(0.3)  # observation window: no hedge may arrive late
        self.assertEqual([m for m, _ in up.arrivals], [PRIMARY])

    def test_slow_primary_first_success_wins(self):
        res, elapsed, up, gw = self._run({PRIMARY: "slow_ok", FALLBACK: "stall"})
        self.assertEqual(res.model, PRIMARY)
        self.assertEqual([m for m, _ in up.arrivals], [PRIMARY, FALLBACK])

    def test_all_stalled_returns_static_kb_within_budget(self):
        res, elapsed, up, gw = self._run({PRIMARY: "stall", FALLBACK: "stall"}, budget_seconds=1.0)
        self.assertTrue(res.fallback)
        self.assertEqual(res.model, "static-kb")
        self.assertLess(elapsed, 1.5)

    def test_token_ceiling_bounds_hedge_spend(self):
        # Ceiling fits exactly one completion reservation: no hedge lane may launch.
        res, elapsed, up, gw = self._run({PRIMARY: "slow_ok", FALLBACK: "ok"},
                                         env={"GATEWAY_MAX_TOKENS": "100"}, token_budget=100)
        self.assertEqual(res.model, PRIMARY)
        self.assertEqual([m for m, _ in up.arrivals], [PRIMARY])

    def test_negative_delay_disables_hedging(self):
        with mock.patch.dict(os.environ, {"GATEWAY_HEDGE_DELAY_MS": "-1"}):
            self.assertIsNone(gateway.ModelGateway(api_key="k").hedge_delay())
        with mock.patch.dict(os.environ, {"GATEWAY_HEDGE_DELAY_MS": "nan"}):
            self.assertIsNone(gateway.ModelGateway(api_key="k").hedge_delay())
        with mock.patch.dict(os.environ, {"GATEWAY_HEDGE_DELAY_MS": "bogus"}):
            self.assertEqual(gateway.ModelGateway(api_key="k").hedge_delay(), 0.1)


if __name__ == "__main__":
    unittest.main()
