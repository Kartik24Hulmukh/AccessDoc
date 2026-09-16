"""Health-ranked routing + timeout-weighted breaker (app/gateway.py).

Motivated by the live 2026-09-16 Melious bench: GLM-5.3 Flash returned three
consecutive 25 s read timeouts before its breaker opened, i.e. one slow model
could spend 25 s of the shared 40 s budget ahead of a healthy 11 s model.
All transports are injected; no network, no secrets.
"""
import os
import sys
import unittest

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.gateway import CANONICAL_CHAIN, CircuitBreaker, ModelGateway

PROMPT = "Remediate WCAG 1.4.3 Contrast (Minimum)."


def ok(model):
    return 200, {}, {"choices": [{"message": {"content": "served by " + model}}],
                     "usage": {"total_tokens": 40}}


class TimeoutWeightedBreakerTests(unittest.TestCase):
    def test_two_timeouts_open_a_threshold_three_breaker(self):
        b = CircuitBreaker(failure_threshold=3)
        b.record_timeout()
        self.assertEqual(b.state, CircuitBreaker.CLOSED)
        b.record_timeout()
        self.assertEqual(b.state, CircuitBreaker.OPEN)
        snap = b.snapshot()
        # Two real observations, never a fabricated third.
        self.assertEqual(snap["failures"], 2)
        self.assertEqual(snap["timeouts"], 2)

    def test_success_clears_unhealthy(self):
        b = CircuitBreaker()
        self.assertFalse(b.unhealthy())
        b.record_timeout()
        self.assertTrue(b.unhealthy())
        b.record_success()
        self.assertFalse(b.unhealthy())


class HealthRankedRoutingTests(unittest.TestCase):
    def test_healthy_chain_is_canonical_and_deterministic(self):
        gw = ModelGateway(transport=lambda m, msgs: ok(m))
        self.assertEqual(gw.route_order(), tuple(CANONICAL_CHAIN))
        self.assertEqual(gw.route_order(2), tuple(CANONICAL_CHAIN[2:]))

    def test_timed_out_model_is_demoted_not_dropped(self):
        calls = []
        slow = CANONICAL_CHAIN[1]

        def transport(model, messages):
            calls.append(model)
            if model == slow and len(calls) <= 1:
                raise requests.Timeout("read timed out")
            return ok(model)

        gw = ModelGateway(chain=CANONICAL_CHAIN, transport=transport,
                          base_backoff=0.01, max_sleep=0.02)
        # Explicitly start at the slow model: it times out, failover serves.
        res = gw.chat(PROMPT, model=slow)
        self.assertEqual(calls, [slow, CANONICAL_CHAIN[2]])
        self.assertEqual(res.model, CANONICAL_CHAIN[2])
        self.assertEqual(gw.breakers[slow].snapshot()["timeouts"], 1)
        # Next request: canonical priority for healthy models, slow one last.
        order = gw.route_order()
        self.assertEqual(order[-1], slow)
        self.assertEqual(order[:-1], tuple(m for m in CANONICAL_CHAIN if m != slow))
        self.assertEqual(len(order), len(CANONICAL_CHAIN))

    def test_demoted_model_recovers_after_success(self):
        slow = CANONICAL_CHAIN[0]
        gw = ModelGateway(transport=lambda m, msgs: ok(m))
        gw.breakers[slow].record_timeout()
        self.assertEqual(gw.route_order()[0], CANONICAL_CHAIN[1])
        gw.breakers[slow].record_success()
        self.assertEqual(gw.route_order(), tuple(CANONICAL_CHAIN))

    def test_primary_timeout_does_not_starve_fast_fallbacks(self):
        """After one timeout the primary is demoted so a healthy model answers
        first on the next call - the budget is spent on the fast path."""
        calls = []
        primary = CANONICAL_CHAIN[0]

        def transport(model, messages):
            calls.append(model)
            if model == primary:
                raise requests.Timeout("read timed out")
            return ok(model)

        gw = ModelGateway(transport=transport, base_backoff=0.01, max_sleep=0.02)
        gw.chat(PROMPT)
        self.assertEqual(calls[0], primary)
        calls.clear()
        res = gw.chat(PROMPT)
        self.assertEqual(calls, [CANONICAL_CHAIN[1]])
        self.assertEqual(res.model, CANONICAL_CHAIN[1])


if __name__ == "__main__":
    unittest.main()
