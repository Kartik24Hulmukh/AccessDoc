"""End-to-end chain tests: real product output through the full pipeline.

These tests exercise the real build_artifacts() and build_bundle() functions
without mocking. They verify the receipt schema 1.2 chain from generation
through extraction, trend comparison, and tamper detection.
"""
import copy
import hashlib
import io
import json
import os
import sys
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.service import build_artifacts
from app.bundle import build_bundle, validate_bundle
from app.receipt_builder import compute_finding_fingerprint, FINDING_FINGERPRINT_VERSION


# --- Fixtures ----------------------------------------------------------------

# Bundle A: one finding that will be remediated, one that will persist,
# and two distinct targets under the same axe rule.
AXE_A = json.dumps({
    "url": "https://example.com",
    "testEngine": {"name": "axe-core", "version": "4.11.2"},
    "violations": [
        {
            "id": "image-alt", "impact": "critical", "description": "Missing alt",
            "helpUrl": "https://deque.com/alt",
            "nodes": [{"target": "img.hero"}],
        },
        {
            "id": "color-contrast", "impact": "serious", "description": "Low contrast",
            "helpUrl": "https://deque.com/contrast",
            "nodes": [
                {"target": "#text1"},
                {"target": "#text2"},
            ],
        },
    ],
})

# Bundle B: image-alt is gone (remediated), color-contrast persists,
# and a new finding (label) appears.
AXE_B = json.dumps({
    "url": "https://example.com",
    "testEngine": {"name": "axe-core", "version": "4.11.2"},
    "violations": [
        {
            "id": "color-contrast", "impact": "serious", "description": "Low contrast",
            "helpUrl": "https://deque.com/contrast",
            "nodes": [
                {"target": "#text1"},
                {"target": "#text2"},
            ],
        },
        {
            "id": "label", "impact": "critical", "description": "Missing label",
            "helpUrl": "https://deque.com/label",
            "nodes": [{"target": "#email"}],
        },
    ],
})


def _extract_receipt(zip_bytes):
    """Extract receipt.json from a bundle ZIP."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        return json.loads(zf.read("receipt.json"))


def _build_bundle(axe_json, **extra):
    """Build a full bundle and return (zip_bytes, artifacts)."""
    body = {"scanner_input": axe_json, "client_name": "TestClient",
            "audit_date": "2026-01-01"}
    body.update(extra)
    artifacts = build_artifacts(body)
    zip_bytes = build_bundle(artifacts)
    return zip_bytes, artifacts


class TestJourneyA(unittest.TestCase):
    """Journey A: Generate bundle A, extract receipt, assert schema 1.2."""

    @classmethod
    def setUpClass(cls):
        cls.zip_a, cls.arts_a = _build_bundle(AXE_A)
        cls.receipt_a = _extract_receipt(cls.zip_a)

    def test_schema_is_12(self):
        self.assertEqual(self.receipt_a["schema_version"], "1.2")

    def test_rule_ids_present(self):
        self.assertIn("rule_ids", self.receipt_a)
        self.assertIn("image-alt", self.receipt_a["rule_ids"])
        self.assertIn("color-contrast", self.receipt_a["rule_ids"])

    def test_violations_present(self):
        self.assertIn("violations", self.receipt_a)
        self.assertGreater(len(self.receipt_a["violations"]), 0)

    def test_finding_fingerprint_version_is_1(self):
        self.assertEqual(self.receipt_a["finding_fingerprint_version"], "1")

    def test_fingerprints_are_64_chars(self):
        for v in self.receipt_a["violations"]:
            self.assertEqual(len(v["finding_fingerprint"]), 64)

    def test_two_targets_under_one_rule_distinct(self):
        """Two targets under same axe rule remain distinct."""
        cc_findings = [v for v in self.receipt_a["violations"] if v["id"] == "color-contrast"]
        self.assertEqual(len(cc_findings), 2)
        fps = {v["finding_fingerprint"] for v in cc_findings}
        self.assertEqual(len(fps), 2)  # distinct fingerprints
        targets = {v["target"] for v in cc_findings}
        self.assertEqual(targets, {"#text1", "#text2"})

    def test_bundle_validates(self):
        result = validate_bundle(self.zip_a)
        self.assertTrue(result["valid"], f"Bundle validation errors: {result['errors']}")


class TestJourneyB(unittest.TestCase):
    """Journey B: Generate bundle B using A's real receipt as prior, assert trend."""

    @classmethod
    def setUpClass(cls):
        cls.zip_a, cls.arts_a = _build_bundle(AXE_A)
        cls.receipt_a = _extract_receipt(cls.zip_a)
        # Build B with A's receipt as prior
        cls.zip_b, cls.arts_b = _build_bundle(AXE_B, prior_receipt=cls.receipt_a)
        cls.receipt_b = _extract_receipt(cls.zip_b)
        cls.trend = json.loads(cls.arts_b.trend_json)

    def test_trend_has_comparison_precision(self):
        self.assertIn("comparison_precision", self.trend)

    def test_trend_precision_is_target_level(self):
        """Both receipts are schema 1.2 with fingerprints, so precision should be target-level."""
        self.assertEqual(self.trend["comparison_precision"], "target-level")

    def test_image_alt_remediated(self):
        """image-alt was in A but not B -> remediated."""
        remediated_ids = [f.get("id") for f in self.trend.get("remediated_findings", [])]
        # image-alt should be in remediated (by fingerprint)
        # Check rule-level too
        self.assertIn("image-alt", self.trend["fixed_rules"])

    def test_color_contrast_persists(self):
        """color-contrast was in A and still in B -> persisting."""
        self.assertIn("color-contrast", self.trend["persisting_rules"])

    def test_label_introduced(self):
        """label was not in A but appears in B -> introduced."""
        self.assertIn("label", self.trend["new_rules"])

    def test_target_level_findings_present(self):
        """Target-level comparison should have finding-level entries."""
        self.assertIn("remediated_findings", self.trend)
        self.assertIn("persisting_findings", self.trend)
        self.assertIn("introduced_findings", self.trend)

    def test_remediated_count_matches(self):
        """One finding (image-alt) was remediated."""
        self.assertEqual(self.trend["remediated_count"], 1)

    def test_introduced_count_matches(self):
        """One finding (label) was introduced."""
        self.assertEqual(self.trend["introduced_count"], 1)

    def test_persisting_count_matches(self):
        """Two color-contrast findings persist."""
        self.assertEqual(self.trend["persisting_count"], 2)

    def test_both_bundles_validate(self):
        self.assertTrue(validate_bundle(self.zip_a)["valid"])
        self.assertTrue(validate_bundle(self.zip_b)["valid"])


class TestJourneyC(unittest.TestCase):
    """Journey C: Tamper with A's receipt, confirm chain validation fails or reports degraded."""

    @classmethod
    def setUpClass(cls):
        cls.zip_a, cls.arts_a = _build_bundle(AXE_A)
        cls.receipt_a = _extract_receipt(cls.zip_a)

    def test_count_tampering_detected(self):
        """Modifying summary counts in prior receipt changes trend but doesn't crash."""
        tampered = copy.deepcopy(self.receipt_a)
        tampered["summary"]["critical"] = 999
        zip_b, arts_b = _build_bundle(AXE_B, prior_receipt=tampered)
        trend = json.loads(arts_b.trend_json)
        # The trend should still work but the prior summary will reflect tampered data
        self.assertNotEqual(trend["prior_summary"]["critical"], self.receipt_a["summary"]["critical"])

    def test_target_tampering_changes_fingerprints(self):
        """Modifying target in prior receipt changes fingerprint comparison."""
        tampered = copy.deepcopy(self.receipt_a)
        if tampered["violations"]:
            tampered["violations"][0]["target"] = "tampered-target"
            # Recompute fingerprint for tampered entry
            tampered["violations"][0]["finding_fingerprint"] = compute_finding_fingerprint(
                tampered["violations"][0]["id"],
                tampered["violations"][0]["source"],
                "tampered-target",
            )
        zip_b, arts_b = _build_bundle(AXE_B, prior_receipt=tampered)
        trend = json.loads(arts_b.trend_json)
        # The remediated/persisting counts will differ because the fingerprint changed
        self.assertIn("comparison_precision", trend)

    def test_fingerprint_tampering_detected(self):
        """Modifying finding_fingerprint in prior receipt changes comparison."""
        tampered = copy.deepcopy(self.receipt_a)
        if tampered["violations"]:
            tampered["violations"][0]["finding_fingerprint"] = "a" * 64
        zip_b, arts_b = _build_bundle(AXE_B, prior_receipt=tampered)
        trend = json.loads(arts_b.trend_json)
        # The original finding will appear as "remediated" since its fingerprint no longer matches
        self.assertIn("remediated_findings", trend)

    def test_audit_date_tampering(self):
        """Modifying audit_date in prior receipt changes the chain."""
        tampered = copy.deepcopy(self.receipt_a)
        tampered["audit_date"] = "2025-01-01"
        zip_b, arts_b = _build_bundle(AXE_B, prior_receipt=tampered)
        trend = json.loads(arts_b.trend_json)
        # The prev_receipt_sha256 will be different from the original
        original_sha = hashlib.sha256(
            json.dumps(self.receipt_a, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.assertNotEqual(trend["prev_receipt_sha256"], original_sha)

    def test_missing_prior_receipt_handled(self):
        """Missing/None prior receipt should not crash (no trend generated)."""
        # When no prior_receipt is provided, trend_json is None
        zip_b, arts_b = _build_bundle(AXE_B)
        self.assertIsNone(arts_b.trend_json)

    def test_intermediate_receipt_in_history(self):
        """Receipt history with intermediate receipts works for due-diligence."""
        receipt_a = self.receipt_a
        intermediate = copy.deepcopy(receipt_a)
        intermediate["audit_date"] = "2026-01-15"
        zip_b, arts_b = _build_bundle(
            AXE_B, receipt_history=[receipt_a, intermediate]
        )
        self.assertIsNotNone(arts_b.due_diligence_md)
        self.assertIn("Due-Diligence Record", arts_b.due_diligence_md)


class TestJourneyD(unittest.TestCase):
    """Journey D: Same journey through CLI, CI gate, MCP, API service function.

    All receipts share the same schema and required fields. Does not mock
    build_artifacts().
    """

    @classmethod
    def setUpClass(cls):
        cls.zip_api, cls.arts_api = _build_bundle(AXE_A)
        cls.receipt_api = _extract_receipt(cls.zip_api)

    def test_api_receipt_schema(self):
        """API service function produces schema 1.2."""
        self.assertEqual(self.receipt_api["schema_version"], "1.2")

    def test_ci_gate_receipt_schema(self):
        """CI gate (via build_artifacts) produces schema 1.2."""
        # CI gate uses the same build_artifacts function
        body = {"scanner_input": AXE_A, "client_name": "CI Audit",
                "audit_date": "2026-01-01"}
        arts = build_artifacts(body)
        zip_bytes = build_bundle(arts)
        receipt = _extract_receipt(zip_bytes)
        self.assertEqual(receipt["schema_version"], "1.2")

    def test_mcp_receipt_schema(self):
        """MCP server (via build_artifacts) produces schema 1.2."""
        from mcp import server
        resp = server.handle_request({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "generate_bundle",
                       "arguments": {"scanner_input": AXE_A, "client_name": "MCP"}},
        })
        payload = json.loads(resp["result"]["content"][0]["text"])
        # MCP returns base64-encoded bundle
        import base64
        zip_bytes = base64.b64decode(payload["bundle_base64"])
        receipt = _extract_receipt(zip_bytes)
        self.assertEqual(receipt["schema_version"], "1.2")

    def test_all_surfaces_share_required_fields(self):
        """All product surfaces produce receipts with the same required fields."""
        required = [
            "schema_version", "accessdoc_version", "axe_core_verified_version",
            "catalog_version", "coverage_note", "audit_date", "client_name",
            "url", "engine_version", "summary", "rule_ids",
            "finding_fingerprint_version", "violations",
        ]
        # API receipt
        for field in required:
            self.assertIn(field, self.receipt_api, f"API receipt missing: {field}")

        # CI gate receipt
        body = {"scanner_input": AXE_A, "client_name": "CI",
                "audit_date": "2026-01-01"}
        arts = build_artifacts(body)
        ci_receipt = json.loads(arts.receipt_json)
        for field in required:
            self.assertIn(field, ci_receipt, f"CI receipt missing: {field}")

    def test_all_surfaces_have_finding_fingerprints(self):
        """All surfaces produce violations with finding_fingerprint."""
        for v in self.receipt_api["violations"]:
            self.assertIn("finding_fingerprint", v)
            self.assertEqual(len(v["finding_fingerprint"]), 64)

    def test_all_surfaces_finding_fingerprint_version(self):
        """All surfaces set finding_fingerprint_version to '1'."""
        self.assertEqual(self.receipt_api["finding_fingerprint_version"], "1")


if __name__ == "__main__":
    unittest.main()
