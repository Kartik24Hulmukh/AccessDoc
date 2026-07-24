"""Tests for EAA evidence pack generator."""
import os
import sys
import unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.models import AuditSummary, AuditViolation
from app.eaa import generate_eaa_pack, _md


class TestEaa(unittest.TestCase):
    def _data(self):
        summary = AuditSummary(critical=1, serious=0, total_violations=1,
                               url="https://example.com", engine_version="4.11.2")
        violations = [AuditViolation(id="image-alt", impact="critical", description="d",
                                     help_url="u", wcag_scs=["1.1.1"], nodes=2)]
        return summary, violations

    def test_is_string(self):
        s, v = self._data()
        self.assertIsInstance(generate_eaa_pack(s, v), str)

    def test_contains_eaa_title(self):
        s, v = self._data()
        self.assertIn("EAA Accessibility Evidence Pack", generate_eaa_pack(s, v))

    def test_en_301_549_clause(self):
        s, v = self._data()
        self.assertIn("9.1.1.1", generate_eaa_pack(s, v))

    def test_coverage_limit_stated(self):
        s, v = self._data()
        self.assertIn("30-57", generate_eaa_pack(s, v))

    def test_client_name_escaped(self):
        s, v = self._data()
        self.assertIn("Ev\\|il", generate_eaa_pack(s, v, client_name="Ev|il"))

    def test_md_escape(self):
        self.assertEqual(_md("a|b"), "a\\|b")
        self.assertNotIn("\n", _md("a\nb"))

    def test_no_violations(self):
        out = generate_eaa_pack(AuditSummary(url="https://x.com"), [])
        self.assertIn("No automated failures detected", out)


if __name__ == "__main__":
    unittest.main()
