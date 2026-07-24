"""Tests for time-series / regression trend."""
import json
import os
import sys
import unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.models import AuditViolation
from app.timeseries import build_trend, rule_ids_for_receipt, _sha256_of_receipt


class TestTimeseries(unittest.TestCase):
    def _cur(self):
        return [
            AuditViolation(id="image-alt", impact="critical", description="d",
                           help_url="u", wcag_scs=["1.1.1"]),
            AuditViolation(id="color-contrast", impact="serious", description="d",
                           help_url="u", wcag_scs=["1.4.3"]),
        ]

    def test_new_and_fixed(self):
        prior = {"rule_ids": ["image-alt", "link-name"], "summary": {"total_violations": 2}}
        trend = json.loads(build_trend(prior, {"summary": {"total_violations": 2}}, self._cur()))
        self.assertIn("color-contrast", trend["new_rules"])
        self.assertIn("link-name", trend["fixed_rules"])
        self.assertIn("image-alt", trend["persisting_rules"])

    def test_delta_total(self):
        prior = {"rule_ids": ["image-alt"], "summary": {"total_violations": 1}}
        trend = json.loads(build_trend(prior, {"summary": {"total_violations": 2}}, self._cur()))
        self.assertEqual(trend["delta_total_violations"], 1)

    def test_regressed_flag(self):
        prior = {"rule_ids": [], "summary": {"total_violations": 0}}
        trend = json.loads(build_trend(prior, {"summary": {"total_violations": 2}}, self._cur()))
        self.assertTrue(trend["regressed"])

    def test_prev_sha_present(self):
        trend = json.loads(build_trend({"rule_ids": [], "summary": {}}, {"summary": {}}, self._cur()))
        self.assertEqual(len(trend["prev_receipt_sha256"]), 64)

    def test_sha_deterministic(self):
        self.assertEqual(_sha256_of_receipt({"a": 1, "b": 2}),
                         _sha256_of_receipt({"b": 2, "a": 1}))

    def test_rule_ids_helper(self):
        self.assertEqual(rule_ids_for_receipt(self._cur()), ["color-contrast", "image-alt"])

    def test_prior_as_string(self):
        prior = json.dumps({"rule_ids": ["image-alt"], "summary": {"total_violations": 1}})
        trend = json.loads(build_trend(prior, {"summary": {"total_violations": 2}}, self._cur()))
        self.assertIn("color-contrast", trend["new_rules"])


if __name__ == "__main__":
    unittest.main()
