"""Stale in-flight completions must not undo newer breaker transitions."""
import threading
import unittest
from unittest.mock import patch

from app.gateway import CANONICAL_CHAIN, CircuitBreaker, GatewayError, ModelGateway


class GatewayEpochTests(unittest.TestCase):
    def test_100_stale_successes_preserve_rate_limit_cooldown(self):
        from concurrent.futures import ThreadPoolExecutor
        breaker = CircuitBreaker()
        tickets = [breaker.admit() for _ in range(100)]
        breaker.trip(breaker.admit())
        with ThreadPoolExecutor(max_workers=20) as pool:
            list(pool.map(breaker.record_success, tickets))
        snap = breaker.snapshot()
        self.assertEqual(snap["successes"], 100)
        self.assertEqual(snap["state"], "open")
        self.assertEqual(snap["open_cycles"], 1)
        self.assertIsNone(breaker.admit())

    def test_old_success_cannot_impersonate_half_open_probe(self):
        clock = [0.0]
        breaker = CircuitBreaker(clock=lambda: clock[0])
        old = breaker.admit()
        breaker.trip(old)
        clock[0] = 31.0
        probe = breaker.admit()
        self.assertNotEqual(old, probe)
        breaker.record_success(old)
        self.assertEqual(breaker.snapshot()["state"], "half_open")
        self.assertEqual(breaker.snapshot()["open_cycles"], 1)
        breaker.record_success(probe)
        self.assertEqual(breaker.snapshot()["state"], "closed")
        self.assertEqual(breaker.snapshot()["successes"], 2)

    def test_failed_sibling_probe_cannot_reopen_recovered_circuit(self):
        clock = [0.0]
        breaker = CircuitBreaker(clock=lambda: clock[0])
        breaker.trip(breaker.admit())
        clock[0] = 31.0
        good, late = breaker.admit(), breaker.admit()
        breaker.record_success(good)
        breaker.record_timeout(late)
        snap = breaker.snapshot()
        self.assertEqual(snap["state"], "closed")
        self.assertEqual(snap["consecutive_failures"], 0)
        self.assertEqual(snap["failures"], 2)  # trip + one observed timeout
        self.assertEqual(snap["timeouts"], 1)

    def test_timeout_weight_is_atomic_and_counts_one_observed_failure(self):
        breaker = CircuitBreaker(failure_threshold=2, timeout_weight=3)
        breaker.record_timeout(breaker.admit())
        snap = breaker.snapshot()
        self.assertEqual(snap["state"], "open")
        self.assertEqual(snap["consecutive_failures"], 3)
        self.assertEqual(snap["failures"], 1)
        self.assertEqual(snap["open_cycles"], 1)

    def test_retry_rechecks_circuit_admission(self):
        calls = []
        def transport(model, messages):
            calls.append(model)
            return 408, {}, {}
        gw = ModelGateway(transport=transport, chain=(CANONICAL_CHAIN[0],),
                          base_backoff=0, max_sleep=0)
        self.addCleanup(gw._session.close)
        gw.breakers[CANONICAL_CHAIN[0]].failure_threshold = 1
        with patch.object(gw, "_log"):
            self.assertTrue(gw.chat("retry").fallback)
        self.assertEqual(len(calls), 1)

    def test_exception_releases_half_open_admission(self):
        clock = [0.0]
        def transport(model, messages):
            raise GatewayError("credential missing")
        gw = ModelGateway(transport=transport, chain=(CANONICAL_CHAIN[0],))
        self.addCleanup(gw._session.close)
        breaker = gw.breakers[CANONICAL_CHAIN[0]]
        breaker._clock = lambda: clock[0]
        breaker.trip(breaker.admit())
        clock[0] = 31.0
        with patch.object(gw, "_log"), self.assertRaises(GatewayError):
            gw.chat("probe")
        self.assertEqual(breaker._trials, 0)
        self.assertIsNotNone(breaker.admit())

    def test_stale_success_cannot_clear_newer_rate_limit_trip(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []
        clock = [0.0]

        def transport(model, messages):
            calls.append(model)
            if len(calls) == 1:
                entered.set()
                if not release.wait(2):
                    raise AssertionError("test did not release the older request")
            elif len(calls) == 2:
                return 429, {}, {}
            return 200, {}, {"choices": [{"message": {"content": "ok"}}]}

        gw = ModelGateway(transport=transport, chain=(CANONICAL_CHAIN[0],))
        self.addCleanup(gw._session.close)
        breaker = gw.breakers[CANONICAL_CHAIN[0]]
        breaker._clock = lambda: clock[0]
        results = []
        older = threading.Thread(target=lambda: results.append(gw.chat("older")))
        with patch.object(gw, "_log"):
            older.start()
            try:
                self.assertTrue(entered.wait(1))
                self.assertTrue(gw.chat("rate-limited").fallback)
                self.assertEqual(breaker.snapshot()["state"], "open")
            finally:
                release.set()
                older.join(2)
            self.assertFalse(older.is_alive())
            self.assertEqual(results[0].text, "ok")
            self.assertEqual(breaker.snapshot()["state"], "open")
            self.assertEqual(breaker.snapshot()["open_cycles"], 1)
            self.assertTrue(gw.chat("inside cooldown").fallback)
            self.assertEqual(len(calls), 2)
            clock[0] = 31.0
            self.assertEqual(gw.chat("fresh recovery probe").text, "ok")
            self.assertEqual(breaker.snapshot()["state"], "closed")
            self.assertEqual(len(calls), 3)


if __name__ == "__main__":
    unittest.main()