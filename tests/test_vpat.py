"""Tests for VPAT draft generator."""
import os
import sys
import unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.models import AuditSummary, AuditViolation
from app.vpat import generate_vpat_html


class TestVpat(unittest.TestCase):
    def _data(self):
        summary = AuditSummary(critical=1, total_violations=1,
                               url="https://example.com", engine_version="4.11.2")
        violations = [AuditViolation(id="image-alt", impact="critical", description="d",
                                     help_url="u", wcag_scs=["1.1.1"], nodes=2)]
        return summary, violations

    def test_is_html(self):
        s, v = self._data()
        self.assertIn("<!DOCTYPE html>", generate_vpat_html(s, v))

    def test_marked_draft(self):
        s, v = self._data()
        self.assertIn("DRAFT", generate_vpat_html(s, v))

    def test_failing_sc_does_not_support(self):
        s, v = self._data()
        self.assertIn("Does Not Support", generate_vpat_html(s, v))

    def test_client_name_escaped(self):
        s, v = self._data()
        out = generate_vpat_html(s, v, client_name="<script>x</script>")
        self.assertNotIn("<script>x</script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_coverage_note(self):
        s, v = self._data()
        self.assertIn("30-57", generate_vpat_html(s, v))

    def test_includes_sc_names(self):
        s, v = self._data()
        self.assertIn("Non-text Content", generate_vpat_html(s, v))


if __name__ == "__main__":
    unittest.main()
