"""Turn 81 guard: the K3 read window must clear its measured live p95
(29.26 s, turn 80) with headroom, yet stay clamped to the remaining budget."""
import unittest

from app import gateway

K3 = gateway.CANONICAL_CHAIN[-1]
MEASURED_K3_P95_SECONDS = 29.26


class K3WindowTests(unittest.TestCase):
    def setUp(self):
        self.gw = gateway.ModelGateway(api_key="test", read_timeout=15.0, budget_seconds=40.0)

    def tearDown(self):
        self.gw._session.close()

    def test_k3_is_last_in_chain(self):
        self.assertTrue(K3.endswith("k3"))

    def test_k3_window_clears_measured_p95_with_headroom(self):
        self.assertGreaterEqual(self.gw.read_timeout_for(K3), MEASURED_K3_P95_SECONDS * 1.25)

    def test_k3_window_never_exceeds_default_budget(self):
        self.assertLessEqual(gateway.MODEL_READ_TIMEOUTS[K3], self.gw.budget_seconds)

    def test_k3_window_clamped_to_remaining_budget(self):
        self.assertEqual(self.gw.read_timeout_for(K3, remaining=7.5), 7.5)


if __name__ == "__main__":
    unittest.main()
