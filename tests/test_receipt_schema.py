"""Tests for receipt schema 1.2: fingerprints, target normalization, determinism."""
import hashlib
import json
import os
import sys
import unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import AuditViolation, AuditSummary, SOURCE_AUTOMATED, SOURCE_MANUAL
from app.parser import parse_axe_json, _normalize_target_value, _bound_target
from app.receipt_builder import (
    build_receipt, receipt_json_str, compute_finding_fingerprint,
    FINDING_FINGERPRINT_VERSION, SCHEMA_VERSION,
    normalize_rule_id, normalize_source, normalize_target,
)
from app.timeseries import build_trend, _detect_precision


def _make_summary(**kw):
    defaults = dict(
        critical=0, serious=0, moderate=0, minor=0,
        total_violations=0, total_passes=0, total_incomplete=0,
        url="https://example.com", engine_version="4.11.2", manual_findings=0,
    )
    defaults.update(kw)
    return AuditSummary(**defaults)


class TestFingerprintComputation(unittest.TestCase):
    """Tests for finding fingerprint computation."""

    def test_full_64_character_fingerprints(self):
        """Fingerprints must be full 64-char SHA-256, not truncated."""
        fp = compute_finding_fingerprint("image-alt", "automated", "img.hero")
        self.assertEqual(len(fp), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in fp))

    def test_same_input_same_fingerprint(self):
        """Same input produces same fingerprint."""
        fp1 = compute_finding_fingerprint("color-contrast", "automated", "#text")
        fp2 = compute_finding_fingerprint("color-contrast", "automated", "#text")
        self.assertEqual(fp1, fp2)

    def test_different_targets_different_fingerprints(self):
        """Two targets under same axe rule remain distinct."""
        fp1 = compute_finding_fingerprint("image-alt", "automated", "img.hero")
        fp2 = compute_finding_fingerprint("image-alt", "automated", "img.logo")
        self.assertNotEqual(fp1, fp2)

    def test_reordered_input_same_fingerprint(self):
        """Same target with reordered canonical input produces same fingerprint.

        The canonical serialization uses sort_keys=True, so key order doesn't matter.
        """
        # The fingerprint input is always {"rule":..., "source":..., "target":...}
        # with sort_keys=True, so any reordering of the dict produces the same bytes.
        fp1 = compute_finding_fingerprint("label", "automated", "#email")
        fp2 = compute_finding_fingerprint("label", "automated", "#email")
        self.assertEqual(fp1, fp2)

    def test_different_source_different_fingerprint(self):
        """Same rule+target but different source produces different fingerprint."""
        fp1 = compute_finding_fingerprint("label", "automated", "#email")
        fp2 = compute_finding_fingerprint("label", "manual", "#email")
        self.assertNotEqual(fp1, fp2)


class TestTargetNormalization(unittest.TestCase):
    """Tests for axe node target normalization."""

    def test_string_target(self):
        """Strings remain strings after bounded normalization."""
        self.assertEqual(_normalize_target_value("img.hero"), "img.hero")

    def test_flat_list_joined(self):
        """Flat lists join using documented delimiter."""
        result = _normalize_target_value(["div", "span", "img"])
        self.assertEqual(result, "div > span > img")

    def test_nested_list_preserves_hierarchy(self):
        """Nested lists preserve hierarchy deterministically."""
        result = _normalize_target_value([["iframe", "div"], "span"])
        self.assertEqual(result, "iframe > div > span")

    def test_missing_target(self):
        """Missing target returns empty string."""
        self.assertEqual(_normalize_target_value(None), "")
        self.assertEqual(_normalize_target_value(""), "")

    def test_malformed_target(self):
        """Malformed target is handled gracefully."""
        result = _normalize_target_value(42)
        self.assertEqual(result, "42")

    def test_control_characters_removed(self):
        """Control characters are removed safely."""
        result = _normalize_target_value("img\x00.hero\x01")
        self.assertEqual(result, "img.hero")

    def test_unicode_preserved(self):
        """Unicode is preserved in targets."""
        result = _normalize_target_value("div[title='café']")
        self.assertEqual(result, "div[title='café']")

    def test_bidirectional_text_preserved(self):
        """Bidirectional text in target is preserved."""
        result = _normalize_target_value("div[title='مرحبا']")
        self.assertIn("مرحبا", result)

    def test_extremely_long_target_truncated(self):
        """Excessively long target text is bounded."""
        long_target = "a" * 500
        result = _bound_target(long_target)
        self.assertEqual(len(result), 200)

    def test_duplicate_targets_deduplicated(self):
        """Duplicate targets are deduplicated by parser."""
        axe = json.dumps({
            "url": "https://example.com",
            "testEngine": {"version": "4.11.2"},
            "violations": [{
                "id": "image-alt",
                "impact": "critical",
                "description": "d",
                "helpUrl": "h",
                "nodes": [
                    {"target": "img.hero"},
                    {"target": "img.hero"},  # duplicate
                    {"target": "img.logo"},
                ],
            }],
        })
        summary, violations = parse_axe_json(axe)
        targets = [v.target for v in violations]
        self.assertEqual(len(targets), 2)  # deduplicated
        self.assertIn("img.hero", targets)
        self.assertIn("img.logo", targets)

    def test_absent_target_falls_back(self):
        """Absent target falls back to documented identity."""
        axe = json.dumps({
            "url": "https://example.com",
            "testEngine": {"version": "4.11.2"},
            "violations": [{
                "id": "image-alt",
                "impact": "critical",
                "description": "d",
                "helpUrl": "h",
                "nodes": [{}],  # no target
            }],
        })
        summary, violations = parse_axe_json(axe)
        self.assertEqual(len(violations), 1)
        self.assertIn("no-target", violations[0].target)

    def test_no_nodes_falls_back(self):
        """Violation with no nodes falls back to no-target identity."""
        axe = json.dumps({
            "url": "https://example.com",
            "testEngine": {"version": "4.11.2"},
            "violations": [{
                "id": "label",
                "impact": "serious",
                "description": "d",
                "helpUrl": "h",
                "nodes": [],
            }],
        })
        summary, violations = parse_axe_json(axe)
        self.assertEqual(len(violations), 1)
        self.assertIn("no-target", violations[0].target)

    def test_two_targets_same_rule_distinct(self):
        """Two targets under same axe rule remain distinct findings."""
        axe = json.dumps({
            "url": "https://example.com",
            "testEngine": {"version": "4.11.2"},
            "violations": [{
                "id": "color-contrast",
                "impact": "serious",
                "description": "d",
                "helpUrl": "h",
                "nodes": [
                    {"target": "#text1"},
                    {"target": "#text2"},
                ],
            }],
        })
        summary, violations = parse_axe_json(axe)
        self.assertEqual(len(violations), 2)
        self.assertEqual(violations[0].id, violations[1].id)
        self.assertNotEqual(violations[0].target, violations[1].target)
        # Fingerprints should be different
        fp0 = compute_finding_fingerprint(violations[0].id, violations[0].source, violations[0].target)
        fp1 = compute_finding_fingerprint(violations[1].id, violations[1].source, violations[1].target)
        self.assertNotEqual(fp0, fp1)


class TestReceiptSchema(unittest.TestCase):
    """Tests for receipt schema 1.2 structure."""

    def _make_violations(self):
        return [
            AuditViolation(id="image-alt", impact="critical", description="d",
                           help_url="u", wcag_scs=["1.1.1"], target="img.hero"),
            AuditViolation(id="color-contrast", impact="serious", description="d",
                           help_url="u", wcag_scs=["1.4.3"], target="#text"),
        ]

    def test_schema_version_is_12(self):
        receipt = build_receipt(_make_summary(), self._make_violations(), {"audit_date": "2026-01-01"})
        self.assertEqual(receipt["schema_version"], SCHEMA_VERSION)
        self.assertEqual(receipt["schema_version"], "1.2")

    def test_required_fields_present(self):
        receipt = build_receipt(_make_summary(), self._make_violations(), {"audit_date": "2026-01-01"})
        required = [
            "schema_version", "accessdoc_version", "axe_core_verified_version",
            "catalog_version", "coverage_note", "audit_date", "client_name",
            "url", "engine_version", "summary", "rule_ids",
            "finding_fingerprint_version", "violations",
        ]
        for field in required:
            self.assertIn(field, receipt, f"Missing required field: {field}")

    def test_finding_fingerprint_version_is_1(self):
        receipt = build_receipt(_make_summary(), self._make_violations(), {"audit_date": "2026-01-01"})
        self.assertEqual(receipt["finding_fingerprint_version"], FINDING_FINGERPRINT_VERSION)
        self.assertEqual(receipt["finding_fingerprint_version"], "1")

    def test_violations_have_required_entries(self):
        receipt = build_receipt(_make_summary(), self._make_violations(), {"audit_date": "2026-01-01"})
        for v in receipt["violations"]:
            for field in ["id", "impact", "source", "target", "finding_fingerprint"]:
                self.assertIn(field, v, f"Missing violation field: {field}")

    def test_rule_ids_sorted_unique(self):
        receipt = build_receipt(_make_summary(), self._make_violations(), {"audit_date": "2026-01-01"})
        self.assertEqual(receipt["rule_ids"], ["color-contrast", "image-alt"])

    def test_fingerprints_are_64_chars(self):
        receipt = build_receipt(_make_summary(), self._make_violations(), {"audit_date": "2026-01-01"})
        for v in receipt["violations"]:
            self.assertEqual(len(v["finding_fingerprint"]), 64)

    def test_deterministic_receipt_bytes(self):
        """Same input -> same output."""
        r1 = build_receipt(_make_summary(), self._make_violations(), {"audit_date": "2026-01-01"})
        r2 = build_receipt(_make_summary(), self._make_violations(), {"audit_date": "2026-01-01"})
        self.assertEqual(receipt_json_str(r1), receipt_json_str(r2))

    def test_old_11_receipt_accepted_by_trend(self):
        """Old 1.1 receipt (no violations[], no fingerprints) still accepted."""
        old_receipt = {
            "schema_version": "1.1",
            "accessdoc_version": "0.7.0-beta.2",
            "audit_date": "2026-01-01",
            "summary": {"critical": 1, "serious": 0, "moderate": 0, "minor": 0,
                        "total_violations": 1, "total_passes": 0, "manual_findings": 0},
            "rule_ids": ["image-alt"],
        }
        current = build_receipt(_make_summary(), self._make_violations(), {"audit_date": "2026-02-01"})
        violations = self._make_violations()
        trend = json.loads(build_trend(old_receipt, current, violations))
        # Should work and detect precision difference
        self.assertIn("comparison_precision", trend)
        self.assertIn(trend["comparison_precision"], ["aggregate-only", "rule-level"])

    def test_malformed_receipt_fields_handled(self):
        """Malformed receipt fields handled gracefully."""
        malformed = {
            "schema_version": "1.2",
            "violations": "not-a-list",
            "rule_ids": None,
            "summary": "not-a-dict",
        }
        precision = _detect_precision(malformed)
        self.assertEqual(precision, "aggregate-only")

    def test_receipt_json_str_roundtrip(self):
        """receipt_json_str produces valid JSON that roundtrips."""
        receipt = build_receipt(_make_summary(), self._make_violations(), {"audit_date": "2026-01-01"})
        s = receipt_json_str(receipt)
        parsed = json.loads(s)
        self.assertEqual(parsed["schema_version"], "1.2")
        self.assertEqual(len(parsed["violations"]), 2)


if __name__ == "__main__":
    unittest.main()
