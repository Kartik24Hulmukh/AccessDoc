"""The verifier must work with the AccessDoc source tree absent.

This is the single assertion that encodes the product claim: a bundle is
verifiable without trusting the tool or its author. If scripts/verify_bundle.py
ever imports app.bundle again, this test fails - which is the point.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.bundle import build_bundle
from app.service import build_artifacts

SAMPLE_BODY = {
    "scanner_input": json.dumps({
        "url": "https://example.com",
        "testEngine": {"name": "axe-core", "version": "4.11.2"},
        "violations": [{
            "id": "image-alt",
            "impact": "critical",
            "description": "Images must have alternate text",
            "helpUrl": "https://dequeuniversity.com/rules/axe/4.11/image-alt",
            "nodes": [{"html": "<img>", "target": ["img"]}],
        }],
        "passes": [], "incomplete": [],
    }),
    "client_name": "Independence Client",
    "audit_date": "2026-08-28",
}


class TestVerifierIndependence(unittest.TestCase):
    def test_verifier_runs_with_no_accessdoc_source_present(self):
        data = build_bundle(build_artifacts(SAMPLE_BODY))
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            shutil.copy(ROOT / "scripts" / "verify_bundle.py", tmp / "verify_bundle.py")
            (tmp / "bundle.zip").write_bytes(data)
            self.assertFalse((tmp / "app").exists())
            proc = subprocess.run(
                [sys.executable, "verify_bundle.py", "bundle.zip", "--json"],
                capture_output=True, text=True, cwd=str(tmp),
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(json.loads(proc.stdout)["status"], "PASS")

    def test_verifier_does_not_import_app(self):
        src = (ROOT / "scripts" / "verify_bundle.py").read_text(encoding="utf-8")
        self.assertNotIn("from app", src)
        self.assertNotIn("import app", src)

    def test_tampered_member_fails_with_integrity_code(self):
        import zipfile
        data = build_bundle(build_artifacts(SAMPLE_BODY))
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            shutil.copy(ROOT / "scripts" / "verify_bundle.py", tmp / "verify_bundle.py")
            src, dst = tmp / "ok.zip", tmp / "bad.zip"
            src.write_bytes(data)
            with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
                for info in zin.infolist():
                    blob = zin.read(info.filename)
                    if info.filename == "report.html":
                        blob = blob.replace(b"<html", b"<HTML", 1)
                    zout.writestr(info, blob)
            proc = subprocess.run(
                [sys.executable, "verify_bundle.py", "bad.zip"],
                capture_output=True, text=True, cwd=str(tmp),
            )
            self.assertEqual(proc.returncode, 20, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
