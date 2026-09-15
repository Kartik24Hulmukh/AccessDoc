"""Per-model read windows must cover each frontier model's observed latency.

Live Melious benchmarks (2026-09-15) measured P50/P95 of ~11.0/12.0 s for the
second and third models in the canonical chain and ~24 s for the fourth. A
15 s default window turned the second model into a 504 on a routine call and
had already made the fourth model dead weight (fixed in PR #43). Every model
that regularly exceeds ~8 s must get a window of at least 25 s, and every
window must still be clamped to the remaining GATEWAY_BUDGET_SECONDS.
"""
import os
import unittest

from app.gateway import CANONICAL_CHAIN, MODEL_READ_TIMEOUTS, ModelGateway


class ReadWindowTests(unittest.TestCase):
    def setUp(self):
        for k in list(os.environ):
            if k.startswith("GATEWAY_READ_TIMEOUT_"):
                os.environ.pop(k)

    def test_slow_models_have_wide_windows(self):
        for model in CANONICAL_CHAIN[1:]:
            self.assertGreaterEqual(MODEL_READ_TIMEOUTS.get(model, 0), 25.0, model)

    def test_primary_keeps_fast_default(self):
        gw = ModelGateway()
        self.assertEqual(gw.read_timeout_for(CANONICAL_CHAIN[0]), gw.timeout[1])

    def test_windows_are_clamped_to_remaining_budget(self):
        gw = ModelGateway()
        for model in CANONICAL_CHAIN:
            self.assertLessEqual(gw.read_timeout_for(model, remaining=7.5), 7.5, model)
            self.assertLessEqual(gw.read_timeout_for(model), gw.budget_seconds
                                 if hasattr(gw, "budget_seconds") else 40.0, model)


if __name__ == "__main__":
    unittest.main()
