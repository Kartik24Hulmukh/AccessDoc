"""Hostile-fixture tests for scripts/verify_bundle.py per 03-VERIFY-PRIMITIVE.md.

Eight hostile fixtures assert exact distinct exit codes:
  - tampered_member.zip          -> exit code 20 (INTEGRITY)
  - manifest_digest_mismatch.zip  -> exit code 20 (INTEGRITY)
  - extra_member.zip              -> exit code 10 (STRUCTURE)
  - missing_member.zip            -> exit code 10 (STRUCTURE)
  - not_a_pdf.zip                 -> exit code 30 (CONTENT)
  - oversize.zip                  -> exit code 10 (STRUCTURE)
  - corrupt_zip.zip               -> exit code 10 (STRUCTURE)
  - resealed_manifest.zip         -> exit code 64 (USAGE / SIGNATURE REQUIRED)
"""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "hostile"
VERIFIER = ROOT / "scripts" / "verify_bundle.py"


class TestHostileFixtures(unittest.TestCase):
    def test_tampered_member_exits_20(self):
        proc = subprocess.run([sys.executable, str(VERIFIER), str(FIXTURE_DIR / "tampered_member.zip")], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 20, proc.stdout + proc.stderr)

    def test_manifest_digest_mismatch_exits_20(self):
        proc = subprocess.run([sys.executable, str(VERIFIER), str(FIXTURE_DIR / "manifest_digest_mismatch.zip")], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 20, proc.stdout + proc.stderr)

    def test_extra_member_exits_10(self):
        proc = subprocess.run([sys.executable, str(VERIFIER), str(FIXTURE_DIR / "extra_member.zip")], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 10, proc.stdout + proc.stderr)

    def test_missing_member_exits_10(self):
        proc = subprocess.run([sys.executable, str(VERIFIER), str(FIXTURE_DIR / "missing_member.zip")], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 10, proc.stdout + proc.stderr)

    def test_not_a_pdf_exits_30(self):
        proc = subprocess.run([sys.executable, str(VERIFIER), str(FIXTURE_DIR / "not_a_pdf.zip")], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 30, proc.stdout + proc.stderr)

    def test_oversize_exits_10(self):
        proc = subprocess.run([sys.executable, str(VERIFIER), str(FIXTURE_DIR / "oversize.zip")], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 10, proc.stdout + proc.stderr)

    def test_corrupt_zip_exits_10(self):
        proc = subprocess.run([sys.executable, str(VERIFIER), str(FIXTURE_DIR / "corrupt_zip.zip")], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 10, proc.stdout + proc.stderr)

    def test_resealed_manifest_exits_64(self):
        proc = subprocess.run([sys.executable, str(VERIFIER), str(FIXTURE_DIR / "resealed_manifest.zip")], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 64, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
