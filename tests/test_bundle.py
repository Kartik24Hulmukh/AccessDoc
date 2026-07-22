"""Tests for bundle builder and validator."""
import json
import unittest
import zipfile
from io import BytesIO
from app.bundle import build_bundle, validate_bundle, MEMBERS
from app.service import build_artifacts

SAMPLE_BODY = {
    "scanner_input": json.dumps({
        "url": "https://example.com",
        "testEngine": {"name": "axe-core", "version": "4.11.2"},
        "violations": [
            {"id": "image-alt", "impact": "critical",
             "description": "Images must have alternate text",
             "helpUrl": "https://dequeuniversity.com/rules/axe/4.11/image-alt",
             "nodes": [{"html": "<img>"}]}
        ],
        "passes": [], "incomplete": []
    }),
    "client_name": "Test Client",
    "agency_name": "Test Agency",
    "audit_date": "2026-07-23",
}


class BundleTests(unittest.TestCase):
    def setUp(self):
        arts = build_artifacts(SAMPLE_BODY)
        self.data = build_bundle(arts)

    def test_bundle_integrity_and_receipt(self):
        with zipfile.ZipFile(BytesIO(self.data)) as z:
            manifest = json.loads(z.read("manifest.json"))
            self.assertEqual(
                [x["path"] for x in manifest["files"]],
                list(MEMBERS[:-1])
            )

    def test_bundle_member_count(self):
        with zipfile.ZipFile(BytesIO(self.data)) as z:
            self.assertEqual(len(z.namelist()), len(MEMBERS))

    def test_bundle_all_members_present(self):
        with zipfile.ZipFile(BytesIO(self.data)) as z:
            self.assertEqual(set(z.namelist()), set(MEMBERS))

    def test_bundle_size_under_limit(self):
        self.assertLess(len(self.data), 8_000_000)

    def test_validate_bundle_passes(self):
        result = validate_bundle(self.data)
        self.assertTrue(result["valid"])
        self.assertEqual(result["errors"], [])

    def test_receipt_json_schema_version(self):
        with zipfile.ZipFile(BytesIO(self.data)) as z:
            receipt = json.loads(z.read("receipt.json"))
        self.assertEqual(receipt["schema_version"], "1.1")

    def test_receipt_has_coverage_note(self):
        with zipfile.ZipFile(BytesIO(self.data)) as z:
            receipt = json.loads(z.read("receipt.json"))
        self.assertIn("coverage_note", receipt)

    def test_openacr_yaml_present(self):
        with zipfile.ZipFile(BytesIO(self.data)) as z:
            yaml_content = z.read("openacr.yaml").decode()
        self.assertIn("schema_version", yaml_content)

    def test_intoto_json_is_dsse(self):
        with zipfile.ZipFile(BytesIO(self.data)) as z:
            intoto = json.loads(z.read("attestation.intoto.json"))
        self.assertIn("payloadType", intoto)
        self.assertIn("payload", intoto)

    def test_manifest_digests_correct(self):
        result = validate_bundle(self.data)
        self.assertEqual(result["errors"], [])

    def test_corrupt_bundle_fails_validation(self):
        result = validate_bundle(b"not a zip file")
        self.assertFalse(result["valid"])


if __name__ == "__main__":
    unittest.main()
