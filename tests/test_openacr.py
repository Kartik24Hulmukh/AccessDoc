"""Tests for OpenACR YAML exporter conforming to GSA OpenACR 0.1.0 schema."""
import json
from pathlib import Path
import unittest
import yaml
import jsonschema

from app.models import AuditSummary, AuditViolation
from app.openacr import generate_openacr_yaml, EN_301_549_MAP

SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "openacr-0.1.0.json"


class TestOpenACR(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            cls.schema = json.load(f)
        cls.validator = jsonschema.Draft7Validator(cls.schema)

    def _make_summary(self):
        return AuditSummary(critical=1, serious=2, total_violations=3, engine_version="4.11.2")

    def _make_violations(self):
        return [
            AuditViolation(id="image-alt", impact="critical", description="img alt",
                           help_url="u", wcag_scs=["1.1.1"], nodes=1),
            AuditViolation(id="color-contrast", impact="serious", description="contrast",
                           help_url="u", wcag_scs=["1.4.3"], nodes=2),
        ]

    def _assert_gsa_schema_valid(self, yaml_str: str):
        """Assert the emitted YAML string strictly conforms to GSA's JSON Schema."""
        data = yaml.safe_load(yaml_str)
        errors = list(self.validator.iter_errors(data))
        if errors:
            error_msgs = [f"Path: {list(e.path)} -> {e.message}" for e in errors]
            self.fail(f"OpenACR YAML failed GSA schema validation ({len(errors)} errors):\n" + "\n".join(error_msgs))

    def test_output_is_string(self):
        out = generate_openacr_yaml(self._make_summary(), self._make_violations())
        self.assertIsInstance(out, str)

    def test_starts_with_yaml_doc_marker(self):
        out = generate_openacr_yaml(self._make_summary(), self._make_violations())
        self.assertTrue(out.startswith("---"))

    def test_gsa_schema_validation_with_violations(self):
        """Emitted OpenACR YAML with violations must pass GSA 0.1.0 schema."""
        out = generate_openacr_yaml(self._make_summary(), self._make_violations(), client_name="ACME Corp", audit_date="2026-07-23")
        self._assert_gsa_schema_valid(out)

    def test_gsa_schema_validation_clean_scan(self):
        """Emitted OpenACR YAML for a clean scan (0 violations) must pass GSA schema."""
        out = generate_openacr_yaml(self._make_summary(), [], client_name="Clean Site", audit_date="2026-07-23")
        self._assert_gsa_schema_valid(out)

    def test_required_root_fields(self):
        out = generate_openacr_yaml(self._make_summary(), self._make_violations(), client_name="ACME Corp", audit_date="2026-07-23")
        data = yaml.safe_load(out)
        self.assertIn("title", data)
        self.assertIn("product", data)
        self.assertIn("author", data)
        self.assertEqual(data["product"]["name"], "ACME Corp")
        self.assertIn("email", data["author"])
        self.assertEqual(data["report_date"], "2026-07-23")

    def test_failing_sc_listed_in_chapters(self):
        out = generate_openacr_yaml(self._make_summary(), self._make_violations())
        data = yaml.safe_load(out)
        level_a_criteria = data["chapters"]["success_criteria_level_a"]["criteria"]
        level_aa_criteria = data["chapters"]["success_criteria_level_aa"]["criteria"]

        sc_nums_a = [c["num"] for c in level_a_criteria]
        sc_nums_aa = [c["num"] for c in level_aa_criteria]

        self.assertIn("1.1.1", sc_nums_a)
        self.assertIn("1.4.3", sc_nums_aa)

    def test_en_301_549_clause_mapping(self):
        self.assertEqual(EN_301_549_MAP["1.1.1"], "9.1.1.1")
        self.assertEqual(EN_301_549_MAP["1.4.3"], "9.1.4.3")
        self.assertEqual(EN_301_549_MAP["4.1.2"], "9.4.1.2")

    def test_emitter_uses_level_table_for_level_a(self):
        """Assert that 1.3.1, 2.4.1, 3.3.2, and 4.1.2 appear in success_criteria_level_a."""
        from app.service import build_artifacts
        sample_path = Path(__file__).parent.parent / "fixtures" / "axe-sample.json"
        y = build_artifacts({
            "scanner_input": sample_path.read_text(encoding="utf-8"),
            "client_name": "ACME Corp"
        }).openacr_yaml
        level_a_section = y.split("success_criteria_level_aa")[0]
        self.assertIn("1.3.1", level_a_section)
        self.assertIn("2.4.1", level_a_section)
        self.assertIn("3.3.2", level_a_section)
        self.assertIn("4.1.2", level_a_section)

    def test_unmapped_criterion_not_in_aa_and_1_3_2_in_level_a(self):
        """GATE: chapter_for('1.3.2') == 'success_criteria_level_a' and unmapped not in AA."""
        from app.wcag_levels import chapter_for
        self.assertEqual(chapter_for("1.3.2"), "success_criteria_level_a")

        v_unmapped = [
            AuditViolation(id="custom-rule", impact="serious", description="unmapped rule",
                           help_url="u", wcag_scs=["9.9.9"], nodes=1)
        ]
        out = generate_openacr_yaml(self._make_summary(), v_unmapped, client_name="ACME Corp")
        data = yaml.safe_load(out)
        aa_criteria = data["chapters"].get("success_criteria_level_aa", {}).get("criteria", [])
        sc_nums_aa = [c["num"] for c in aa_criteria]
        self.assertNotIn("9.9.9", sc_nums_aa)
        self.assertIn("9.9.9", data.get("notes", ""))

    def test_restored_chapters_present_and_disabled(self):
        """functional_performance_criteria and support_documentation_and_services are present and disabled."""
        out = generate_openacr_yaml(self._make_summary(), self._make_violations(), client_name="ACME Corp")
        data = yaml.safe_load(out)
        self.assertIn("functional_performance_criteria", data["chapters"])
        self.assertTrue(data["chapters"]["functional_performance_criteria"]["disabled"])
        self.assertIn("support_documentation_and_services", data["chapters"])
        self.assertTrue(data["chapters"]["support_documentation_and_services"]["disabled"])
        self._assert_gsa_schema_valid(out)


if __name__ == "__main__":
    unittest.main()
