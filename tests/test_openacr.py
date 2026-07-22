"""Tests for OpenACR YAML exporter."""
import unittest
from app.models import AuditSummary, AuditViolation
from app.openacr import generate_openacr_yaml, EN_301_549_MAP


class TestOpenACR(unittest.TestCase):
    def _make_summary(self):
        return AuditSummary(critical=1, serious=2, total_violations=3, engine_version="4.11.2")

    def _make_violations(self):
        return [
            AuditViolation(id="image-alt", impact="critical", description="img alt",
                           help_url="u", wcag_scs=["1.1.1"], nodes=1),
            AuditViolation(id="color-contrast", impact="serious", description="contrast",
                           help_url="u", wcag_scs=["1.4.3"], nodes=2),
        ]

    def test_output_is_string(self):
        yaml = generate_openacr_yaml(self._make_summary(), self._make_violations())
        self.assertIsInstance(yaml, str)

    def test_starts_with_yaml_doc_marker(self):
        yaml = generate_openacr_yaml(self._make_summary(), self._make_violations())
        self.assertTrue(yaml.startswith("---"))

    def test_schema_version_present(self):
        yaml = generate_openacr_yaml(self._make_summary(), self._make_violations())
        self.assertIn('schema_version: "0.1"', yaml)

    def test_client_name_in_output(self):
        yaml = generate_openacr_yaml(self._make_summary(), self._make_violations(), client_name="ACME Corp")
        self.assertIn("ACME Corp", yaml)

    def test_failing_sc_listed(self):
        yaml = generate_openacr_yaml(self._make_summary(), self._make_violations())
        self.assertIn("1.1.1", yaml)
        self.assertIn("1.4.3", yaml)

    def test_en_301_549_clause_mapping(self):
        self.assertEqual(EN_301_549_MAP["1.1.1"], "9.1.1.1")
        self.assertEqual(EN_301_549_MAP["1.4.3"], "9.1.4.3")
        self.assertEqual(EN_301_549_MAP["4.1.2"], "9.4.1.2")

    def test_en_301_549_clause_in_output(self):
        yaml = generate_openacr_yaml(self._make_summary(), self._make_violations())
        self.assertIn("9.1.1.1", yaml)

    def test_no_violations_produces_supports(self):
        yaml = generate_openacr_yaml(self._make_summary(), [])
        self.assertIn("Supports", yaml)

    def test_audit_date_in_output(self):
        yaml = generate_openacr_yaml(self._make_summary(), [], audit_date="2026-07-23")
        self.assertIn("2026-07-23", yaml)


if __name__ == "__main__":
    unittest.main()
