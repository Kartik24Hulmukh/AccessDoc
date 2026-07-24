"""Tests for provenance-labeled enrichment."""
import os
import sys
import unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.models import AuditViolation
from app.enrich import enrich_violations, explain_sc, PROVENANCE_DETERMINISTIC


class TestEnrich(unittest.TestCase):
    def test_explain_known_sc(self):
        kb = explain_sc("1.1.1")
        self.assertIsNotNone(kb)
        self.assertIn("plain", kb)

    def test_explain_unknown_sc(self):
        self.assertIsNone(explain_sc("9.9.9"))

    def test_enrich_labels_provenance(self):
        v = [AuditViolation(id="image-alt", impact="critical", description="d",
                            help_url="u", wcag_scs=["1.1.1"])]
        out = enrich_violations(v)
        self.assertEqual(out["items"][0]["explanations"][0]["provenance"],
                         PROVENANCE_DETERMINISTIC)

    def test_enrich_dedupes_rules(self):
        v = [AuditViolation(id="image-alt", impact="critical", description="d",
                            help_url="u", wcag_scs=["1.1.1"])] * 2
        self.assertEqual(len(enrich_violations(v)["items"]), 1)

    def test_enrich_unknown_sc_no_explanation(self):
        v = [AuditViolation(id="x", impact="minor", description="d",
                            help_url="u", wcag_scs=["9.9.9"])]
        self.assertEqual(enrich_violations(v)["items"][0]["explanations"], [])

    def test_has_note_about_ai(self):
        self.assertIn("AI-ASSISTED", enrich_violations([])["note"])


if __name__ == "__main__":
    unittest.main()
