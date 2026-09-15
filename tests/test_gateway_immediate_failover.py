"""Deterministic routing overhead and atomic breaker regressions (no provider SLA)."""
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from app.gateway import CANONICAL_CHAIN, CircuitBreaker, ModelGateway


class ImmediateFailoverTests(unittest.TestCase):
    def test_rate_limit_and_server_errors_route_once_without_sleep(self):
        for status in (429, 500, 502, 503, 504):
            with self.subTest(status=status):
                calls = []
                def transport(model, messages):
                    calls.append(model)
                    if model == CANONICAL_CHAIN[0]:
                        return status, {"Retry-After": "60"}, {}
                    return 200, {}, {"choices": [{"message": {"content": "ok"}}]}
                gw = ModelGateway(transport=transport, max_retries=5, base_backoff=1)
                try:
                    with patch.object(gw, "_log"), patch("app.gateway.time.sleep") as sleep:
                        start = time.monotonic()
                        result = gw.chat("fix contrast")
                        elapsed = time.monotonic() - start
                    self.assertEqual(calls, list(CANONICAL_CHAIN[:2]))
                    self.assertEqual(result.model, CANONICAL_CHAIN[1])
                    sleep.assert_not_called()
                    self.assertLess(elapsed, 0.2, "local routing overhead, not network latency")
                    self.assertEqual(gw.breakers[CANONICAL_CHAIN[0]].snapshot()["failures"], 1)
                finally:
                    gw._session.close()

    def test_trip_records_exactly_one_failure_under_concurrency(self):
        breaker = CircuitBreaker(failure_threshold=1000000)
        with ThreadPoolExecutor(max_workers=100) as pool:
            list(pool.map(lambda _: breaker.trip(), range(200)))
        self.assertEqual(breaker.snapshot()["failures"], 200)
        self.assertEqual(breaker.snapshot()["consecutive_failures"], 200)
        self.assertEqual(breaker.snapshot()["state"], CircuitBreaker.OPEN)
        self.assertFalse(breaker.allow())
        breaker.recovery_timeout = 0
        self.assertTrue(breaker.allow())
        breaker.record_success()
        self.assertEqual(breaker.snapshot()["state"], CircuitBreaker.CLOSED)
