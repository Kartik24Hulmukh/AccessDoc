"""Regression coverage for retry budget and untrusted provider boundaries."""
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from app.gateway import ModelGateway, CANONICAL_CHAIN, extract_text


class BudgetBoundaryTests(unittest.TestCase):
    def run_quiet(self, gateway):
        with redirect_stdout(io.StringIO()):
            return gateway.chat("fix contrast")

    def test_retry_checks_token_budget_before_another_call(self):
        calls = []
        def transport(model, messages):
            calls.append(model)
            return 503, {}, {"usage": {"total_tokens": 100}}
        result = self.run_quiet(ModelGateway(transport=transport, token_budget=100,
                                             base_backoff=0, max_sleep=0))
        self.assertTrue(result.fallback)
        self.assertEqual(len(calls), 1)

    def test_retry_checks_deadline_after_sleep(self):
        clock = [0.0]
        calls = []
        def transport(model, messages):
            calls.append(model)
            return 503, {}, {}
        def sleep(delay):
            clock[0] += 2.0
        with patch("app.gateway.time.monotonic", side_effect=lambda: clock[0]), patch("app.gateway.time.sleep", side_effect=sleep):
            result = self.run_quiet(ModelGateway(transport=transport, budget_seconds=1))
        self.assertTrue(result.fallback)
        self.assertEqual(len(calls), 1)

    def test_429_fails_over_without_retry_sleep(self):
        calls = []
        def transport(model, messages):
            calls.append(model)
            if model == CANONICAL_CHAIN[0]:
                return 429, {"Retry-After": "10"}, {}
            return 200, {}, {"choices": [{"message": {"content": "ok"}}]}
        gw = ModelGateway(transport=transport, max_retries=3, base_backoff=1)
        with patch("app.gateway.time.sleep") as sleep:
            result = self.run_quiet(gw)
        self.assertEqual(calls, list(CANONICAL_CHAIN[:2]))
        sleep.assert_not_called()
        self.assertEqual(result.model, CANONICAL_CHAIN[1])

    def test_small_remaining_budget_is_not_rounded_up(self):
        gw = ModelGateway()
        self.assertLessEqual(gw.read_timeout_for(CANONICAL_CHAIN[0], remaining=0.2), 0.2)

    def test_completion_budget_has_no_minimum_64_overshoot(self):
        gw = ModelGateway(token_budget=100, max_retries=0)
        limits = []
        def post(model, messages, max_tokens=None, remaining=None):
            limits.append(max_tokens)
            return 200, {}, {"choices": [{"message": {"content": ""}}], "usage": {"total_tokens": 90}}
        with patch.object(gw, "_post", side_effect=post):
            self.run_quiet(gw)
        self.assertEqual(limits, [100, 10])

    def test_negative_usage_does_not_refund_budget(self):
        gw = ModelGateway(token_budget=100, max_retries=0)
        limits = []
        def post(model, messages, max_tokens=None, remaining=None):
            limits.append(max_tokens)
            return 503, {}, {"usage": {"total_tokens": -900}}
        with patch.object(gw, "_post", side_effect=post):
            self.run_quiet(gw)
        self.assertTrue(all(n <= 100 for n in limits))

    def test_multipart_non_string_provider_text_is_ignored(self):
        payload = {"choices": [{"message": {"content": [{"text": None}, {"text": "safe"}, {"text": 1}]}}]}
        self.assertEqual(extract_text(payload), "safe")

    def test_malformed_usage_does_not_crash_success(self):
        gw = ModelGateway(transport=lambda m, msgs: (200, {}, {"choices": [{"message": {"content": "safe"}}], "usage": [1]}))
        self.assertEqual(self.run_quiet(gw).text, "safe")

    def test_http_response_is_closed_and_connect_window_is_clamped(self):
        from unittest.mock import Mock
        gw = ModelGateway(api_key="test-only")
        response = Mock(status_code=200, headers={})
        response.iter_content.return_value = iter([b"{}"])
        with patch.object(gw._session, "post", return_value=response) as post:
            gw._post(CANONICAL_CHAIN[0], [], remaining=0.2)
        self.assertEqual(post.call_args.kwargs["timeout"], (0.2, 0.2))
        response.close.assert_called_once()

    def test_expired_post_does_not_touch_network(self):
        from app.gateway import GatewayError
        gw = ModelGateway(api_key="test-only")
        with patch.object(gw._session, "post") as post:
            with self.assertRaises(GatewayError):
                gw._post(CANONICAL_CHAIN[0], [], remaining=0)
        post.assert_not_called()

    def test_100_concurrent_outages_recover_on_shared_gateway(self):
        from concurrent.futures import ThreadPoolExecutor
        from app.gateway import GatewayError
        from requests import Timeout
        counter = [0]
        import threading
        lock = threading.Lock()
        def outage(model, messages):
            with lock:
                counter[0] += 1
                n = counter[0]
            if n % 3 == 0:
                raise Timeout("injected read timeout")
            return (429 if n % 3 == 1 else 503), {}, {}
        gw = ModelGateway(transport=outage, max_retries=0, base_backoff=0)
        with patch.object(gw, "_log"), ThreadPoolExecutor(max_workers=100) as pool:
            results = list(pool.map(lambda _: gw.chat("fix contrast"), range(200)))
        self.assertTrue(all(r.fallback and r.text for r in results))
        for breaker in gw.breakers.values():
            breaker.recovery_timeout = 0
        gw.transport = lambda m, msgs: (200, {}, {"choices": [{"message": {"content": "recovered"}}]})
        with patch.object(gw, "_log"):
            result = gw.chat("fix contrast")
        self.assertFalse(result.fallback)
        self.assertEqual(result.text, "recovered")
        self.assertEqual(gw.breakers[result.model].snapshot()["state"], "closed")
