"""Tests for time-series / regression trend."""
import json
import os
import sys
import unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.models import AuditViolation
from app.timeseries import build_trend, rule_ids_for_receipt, _sha256_of_receipt


def _receipt(rule_ids, total):
    # Comparable supplied metadata is necessary; bare counts cannot imply scope.
    return {"schema_version": "1.1", "url": "https://example.test/page",
            "client_name": "Synthetic", "engine_version": "4.11.2",
            "catalog_version": "test", "rule_ids": rule_ids,
            "summary": {"total_violations": total}}


class TestTimeseries(unittest.TestCase):
    def _cur(self):
        return [
            AuditViolation(id="image-alt", impact="critical", description="d",
                           help_url="u", wcag_scs=["1.1.1"]),
            AuditViolation(id="color-contrast", impact="serious", description="d",
                           help_url="u", wcag_scs=["1.4.3"]),
        ]

    def test_new_and_not_observed(self):
        prior = _receipt(["image-alt", "link-name"], 2)
        trend = json.loads(build_trend(prior, _receipt(["image-alt", "color-contrast"], 2), self._cur()))
        self.assertIn("color-contrast", trend["new_rules"])
        self.assertIn("link-name", trend["not_observed_rules"])
        self.assertIn("image-alt", trend["persisting_rules"])

    def test_delta_total(self):
        prior = _receipt(["image-alt"], 1)
        trend = json.loads(build_trend(prior, _receipt(["image-alt", "color-contrast"], 2), self._cur()))
        self.assertEqual(trend["delta_total_violations"], 1)

    def test_observed_new_rules_not_regression_claim(self):
        prior = _receipt([], 0)
        trend = json.loads(build_trend(prior, _receipt(["image-alt", "color-contrast"], 2), self._cur()))
        self.assertIn("color-contrast", trend["new_rules"])
        self.assertNotIn("regressed", trend)

    def test_prev_sha_present(self):
        trend = json.loads(build_trend({"rule_ids": [], "summary": {}}, {"summary": {}}, self._cur()))
        self.assertEqual(len(trend["prev_receipt_sha256"]), 64)

    def test_sha_deterministic(self):
        self.assertEqual(_sha256_of_receipt({"a": 1, "b": 2}),
                         _sha256_of_receipt({"b": 2, "a": 1}))

    def test_rule_ids_helper(self):
        self.assertEqual(rule_ids_for_receipt(self._cur()), ["color-contrast", "image-alt"])

    def test_prior_as_string(self):
        prior = json.dumps(_receipt(["image-alt"], 1))
        trend = json.loads(build_trend(prior, _receipt(["image-alt", "color-contrast"], 2), self._cur()))
        self.assertIn("color-contrast", trend["new_rules"])


if __name__ == "__main__":
    unittest.main()
