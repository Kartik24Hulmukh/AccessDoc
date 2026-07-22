"""Tests for axe-core JSON parser."""
import json
import unittest
from app.parser import parse_axe_json


SAMPLE_AXE = {
    "url": "https://example.com",
    "testEngine": {"name": "axe-core", "version": "4.11.2"},
    "violations": [
        {
            "id": "image-alt",
            "impact": "critical",
            "description": "Images must have alternate text",
            "helpUrl": "https://dequeuniversity.com/rules/axe/4.11/image-alt",
            "nodes": [{"html": "<img src='a.png'>"}, {"html": "<img src='b.png'>"}]
        },
        {
            "id": "color-contrast",
            "impact": "serious",
            "description": "Elements must have sufficient color contrast",
            "helpUrl": "https://dequeuniversity.com/rules/axe/4.11/color-contrast",
            "nodes": [{"html": "<p style='color:#aaa'>text</p>"}]
        },
    ],
    "passes": [{"id": "aria-roles", "nodes": [{}, {}]}],
    "incomplete": [{"id": "label", "nodes": [{}]}],
}


class TestParser(unittest.TestCase):
    def setUp(self):
        self.summary, self.violations = parse_axe_json(SAMPLE_AXE)

    def test_summary_violation_counts(self):
        self.assertEqual(self.summary.total_violations, 2)
        self.assertEqual(self.summary.critical, 1)
        self.assertEqual(self.summary.serious, 1)

    def test_summary_passes(self):
        self.assertEqual(self.summary.total_passes, 1)

    def test_summary_incomplete(self):
        self.assertEqual(self.summary.total_incomplete, 1)

    def test_summary_url(self):
        self.assertEqual(self.summary.url, "https://example.com")

    def test_summary_engine_version(self):
        self.assertEqual(self.summary.engine_version, "4.11.2")

    def test_violations_list_length(self):
        self.assertEqual(len(self.violations), 2)

    def test_violation_wcag_sc_mapping(self):
        image_alt_v = next(v for v in self.violations if v.id == "image-alt")
        self.assertIn("1.1.1", image_alt_v.wcag_scs)

    def test_violation_node_count(self):
        image_alt_v = next(v for v in self.violations if v.id == "image-alt")
        self.assertEqual(image_alt_v.nodes, 2)

    def test_parse_from_json_string(self):
        summary, violations = parse_axe_json(json.dumps(SAMPLE_AXE))
        self.assertEqual(summary.total_violations, 2)

    def test_empty_axe_json(self):
        summary, violations = parse_axe_json({})
        self.assertEqual(summary.total_violations, 0)
        self.assertEqual(violations, [])

    def test_unknown_rule_has_empty_scs(self):
        data = {"violations": [{"id": "unknown-xyz", "impact": "minor",
                                 "description": "d", "helpUrl": "u", "nodes": []}]}
        _, violations = parse_axe_json(data)
        self.assertEqual(violations[0].wcag_scs, [])


if __name__ == "__main__":
    unittest.main()
