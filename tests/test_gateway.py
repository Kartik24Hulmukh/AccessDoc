"""Model gateway router hardened-routing coverage (app/gateway.py).

Deterministic: all HTTP is replaced by an injectable transport so the
breaker lifecycle, 429 fallback and outage fail-fast are testable without
network. Credentials are asserted to come only from $MELIOUS_API_KEY and
no secret literal may exist anywhere in the tracked source tree.
"""
import os
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.gateway import (CANONICAL_CHAIN, CircuitBreaker, GatewayError,
                         ModelGateway, normalize_model, static_answer)

PROMPT = "Remediate WCAG 1.1.1 Non-text Content for an image carousel."


def ok_transport(model, messages):
    return 200, {}, {"choices": [{"message": {"content": "alt text: " + model}}],
                     "usage": {"total_tokens": 33}}


class BreakerLifecycleTests(unittest.TestCase):
    def test_opens_after_threshold_half_open_then_closes(self):
        b = CircuitBreaker(failure_threshold=3, recovery_timeout=0.2,
                           half_open_max_trials=1)
        self.assertTrue(b.allow())
        for _ in range(3):
            b.record_failure()
        self.assertEqual(b.state, CircuitBreaker.OPEN)
        self.assertFalse(b.allow())
        time.sleep(0.25)
        self.assertTrue(b.allow())
        self.assertEqual(b.state, CircuitBreaker.HALF_OPEN)
        b.record_failure()
        self.assertEqual(b.state, CircuitBreaker.OPEN)
        time.sleep(0.25)
        self.assertTrue(b.allow())
        b.record_success()
        self.assertEqual(b.state, CircuitBreaker.CLOSED)
        self.assertEqual(b.consecutive_failures, 0)


class RoutingTests(unittest.TestCase):
    def test_429_storm_falls_back_to_next_model(self):
        seen = []

        def storm(model, messages):
            seen.append(model)
            if model == "glm-5.3":
                return 429, {"Retry-After": "0"}, {"error": "rate limited"}
            return ok_transport(model, messages)

        gw = ModelGateway(transport=storm, base_backoff=0.01, max_sleep=0.02)
        res = gw.chat(PROMPT)
        self.assertFalse(res.fallback)
        self.assertEqual(res.model, "glm-5.3-flash")
        self.assertIn("glm-5.3", seen)

    def test_total_outage_fail_fast_and_static_kb(self):
        def outage(model, messages):
            raise GatewayError("gateway down", status=503, model=model)

        gw = ModelGateway(transport=outage, base_backoff=0.01, max_sleep=0.02)
        with self.assertRaises(GatewayError):
            gw.chat(PROMPT, static_fallback=False)
        res = gw.chat(PROMPT, static_fallback=True)
        self.assertTrue(res.fallback)
        self.assertEqual(res.model, "static-kb")
        self.assertIn("WCAG", res.text)

    def test_non_transient_error_does_not_retry(self):
        calls = {"n": 0}

        def bad(model, messages):
            calls["n"] += 1
            return 400, {}, {"error": "bad request"}

        gw = ModelGateway(transport=bad, base_backoff=0.01, max_sleep=0.02)
        res = gw.chat(PROMPT)
        self.assertEqual(calls["n"], len(CANONICAL_CHAIN))
        self.assertTrue(res.fallback)

    def test_circuit_open_skips_model(self):
        gw = ModelGateway(transport=ok_transport, base_backoff=0.01)
        for _ in range(3):
            gw.breakers["glm-5.3"].record_failure()
        self.assertEqual(gw.breakers["glm-5.3"].state, CircuitBreaker.OPEN)
        res = gw.chat(PROMPT)
        self.assertEqual(res.model, "glm-5.3-flash")

    def test_alias_normalization(self):
        self.assertEqual(normalize_model("qwen-3.8-27b"), "qwen3.8-27b")
        self.assertEqual(normalize_model("GLM-5.3"), "glm-5.3")
        self.assertEqual(normalize_model("kimi"), "kimi-k3")

    def test_static_kb_answers_known_criteria(self):
        self.assertIn("text alternative",
                      static_answer("How do I fix WCAG 1.1.1?"))


class CredentialHygieneTests(unittest.TestCase):
    def test_credentials_from_env_only(self):
        gw = ModelGateway()
        os.environ.pop("MELIOUS_API_KEY", None)
        with self.assertRaises(GatewayError):
            gw._post("glm-5.3", [])
        os.environ["MELIOUS_API_KEY"] = "env-token"
        try:
            self.assertEqual(gw._key(), "env-token")
        finally:
            del os.environ["MELIOUS_API_KEY"]

    def test_no_secret_literals_in_tracked_source(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        out = subprocess.run(
            ["grep", "-rn", "-E", "sk-" + "mel-|" + "ghp" + "_", root + "/app", root + "/api",
             root + "/scripts"],
            capture_output=True, text=True)
        self.assertEqual(out.returncode, 1, out.stdout)


if __name__ == "__main__":
    unittest.main()
