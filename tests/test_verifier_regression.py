import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.bundle import build_bundle
from app.service import build_artifacts
from scripts.verify_bundle import verify


class TestVerifierRegression(unittest.TestCase):
    """Regression test for shipped offline verifier (scripts/verify_bundle.py).

    Defect: The old verifier hardcoded 4 members ('report.pdf', 'report.html',
    'receipt.json', 'manifest.json') and rejected real 6-member bundles
    (which also include 'openacr.yaml' and 'attestation.intoto.json').
    """

    def setUp(self):
        sample_path = Path(__file__).parent.parent / "fixtures" / "axe-sample.json"
        body = {
            "scanner_input": sample_path.read_text(encoding="utf-8"),
            "client_name": "Regression Test Client",
            "audit_date": "2026-07-23",
        }
        self.artifacts = build_artifacts(body)
        self.bundle_bytes = build_bundle(self.artifacts)

    def test_old_verifier_fails_on_real_bundle(self):
        """Prove the defect: the old verifier algorithm rejects a real valid bundle."""
        old_expected = ["report.pdf", "report.html", "receipt.json", "manifest.json"]
        with zipfile.ZipFile(io.BytesIO(self.bundle_bytes)) as z:
            real_members = z.namelist()
            # Real bundle must have 6 members
            self.assertEqual(
                real_members,
                [
                    "report.pdf",
                    "report.html",
                    "receipt.json",
                    "openacr.yaml",
                    "attestation.intoto.json",
                    "manifest.json",
                ],
            )
            # Old verifier assertion MUST fail
            with self.assertRaises(AssertionError):
                assert real_members == old_expected

    def test_new_verifier_passes_on_real_bundle(self):
        """The new shipped verifier must accept a real valid bundle."""
        with tempfile.TemporaryDirectory() as td:
            bundle_path = Path(td) / "bundle.zip"
            bundle_path.write_bytes(self.bundle_bytes)
            checks = verify(bundle_path)
            self.assertIn("structure", checks)
            self.assertEqual(checks["integrity"], "PASS")

    def test_new_verifier_rejects_tampered_bundle(self):
        """The new shipped verifier must reject a tampered bundle with non-zero exit code."""
        with zipfile.ZipFile(io.BytesIO(self.bundle_bytes)) as z:
            members = {name: z.read(name) for name in z.namelist()}

        # Tamper report.html
        members["report.html"] = members["report.html"] + b"<!-- tampered -->"

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in members.items():
                z.writestr(name, data)

        with tempfile.TemporaryDirectory() as td:
            tampered_path = Path(td) / "tampered.zip"
            tampered_path.write_bytes(buf.getvalue())
            from scripts.verify_bundle import Fail
            with self.assertRaises(Fail) as ctx:
                verify(tampered_path)
            self.assertEqual(ctx.exception.code, 20)


if __name__ == "__main__":
    unittest.main()
