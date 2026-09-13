"""Adversarial regression tests for the September evidence-hardening pass."""
import json
import unittest
from collections import Counter
from app.parser import parse_axe_json
from app.service import build_artifacts
from app.manual import parse_manual_findings
from app.receipt_validate import validate_receipt
from app.limits import LimitExceeded


class ProductionHardeningTests(unittest.TestCase):
    def test_unknown_and_null_severity_never_become_minor(self):
        for impact in (None, "", "catastrophic"):
            summary, findings = parse_axe_json({"violations": [{"id": "x", "impact": impact}]})
            self.assertEqual(summary.unknown, 1)
            self.assertEqual(summary.minor, 0)
            self.assertEqual(findings[0].impact, "unknown")

    def test_long_targets_do_not_collapse(self):
        prefix = "#" + "a" * 210
        summary, findings = parse_axe_json({"violations": [{"id": "x", "nodes": [
            {"target": [prefix + "1"]}, {"target": [prefix + "2"]}]}]})
        self.assertEqual(len(findings), 2)
        self.assertNotEqual(findings[0].target, findings[1].target)
        self.assertTrue(all(len(v.target) <= 200 for v in findings))

    def test_malformed_nested_targets_fail_closed(self):
        for target in (42, True, [42], [[{}]], [[["#a"]]]):
            with self.subTest(target=target), self.assertRaises(ValueError):
                parse_axe_json({"violations": [{"id": "x", "nodes": [{"target": target}]}]})

    def test_html_uses_receipt_fingerprint(self):
        arts = build_artifacts({"scanner_input": {"violations": [{"id": "x"}]}})
        receipt = json.loads(arts.receipt_json)
        fp = receipt["violations"][0]["finding_fingerprint"]
        self.assertEqual(len(fp), 64)
        self.assertIn(fp, arts.html_bytes.decode())

    def test_manual_merge_preserves_unknown_count(self):
        arts = build_artifacts({"scanner_input": {"violations": [{"id": "x", "impact": "unknown"}]},
            "manual_findings": [{"id": "keyboard", "impact": "serious"}]})
        receipt = json.loads(arts.receipt_json)
        self.assertEqual(receipt["summary"]["unknown"], 1)
        self.assertEqual(receipt["summary"]["total_violations"], 2)

    def test_options_rejected_before_renderer(self):
        for key, value in (("client_name", {}), ("agency_name", []), ("audit_date", 1),
                           ("include_sarif", "false"), ("pdf_engine", "typo")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                build_artifacts({"scanner_input": {"violations": []}, key: value})

    def test_manual_malformed_entries_rejected(self):
        with self.assertRaises(ValueError):
            parse_manual_findings([{"id": "valid"}, 42])

    def test_manual_csv_limit_applies_after_parse(self):
        with self.assertRaises(LimitExceeded):
            parse_manual_findings("id,impact\n" + "x,serious\n" * 5001)

    def test_receipt_unhashable_rule_ids_is_error_not_crash(self):
        receipt = json.loads(build_artifacts({"scanner_input": {"violations": []}}).receipt_json)
        receipt["rule_ids"] = [{}]
        self.assertTrue(validate_receipt(receipt))

    def test_empty_receipt_cannot_declare_nonexistent_rules(self):
        receipt = json.loads(build_artifacts({"scanner_input": {"violations": []}}).receipt_json)
        receipt["rule_ids"] = ["fabricated"]
        self.assertTrue(validate_receipt(receipt))

    def test_100x_target_expansion_count_invariants(self):
        # One rule at baseline vs 100 distinct instances, not 100x claimed throughput.
        for scale in (1, 100):
            summary, findings = parse_axe_json({"violations": [{"id": "x", "impact": "serious",
                "nodes": [{"target": [f"#node-{i}"]} for i in range(scale)]}]})
            self.assertEqual(summary.serious, scale)
            self.assertEqual(summary.total_violations, len(findings))

    def test_javascript_help_link_not_active(self):
        arts = build_artifacts({"scanner_input": {"violations": [{"id": "x", "helpUrl": "javascript:alert(1)"}]}})
        self.assertNotIn('href="javascript:', arts.html_bytes.decode())

    def test_http_ignores_local_oversize_environment(self):
        from unittest.mock import patch
        from api.handler import handler
        h = object.__new__(handler)
        with patch.dict("os.environ", {"ACCESSDOC_ALLOW_OVERSIZED": "1"}):
            ok, status, message = h._validate_axe_structure({"violations": [], "url": "a" * 10001})
        self.assertFalse(ok)
        self.assertEqual(status, 413)

    def test_nested_scanner_string_depth_fails_without_crash(self):
        from api.handler import handler
        h = object.__new__(handler)
        from unittest.mock import patch
        # Other suites may raise the process recursion limit; inject the decoder
        # failure so this regression is deterministic across runtimes.
        with patch("json.loads", side_effect=RecursionError):
            ok, status, message = h._validate_axe_structure("[]")
        self.assertFalse(ok)
        self.assertEqual(status, 400)
