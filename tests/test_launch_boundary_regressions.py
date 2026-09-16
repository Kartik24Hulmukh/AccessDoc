"""Launch boundary regressions: hostile trace headers and long gateway outages."""
import unittest
from app import telemetry
from app.gateway import CircuitBreaker

class LaunchBoundaryRegressions(unittest.TestCase):
    def test_version_zero_traceparent_rejects_suffix_and_uppercase(self):
        header = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
        for malformed in (header + "-extra", header + "x", header.upper(), header + "\n"):
            with self.subTest(header=malformed):
                self.assertIsNone(telemetry.parse_traceparent(malformed))
        self.assertIsNotNone(telemetry.parse_traceparent(header))

    def test_disconnect_does_not_fabricate_internal_error_status(self):
        from app.main import Handler
        from unittest.mock import Mock
        handler = object.__new__(Handler)
        handler._status = 500
        handler.send_response = Mock(side_effect=BrokenPipeError)
        with self.assertRaises(BrokenPipeError):
            handler._send(422, b"invalid input")
        self.assertEqual(handler._status, 422)

    def test_long_outage_backoff_stays_capped_without_overflow(self):
        breaker = CircuitBreaker(recovery_timeout=30, max_recovery_timeout=300)
        breaker.open_cycles = 100000
        self.assertEqual(breaker.recovery_delay(), 300)

    def test_backoff_schedule_and_success_reset(self):
        breaker = CircuitBreaker(recovery_timeout=30, max_recovery_timeout=300)
        for cycle, expected in enumerate((30, 30, 60, 120, 240, 300, 300)):
            breaker.open_cycles = cycle
            self.assertEqual(breaker.recovery_delay(), expected)
        breaker.record_success()
        self.assertEqual(breaker.recovery_delay(), 30)

if __name__ == "__main__":
    unittest.main()
