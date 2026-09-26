"""Per-model read windows must cover each frontier model's observed latency.

Live Melious benchmarks (2026-09-15) measured P50/P95 of ~11.0/12.0 s for the
second and third models in the canonical chain and ~24 s for the fourth. A
15 s default window turned the second model into a 504 on a routine call and
had already made the fourth model dead weight (fixed in PR #43). The turn-10
live benchmark then caught the PRIMARY at 0/3: it was the only chain model
still on the 15 s default, and 1024-token generations ran past it every time.
A 60 s-window probe measured the same model 5/5 (P50 ~1.1 s, max 9.8 s), so
the window -- not the provider -- was the failure. Every model in the chain
must therefore get a window of at least 25 s, and every window must still be
clamped to the remaining GATEWAY_BUDGET_SECONDS so total wall clock is unchanged.
"""
import os
import unittest

from app.gateway import CANONICAL_CHAIN, MODEL_READ_TIMEOUTS, ModelGateway


class ReadWindowTests(unittest.TestCase):
    def setUp(self):
        for k in list(os.environ):
            if k.startswith("GATEWAY_READ_TIMEOUT_"):
                os.environ.pop(k)

    def test_every_chain_model_has_wide_window(self):
        for model in CANONICAL_CHAIN:
            self.assertGreaterEqual(MODEL_READ_TIMEOUTS.get(model, 0), 25.0, model)

    def test_k3_window_has_headroom_over_measured_p95(self):
        # Turn-80 live p95 was 29.26 s; a 30 s window had < 1 s jitter margin.
        self.assertGreaterEqual(MODEL_READ_TIMEOUTS[CANONICAL_CHAIN[-1]], 35.0)

    def test_primary_is_not_left_on_narrow_default(self):
        # Regression: turn-10 live benchmark, primary 0/3 at the 15 s default.
        gw = ModelGateway()
        self.assertGreater(gw.read_timeout_for(CANONICAL_CHAIN[0]), gw.timeout[1])
        self.assertGreaterEqual(gw.read_timeout_for(CANONICAL_CHAIN[0]), 25.0)

    def test_primary_window_leaves_failover_budget(self):
        # A slow primary must fail over with wall clock left for the next model.
        gw = ModelGateway()
        self.assertLess(gw.read_timeout_for(CANONICAL_CHAIN[0]), gw.budget_seconds)

    def test_env_override_still_wins_for_primary(self):
        import re
        key = "GATEWAY_READ_TIMEOUT_" + re.sub(r"[^A-Za-z0-9]", "_", CANONICAL_CHAIN[0]).upper()
        os.environ[key] = "12"
        try:
            self.assertEqual(ModelGateway().read_timeout_for(CANONICAL_CHAIN[0]), 12.0)
        finally:
            os.environ.pop(key, None)

    def test_windows_are_clamped_to_remaining_budget(self):
        gw = ModelGateway()
        for model in CANONICAL_CHAIN:
            self.assertLessEqual(gw.read_timeout_for(model, remaining=7.5), 7.5, model)
            self.assertLessEqual(gw.read_timeout_for(model), gw.budget_seconds
                                 if hasattr(gw, "budget_seconds") else 40.0, model)


if __name__ == "__main__":
    unittest.main()
