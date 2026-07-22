"""Tests for build_artifacts orchestration layer."""
import json
import unittest
from app.service import build_artifacts, Artifacts

SAMPLE_BODY = {
    "scanner_input": json.dumps({
        "url": "https://example.com",
        "testEngine": {"name": "axe-core", "version": "4.11.2"},
        "violations": [
            {"id": "image-alt", "impact": "critical",
             "description": "Images must have alternate text",
             "helpUrl": "https://dequeuniversity.com",
             "nodes": [{"html": "<img>"}]}
        ],
        "passes": [], "incomplete": []
    }),
    "client_name": "ACME",
    "agency_name": "Audit Co",
    "audit_date": "2026-07-23",
}


class TestBuildArtifacts(unittest.TestCase):
    def setUp(self):
        self.arts = build_artifacts(SAMPLE_BODY)

    def test_returns_artifacts(self):
        self.assertIsInstance(self.arts, Artifacts)

    def test_pdf_is_bytes(self):
        self.assertIsInstance(self.arts.pdf_bytes, bytes)

    def test_pdf_is_pdf(self):
        self.assertTrue(self.arts.pdf_bytes.startswith(b"%PDF"))

    def test_html_is_bytes(self):
        self.assertIsInstance(self.arts.html_bytes, bytes)

    def test_html_contains_doctype(self):
        self.assertIn(b"<!DOCTYPE html", self.arts.html_bytes)

    def test_receipt_json_parseable(self):
        receipt = json.loads(self.arts.receipt_json)
        self.assertIn("schema_version", receipt)

    def test_receipt_schema_version_11(self):
        receipt = json.loads(self.arts.receipt_json)
        self.assertEqual(receipt["schema_version"], "1.1")

    def test_receipt_has_axe_version(self):
        receipt = json.loads(self.arts.receipt_json)
        self.assertIn("axe_core_verified_version", receipt)

    def test_receipt_has_coverage_note(self):
        receipt = json.loads(self.arts.receipt_json)
        self.assertIn("coverage_note", receipt)

    def test_openacr_yaml_is_str(self):
        self.assertIsInstance(self.arts.openacr_yaml, str)

    def test_openacr_yaml_starts_with_dashes(self):
        self.assertTrue(self.arts.openacr_yaml.startswith("---"))

    def test_intoto_bytes_is_bytes(self):
        self.assertIsInstance(self.arts.intoto_bytes, bytes)

    def test_intoto_bytes_parseable(self):
        parsed = json.loads(self.arts.intoto_bytes)
        self.assertIn("payloadType", parsed)

    def test_default_client_name(self):
        arts = build_artifacts({"scanner_input": "{}"})
        receipt = json.loads(arts.receipt_json)
        self.assertEqual(receipt["client_name"], "Client")


if __name__ == "__main__":
    unittest.main()
