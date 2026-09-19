"""Long outages must not crash routing or health snapshots."""
import unittest
from concurrent.futures import ThreadPoolExecutor
from app.gateway import CircuitBreaker, ModelGateway


class SaturatingBackoffTests(unittest.TestCase):
    def test_long_outage_saturates_without_float_overflow(self):
        breaker = CircuitBreaker()
        for cycles in (1, 2, 4, 5, 1025, 1000000):
            with self.subTest(cycles=cycles):
                breaker.open_cycles = cycles
                expected = {1: 30.0, 2: 60.0, 4: 240.0}.get(cycles, 300.0)
                self.assertEqual(breaker.recovery_delay(), expected)
                self.assertEqual(breaker.snapshot()["recovery_delay"], expected)

    def test_concurrent_trips_preserve_health_and_admission(self):
        breaker = CircuitBreaker()
        def trip_many(_):
            for _ in range(10):
                breaker.trip()
        with ThreadPoolExecutor(max_workers=120) as pool:
            list(pool.map(trip_many, range(120)))
        self.assertEqual(breaker.snapshot()["failures"], 1200)
        self.assertEqual(breaker.snapshot()["recovery_delay"], 300.0)
        self.assertFalse(breaker.allow())
        breaker._opened_at -= 301
        self.assertTrue(breaker.allow())
        self.assertTrue(breaker.allow())
        self.assertFalse(breaker.allow())
        breaker.record_success()
        self.assertEqual(breaker.recovery_delay(), 30.0)
        self.assertEqual(breaker.open_cycles, 0)

    def test_gateway_health_survives_long_outage(self):
        gateway = ModelGateway(api_key="test-only")
        try:
            for breaker in gateway.breakers.values():
                breaker.open_cycles = 1000000
            health = gateway.health()
            self.assertTrue(all(v["recovery_delay"] == 300.0 for v in health["models"].values()))
        finally:
            gateway._session.close()

    def test_custom_fractional_backoff_preserved(self):
        breaker = CircuitBreaker(recovery_timeout=0.125, max_recovery_timeout=0.75)
        for cycles, expected in ((1, 0.125), (2, 0.25), (3, 0.5), (4, 0.75), (1025, 0.75)):
            breaker.open_cycles = cycles
            self.assertEqual(breaker.recovery_delay(), expected)

    def test_zero_delay_remains_zero_after_long_outage(self):
        breaker = CircuitBreaker(recovery_timeout=0)
        breaker.open_cycles = 1000000
        self.assertEqual(breaker.recovery_delay(), 0)
