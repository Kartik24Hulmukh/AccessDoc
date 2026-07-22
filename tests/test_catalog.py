"""Tests for catalog module."""
import unittest
from app.catalog import (
    RULE_SC_MAP, get_wcag_scs, catalog_summary,
    CATALOG_VERSION, AXE_CORE_VERIFIED_VERSION, COVERAGE_NOTE
)


class TestCatalog(unittest.TestCase):
    def test_rule_count_gte_37(self):
        self.assertGreaterEqual(len(RULE_SC_MAP), 37)

    def test_image_alt_maps_to_111(self):
        self.assertIn("1.1.1", get_wcag_scs("image-alt"))

    def test_color_contrast_maps_to_143(self):
        self.assertIn("1.4.3", get_wcag_scs("color-contrast"))

    def test_html_has_lang_maps_to_311(self):
        self.assertIn("3.1.1", get_wcag_scs("html-has-lang"))

    def test_unknown_rule_returns_empty(self):
        self.assertEqual(get_wcag_scs("nonexistent-rule-xyz"), [])

    def test_catalog_version_format(self):
        self.assertIn("wcag-2.2", CATALOG_VERSION)

    def test_axe_core_version_format(self):
        parts = AXE_CORE_VERIFIED_VERSION.split(".")
        self.assertEqual(len(parts), 3)

    def test_coverage_note_contains_pct(self):
        self.assertIn("30", COVERAGE_NOTE)
        self.assertIn("57", COVERAGE_NOTE)

    def test_catalog_summary_keys(self):
        s = catalog_summary()
        self.assertIn("rule_count", s)
        self.assertIn("sc_count", s)
        self.assertIn("catalog_version", s)
        self.assertIn("axe_core_verified_version", s)
        self.assertIn("coverage_note", s)

    def test_catalog_summary_rule_count(self):
        s = catalog_summary()
        self.assertGreaterEqual(s["rule_count"], 37)

    def test_catalog_summary_sc_count(self):
        s = catalog_summary()
        self.assertGreaterEqual(s["sc_count"], 20)

    def test_all_sc_values_are_lists(self):
        for rule, scs in RULE_SC_MAP.items():
            self.assertIsInstance(scs, list, f"Rule {rule} SCs must be a list")

    def test_all_sc_values_nonempty(self):
        for rule, scs in RULE_SC_MAP.items():
            self.assertTrue(len(scs) > 0, f"Rule {rule} has empty SC list")


if __name__ == "__main__":
    unittest.main()
