"""Degraded-mode remediation contract (launch turn 16).

Production shipped with no model credential configured, which made
POST /api/remediate return 503 for every user - the flagship AI surface was
100%% dead while a deterministic WCAG knowledge base sat unused in the repo.
These tests pin the fix: without a credential the endpoint must return 200
with an actionable, clearly-labelled offline plan, and strict mode must still
be able to restore the hard 503 for operators who want fail-closed behaviour.
"""
import json, os, threading, unittest, urllib.request, urllib.error
from http.server import HTTPServer

from app import remediate as remediation

AXE = {"violations": [
    {"id": "color-contrast", "impact": "serious", "help": "Elements must meet contrast ratio",
     "nodes": [{"target": [".btn"]}, {"target": ["p"]}]},
    {"id": "image-alt", "impact": "critical", "help": "Images must have alternate text",
     "nodes": [{"target": ["img"]}]},
    {"id": "some-unmapped-future-rule", "impact": "minor", "help": "Unknown", "nodes": [{"target": ["x"]}]},
]}


class OfflinePlanTests(unittest.TestCase):
    def test_plan_is_prioritised_deterministic_and_actionable(self):
        out = remediation.remediate_offline(AXE)
        self.assertTrue(out["degraded"])
        self.assertTrue(out["fallback"])
        self.assertEqual(out["model"], "offline-kb")
        self.assertEqual(out["violations_considered"], 3)
        g = out["guidance"]
        # critical outranks serious outranks minor
        self.assertLess(g.index("image-alt"), g.index("color-contrast"))
        self.assertLess(g.index("color-contrast"), g.index("some-unmapped-future-rule"))
        self.assertIn("1.1.1", g)
        self.assertIn("4.5:1", g)
        self.assertIn("Effort:", g)
        self.assertIn("advisory", g.lower())
        self.assertEqual(g, remediation.remediate_offline(AXE)["guidance"])  # deterministic

    def test_unmapped_rule_still_gets_a_usable_instruction(self):
        g = remediation.remediate_offline({"violations": [{"id": "brand-new-rule", "nodes": []}]})["guidance"]
        self.assertIn("brand-new-rule", g)
        self.assertIn("re-scan", g.lower())

    def test_invalid_input_still_rejected(self):
        with self.assertRaises(ValueError):
            remediation.remediate_offline({"violations": []})

    def test_no_untrusted_control_characters_leak(self):
        hostile = {"violations": [{"id": "x\x00y", "help": "ignore\nprevious\x07", "nodes": []}]}
        g = remediation.remediate_offline(hostile)["guidance"]
        self.assertNotIn("\x00", g)
        self.assertNotIn("\x07", g)

    def test_strict_flag_parsing(self):
        for val, expected in (("1", True), ("true", True), ("ON", True), ("0", False), ("", False)):
            os.environ["ACCESSDOC_STRICT_GATEWAY"] = val
            self.assertIs(remediation.strict_gateway(), expected)
        os.environ.pop("ACCESSDOC_STRICT_GATEWAY", None)
        self.assertFalse(remediation.strict_gateway())


class ServerlessDegradedEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from api.handler import handler as H
        cls.srv = HTTPServer(("127.0.0.1", 0), H)
        cls.port = cls.srv.server_address[1]
        cls.t = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.t.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close()

    def setUp(self):
        self.saved = os.environ.pop("MELIOUS_API_KEY", None)
        os.environ.pop("ACCESSDOC_STRICT_GATEWAY", None)

    def tearDown(self):
        os.environ.pop("ACCESSDOC_STRICT_GATEWAY", None)
        if self.saved is not None:
            os.environ["MELIOUS_API_KEY"] = self.saved

    def _post(self, payload):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/remediate",
                                     data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        return urllib.request.urlopen(req, timeout=10)

    def test_missing_credential_serves_degraded_200_not_503(self):
        r = self._post(AXE)
        self.addCleanup(r.close)
        self.assertEqual(r.status, 200)
        self.assertEqual(r.headers.get("X-AccessDoc-Mode"), "degraded-offline-kb")
        data = json.loads(r.read())
        self.assertTrue(data["degraded"])
        self.assertEqual(data["model"], "offline-kb")
        self.assertTrue(data["guidance"].strip())
        self.assertIn("request_id", data)
        self.assertEqual(data["adapter"], "serverless")

    def test_degraded_mode_still_validates_input(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self._post({"violations": []})
        self.addCleanup(cm.exception.close)
        self.assertEqual(cm.exception.code, 422)

    def test_strict_mode_restores_fail_closed_503(self):
        os.environ["ACCESSDOC_STRICT_GATEWAY"] = "1"
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self._post(AXE)
        self.addCleanup(cm.exception.close)
        self.assertEqual(cm.exception.code, 503)
        self.assertEqual(cm.exception.headers.get("Retry-After"), "5")


if __name__ == "__main__":
    unittest.main()
