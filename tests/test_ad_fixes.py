"""Regression tests for AD-01..AD-08 (2026-09-13 fixes)."""
import json, unittest
from app.parser import parse_axe_json
from app.service import build_artifacts
from app.bundle import build_bundle
from api.handler import handler as BundleHandler


def axe(violations, **kw):
    d = {"url": "https://example.com", "testEngine": {"name": "axe-core", "version": "4.11.2"},
         "violations": violations, "passes": [], "incomplete": []}
    d.update(kw)
    return json.dumps(d)


class CountInvariantTests(unittest.TestCase):
    def _summary(self, violations):
        return parse_axe_json(axe(violations))

    def test_multi_target_rule_counts_match_details(self):  # AD-01
        s, viols = self._summary([{"id": "color-contrast", "impact": "serious", "description": "d",
              "helpUrl": "https://deque.com/cci", "nodes": [{"target": ["#a"]}, {"target": ["#b"]}]}])
        self.assertEqual(len(viols), 2)
        self.assertEqual(s.serious, 2)
        self.assertEqual(s.total_violations, s.critical + s.serious + s.moderate + s.minor + s.unknown)
        self.assertEqual(s.total_violations, len(viols))

    def test_unknown_impact_buckets_as_unknown(self):  # AD-04
        s, viols = self._summary([{"id": "x", "impact": "catastrophic", "description": "d",
                                   "helpUrl": "h", "nodes": [{}]}])
        self.assertEqual(s.unknown, 1)
        self.assertEqual(s.total_violations, 1)

    def test_malformed_shapes_rejected(self):  # AD-05
        for bad in [{"id": "x", "impact": "serious", "description": {"a": 1}, "helpUrl": "h", "nodes": [{}]},
                    {"id": "x", "impact": "serious", "description": "d", "helpUrl": [1], "nodes": [{}]},
                    {"id": "x", "impact": "serious", "description": "d", "helpUrl": "h", "nodes": [{"target": {"css": "x"}}]}]:
            with self.assertRaises(ValueError):
                parse_axe_json(axe([bad]))
        with self.assertRaises(ValueError):
            parse_axe_json(axe([{"id": "x", "impact": "serious"}], passes=[1]))

    def test_null_contract_identical_cli_and_api(self):  # AD-02
        parse_axe_json(json.dumps({"violations": None}))
        h = object.__new__(BundleHandler)
        ok, status, msg = h._validate_axe_structure({"violations": None})
        self.assertTrue(ok, msg)
        ok2, status2, msg2 = h._validate_axe_structure({})
        self.assertFalse(ok2)
        self.assertEqual(status2, 422)


class HtmlHandoffTests(unittest.TestCase):
    def _bundle_html(self):
        arts = build_artifacts({"scanner_input": axe([
            {"id": "color-contrast", "impact": "serious", "description": "Contrast too low",
             "helpUrl": "https://dequeuniversity.com/rules/axe/4.11/color-contrast",
             "nodes": [{"target": ["#header > button.submit"]}, {"target": ["#footer a"]}]}])})
        return arts.html_bytes.decode()

    def test_instance_level_targets_and_fingerprint(self):  # AD-03
        h = self._bundle_html()
        self.assertIn("#header &gt; button.submit", h)
        self.assertIn("#footer a", h)
        self.assertIn("Instance fingerprint", h)
        self.assertIn("Remediation reference", h)
        self.assertIn("Contrast too low", h)
        self.assertNotIn("<table", h)

    def test_provenance_warning_when_absent(self):  # AD-08
        arts = build_artifacts({"scanner_input": json.dumps({"violations": []})})
        self.assertIn("scanner provenance not supplied", arts.html_bytes.decode())


if __name__ == "__main__":
    unittest.main()
