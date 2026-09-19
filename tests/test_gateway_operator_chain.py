"""Regression tests: operator-pinnable chain (GATEWAY_MODELS) and immediate
ejection of provider-unknown (HTTP 404) models. Session 10 hardening."""
import os
import unittest
from unittest import mock

from app import gateway


class ConfiguredChainTests(unittest.TestCase):
    def test_empty_env_falls_back_to_canonical(self):
        self.assertEqual(gateway.configured_chain(""), gateway.CANONICAL_CHAIN)
        self.assertEqual(gateway.configured_chain("  , ;  "), gateway.CANONICAL_CHAIN)

    def test_env_pins_chain_normalised_and_deduped(self):
        chain = gateway.configured_chain(" Hermes-4-405B , gemma-3-27b-it;hermes_4_405b ,")
        self.assertEqual(chain, ("hermes-4-405b", "gemma-3-27b-it"))

    def test_env_aliases_resolve_to_canonical_ids(self):
        chain = gateway.configured_chain("glm5.3")
        self.assertEqual(chain, (gateway.CANONICAL_CHAIN[0],))

    def test_gateway_reads_env_when_no_explicit_chain(self):
        with mock.patch.dict(os.environ, {gateway.CHAIN_ENV: "hermes-4-405b,gemma-3-27b-it"}):
            gw = gateway.ModelGateway(api_key="k")
        self.assertEqual(gw.chain, ("hermes-4-405b", "gemma-3-27b-it"))
        self.assertEqual(set(gw.breakers), set(gw.chain))

    def test_explicit_chain_wins_over_env(self):
        with mock.patch.dict(os.environ, {gateway.CHAIN_ENV: "hermes-4-405b"}):
            gw = gateway.ModelGateway(api_key="k", chain=["gemma-3-27b-it"])
        self.assertEqual(gw.chain, ("gemma-3-27b-it",))

    def test_unset_env_uses_canonical_chain(self):
        env = {k: v for k, v in os.environ.items() if k != gateway.CHAIN_ENV}
        with mock.patch.dict(os.environ, env, clear=True):
            gw = gateway.ModelGateway(api_key="k")
        self.assertEqual(gw.chain, gateway.CANONICAL_CHAIN)


class ModelNotFoundEjectionTests(unittest.TestCase):
    def _gw(self, calls):
        def transport(model, messages):
            calls.append(model)
            if model == "ghost":
                return 404, {}, {"error": {"code": "model_not_found"}}
            return 200, {}, {"choices": [{"message": {"content": "ok from " + model}}],
                             "usage": {"total_tokens": 5}}
        return gateway.ModelGateway(api_key="k", chain=["ghost", "live"], transport=transport)

    def test_404_trips_breaker_after_a_single_attempt(self):
        calls = []
        gw = self._gw(calls)
        res = gw.chat("WCAG 2.4.7?")
        self.assertEqual(res.model, "live")
        self.assertFalse(res.fallback)
        self.assertEqual(calls, ["ghost", "live"])
        snap = gw.breakers["ghost"].snapshot()
        self.assertEqual(snap["state"], gateway.CircuitBreaker.OPEN)
        self.assertEqual(snap["failures"], 1, "must not fabricate failures")

    def test_subsequent_requests_skip_ghost_model_entirely(self):
        calls = []
        gw = self._gw(calls)
        gw.chat("a")
        gw.chat("b")
        gw.chat("c")
        self.assertEqual(calls.count("ghost"), 1)
        self.assertEqual(calls.count("live"), 3)
        # health-ranked ordering demotes the ejected model behind the live one
        self.assertEqual(gw.route_order()[0], "live")

    def test_all_models_404_lands_on_static_kb_not_exception(self):
        def transport(model, messages):
            return 404, {}, {"error": "model_not_found"}
        gw = gateway.ModelGateway(api_key="k", chain=["g1", "g2"], transport=transport)
        res = gw.chat("WCAG 1.4.3 contrast")
        self.assertTrue(res.fallback)
        self.assertEqual(res.model, "static-kb")
        self.assertIn("4.5:1", res.text)


if __name__ == "__main__":
    unittest.main()
