"""Tests for manual-findings merge."""
import os
import sys
import unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.models import AuditSummary, AuditViolation, SOURCE_MANUAL, SOURCE_AUTOMATED
from app.manual import parse_manual_findings, merge_findings


class TestManual(unittest.TestCase):
    def test_parse_list_of_dicts(self):
        viols = parse_manual_findings([{"id": "keyboard-trap", "impact": "serious",
                                        "description": "trap", "wcag_scs": "2.1.2"}])
        self.assertEqual(len(viols), 1)
        self.assertEqual(viols[0].source, SOURCE_MANUAL)
        self.assertEqual(viols[0].wcag_scs, ["2.1.2"])

    def test_parse_csv(self):
        csv = "id,impact,description,wcag_scs\nfocus-order,moderate,bad order,2.4.3\n"
        viols = parse_manual_findings(csv)
        self.assertEqual(len(viols), 1)
        self.assertEqual(viols[0].id, "focus-order")
        self.assertEqual(viols[0].impact, "moderate")

    def test_parse_markdown_table(self):
        md = ("| id | impact | description | wcag_scs |\n"
              "|----|--------|-------------|----------|\n"
              "| alt-text | critical | missing alt | 1.1.1 |\n")
        viols = parse_manual_findings(md)
        self.assertEqual(len(viols), 1)
        self.assertEqual(viols[0].id, "alt-text")
        self.assertEqual(viols[0].impact, "critical")

    def test_invalid_impact_defaults_moderate(self):
        viols = parse_manual_findings([{"id": "x", "impact": "apocalyptic", "description": "d"}])
        self.assertEqual(viols[0].impact, "moderate")

    def test_multi_sc_split(self):
        viols = parse_manual_findings([{"id": "x", "impact": "minor", "description": "d",
                                        "wcag_scs": "1.1.1; 4.1.2"}])
        self.assertEqual(set(viols[0].wcag_scs), {"1.1.1", "4.1.2"})

    def test_merge_updates_summary(self):
        auto = [AuditViolation(id="image-alt", impact="critical", description="d",
                               help_url="u", wcag_scs=["1.1.1"], source=SOURCE_AUTOMATED)]
        manual = parse_manual_findings([{"id": "kbd", "impact": "serious", "description": "d"}])
        summary = AuditSummary()
        merged = merge_findings(auto, manual, summary)
        self.assertEqual(len(merged), 2)
        self.assertEqual(summary.total_violations, 2)
        self.assertEqual(summary.manual_findings, 1)
        self.assertEqual(summary.critical, 1)
        self.assertEqual(summary.serious, 1)

    def test_empty_input(self):
        self.assertEqual(parse_manual_findings(None), [])
        self.assertEqual(parse_manual_findings(""), [])


if __name__ == "__main__":
    unittest.main()
