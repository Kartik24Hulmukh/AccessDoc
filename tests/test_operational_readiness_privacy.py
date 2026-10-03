"""Passive serving readiness and two-boundary optional-model privacy."""
import json
import os
import threading
import unittest
from http.server import HTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

from app import remediate


class OperationalReadinessTests(unittest.TestCase):
    def test_auth_configuration_controls_readiness_not_liveness(self):
        from app.main import Handler
        from api.handler import handler
        for cls in (Handler, handler):
            server = HTTPServer(("127.0.0.1", 0), cls)
            runner = threading.Thread(
                target=lambda: server.serve_forever(poll_interval=0.01))
            runner.start()
            base = "http://127.0.0.1:%d" % server.server_port
            try:
                for required, key, status in (("true", "", 503),
                                              ("true", "local-readiness-test", 200),
                                              ("false", "", 200)):
                    with self.subTest(adapter=cls.__module__, required=required,
                                      configured=bool(key)), patch.dict(os.environ, {
                        "ALLOWED_HOSTS": "127.0.0.1:%d" % server.server_port,
                        "ACCESSDOC_REQUIRE_AUTH": required,
                        "ACCESSDOC_API_KEY": key, "ACCESSDOC_API_KEYS": ""}):
                        try:
                            response = urlopen(base + "/readyz", timeout=5)
                        except HTTPError as error:
                            response = error
                        with response:
                            self.assertEqual(response.code, status)
                            body = json.load(response)
                            self.assertEqual(body["readiness_reasons"],
                                ["AUTH_NOT_CONFIGURED"] if status == 503 else [])
                            self.assertNotIn("local-readiness-test", json.dumps(body))
                        with urlopen(base + "/healthz", timeout=5) as response:
                            self.assertEqual(response.status, 200)
            finally:
                server.shutdown()
                server.server_close()
                runner.join(2)
                self.assertFalse(runner.is_alive())


class ModelPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.payload = {"client_name": "PRIVATE-CLIENT-SENTINEL",
            "scanner_input": {"violations": [{
                "id": "image-alt", "impact": "serious", "help": "Images need text",
                "nodes": [{"target": ["#PRIVATE-SELECTOR-SENTINEL"]}]}]}}

    def test_external_prompt_omits_identity_and_selector(self):
        violations = remediate.extract_violations(self.payload)
        prompt = remediate.build_prompt(violations, self.payload["client_name"])
        for marker in ("PRIVATE-CLIENT-SENTINEL", "PRIVATE-SELECTOR-SENTINEL"):
            self.assertNotIn(marker, prompt)
        self.assertIn("rule=image-alt", prompt)
        self.assertIn("Images need text", prompt)

    def test_offline_plan_retains_local_context_without_gateway(self):
        with patch.object(remediate, "gateway", side_effect=AssertionError(
                "offline guidance must not invoke an external transport")):
            result = remediate.remediate_offline(self.payload)
        self.assertIn("PRIVATE-CLIENT-SENTINEL", result["guidance"])
        self.assertIn("PRIVATE-SELECTOR-SENTINEL", result["guidance"])
        self.assertEqual(result["tokens"], 0)

class PromptCoverageBudgetTests(unittest.TestCase):
    def test_unicode_scanner_selection_fits_two_lane_authorization(self):
        from app.gateway_budget import prompt_token_bound
        from app.gateway import ModelGateway
        from types import SimpleNamespace
        payload = {"violations": [{"id": str(i), "impact": "critical", "help": "界" * 300} for i in range(60)]}
        seen = []
        gw = ModelGateway(transport=lambda m, msgs: (seen.append(msgs) or (200, {}, {"choices": [{"message": {"content": "ok"}}], "usage": {"total_tokens": 20}})))
        try:
            with patch.object(remediate, "gateway", return_value=gw):
                result = remediate.remediate(payload)
            self.assertEqual(len(seen), 1)
            self.assertLessEqual(2 * (prompt_token_bound(seen[0]) + 1024), gw.token_budget)
            self.assertEqual(result["violations_received"], 25)
            self.assertGreater(result["violations_considered"], 0)
            self.assertLess(result["violations_considered"], 25)
            self.assertEqual(result["external_violations_authorized"], result["violations_considered"])
        finally:
            gw._session.close()

    def test_no_fitting_evidence_degrades_without_external_authorization(self):
        from app.gateway import ModelGateway
        calls = []
        gw = ModelGateway(token_budget=100, transport=lambda m, msgs: calls.append(m))
        try:
            with patch.object(remediate, "gateway", return_value=gw), patch.dict(os.environ, {"ACCESSDOC_STRICT_GATEWAY": "false"}):
                result = remediate.remediate({"violations": [{"id": "image-alt"}]})
            self.assertEqual(calls, [])
            self.assertTrue(result["fallback"])
            self.assertEqual(result["external_violations_authorized"], 0)
        finally:
            gw._session.close()
