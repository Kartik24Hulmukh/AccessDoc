"""Tests for models module."""
import unittest
from app.models import VERSION, DISCLAIMER, DISCLAIMER_COMPACT, COVERAGE_STATS, AuditViolation, AuditSummary


class TestModels(unittest.TestCase):
    def test_version_format(self):
        parts = VERSION.split(".")
        self.assertGreaterEqual(len(parts), 3)

    def test_disclaimer_contains_coverage_pct(self):
        self.assertIn("30", DISCLAIMER)
        self.assertIn("57", DISCLAIMER)

    def test_disclaimer_compact_shorter(self):
        self.assertLess(len(DISCLAIMER_COMPACT), len(DISCLAIMER))

    def test_coverage_stats_keys(self):
        self.assertIn("deque_2022", COVERAGE_STATS)
        self.assertIn("gds_2017", COVERAGE_STATS)

    def test_audit_violation_defaults(self):
        v = AuditViolation(id="image-alt", impact="critical", description="d", help_url="u")
        self.assertEqual(v.wcag_scs, [])
        self.assertEqual(v.nodes, 0)

    def test_audit_summary_defaults(self):
        s = AuditSummary()
        self.assertEqual(s.critical, 0)
        self.assertEqual(s.total_violations, 0)


if __name__ == "__main__":
    unittest.main()
