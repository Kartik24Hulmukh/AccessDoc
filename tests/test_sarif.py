"""Tests for SARIF 2.1.0 exporter."""
import json
import os
import sys
import unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.models import AuditSummary, AuditViolation
from app.sarif import generate_sarif, _level_for


class TestSarif(unittest.TestCase):
    def _data(self):
        summary = AuditSummary(critical=1, serious=1, total_violations=2,
                               url="https://example.com", engine_version="4.11.2")
        violations = [
            AuditViolation(id="image-alt", impact="critical", description="alt",
                           help_url="https://d.com", wcag_scs=["1.1.1"], nodes=2),
            AuditViolation(id="color-contrast", impact="serious", description="contrast",
                           help_url="https://d.com", wcag_scs=["1.4.3"], nodes=1),
        ]
        return summary, violations

    def test_valid_json(self):
        s, v = self._data()
        self.assertEqual(json.loads(generate_sarif(s, v))["version"], "2.1.0")

    def test_has_runs(self):
        s, v = self._data()
        self.assertEqual(len(json.loads(generate_sarif(s, v))["runs"]), 1)

    def test_rules_deduplicated(self):
        s, v = self._data()
        v.append(v[0])
        log = json.loads(generate_sarif(s, v))
        ids = [r["id"] for r in log["runs"][0]["tool"]["driver"]["rules"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_results_count(self):
        s, v = self._data()
        self.assertEqual(len(json.loads(generate_sarif(s, v))["runs"][0]["results"]), 2)

    def test_level_mapping(self):
        self.assertEqual(_level_for("critical"), "error")
        self.assertEqual(_level_for("serious"), "error")
        self.assertEqual(_level_for("moderate"), "warning")
        self.assertEqual(_level_for("minor"), "note")
        self.assertEqual(_level_for("unknown"), "warning")

    def test_rule_index_valid(self):
        s, v = self._data()
        log = json.loads(generate_sarif(s, v))
        rules = log["runs"][0]["tool"]["driver"]["rules"]
        for res in log["runs"][0]["results"]:
            self.assertEqual(rules[res["ruleIndex"]]["id"], res["ruleId"])

    def test_empty_violations(self):
        log = json.loads(generate_sarif(AuditSummary(url="https://x.com"), []))
        self.assertEqual(log["runs"][0]["results"], [])

    def test_wcag_tags_present(self):
        s, v = self._data()
        log = json.loads(generate_sarif(s, v))
        rules = log["runs"][0]["tool"]["driver"]["rules"]
        img = next(r for r in rules if r["id"] == "image-alt")
        self.assertIn("wcag-1.1.1", img["properties"]["tags"])


if __name__ == "__main__":
    unittest.main()
