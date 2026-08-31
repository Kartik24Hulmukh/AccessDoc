"""End-to-end CLI tests."""
import json
import io
import os
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cli


AXE = json.dumps({
    "url": "https://example.com",
    "testEngine": {"name": "axe-core", "version": "4.11.2"},
    "violations": [
        {"id": "image-alt", "impact": "critical", "description": "alt",
         "helpUrl": "h", "nodes": [{}], "tags": ["wcag2a", "wcag111"]},
        {"id": "color-contrast", "impact": "serious", "description": "c",
         "helpUrl": "h", "nodes": [{}, {}], "tags": ["wcag2aa", "wcag143"]},
    ],
})


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.axe = os.path.join(self.tmp, "axe.json")
        with open(self.axe, "w") as f:
            f.write(AXE)

    def test_full_bundle_has_all_optional_members(self):
        out = os.path.join(self.tmp, "b.zip")
        rc = cli.main(["bundle", self.axe, "--out", out,
                       "--sarif", "--vpat", "--eaa", "--enrich"])
        self.assertEqual(rc, 0)
        with zipfile.ZipFile(out) as z:
            names = set(z.namelist())
        for member in ("report.pdf", "report.html", "receipt.json", "openacr.yaml",
                       "attestation.intoto.json", "manifest.json",
                       "findings.sarif.json", "vpat-draft.html", "eaa-evidence.md"):
            self.assertIn(member, names)

    def test_default_bundle_has_six_members(self):
        out = os.path.join(self.tmp, "d.zip")
        cli.main(["bundle", self.axe, "--out", out])
        with zipfile.ZipFile(out) as z:
            self.assertEqual(len(z.namelist()), 6)

    def test_verify_detects_tamper(self):
        out = os.path.join(self.tmp, "v.zip")
        cli.main(["bundle", self.axe, "--out", out])
        with zipfile.ZipFile(out) as z:
            items = {n: z.read(n) for n in z.namelist()}
        items["report.html"] = b"tampered"
        with zipfile.ZipFile(out, "w") as z:
            for n, d in items.items():
                z.writestr(n, d)
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            self.assertEqual(cli.main(["verify", out]), 1)
        self.assertIn("WARNING: bundle validation failed", stderr.getvalue())

    def test_verify_passes_intact(self):
        out = os.path.join(self.tmp, "i.zip")
        cli.main(["bundle", self.axe, "--out", out])
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(cli.main(["verify", out]), 0)
        self.assertTrue(json.loads(stdout.getvalue())["valid"])
        self.assertIn("Validity proves only ZIP members", stderr.getvalue())

    def test_verify_non_bundle_fails_cleanly(self):
        bad = os.path.join(self.tmp, "not-a-bundle.zip")
        with open(bad, "wb") as f:
            f.write(b"not a zip")
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            self.assertEqual(cli.main(["verify", bad]), 1)
        self.assertIn("WARNING: bundle validation failed", stderr.getvalue())

    def test_bundle_invalid_input_returns_2_and_no_output(self):
        bad_axe = os.path.join(self.tmp, "bad-axe.json")
        with open(bad_axe, "w", encoding="utf-8") as f:
            f.write("{")
        out = os.path.join(self.tmp, "bad.zip")
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            self.assertEqual(cli.main(["bundle", bad_axe, "--out", out]), 2)
        self.assertIn("ERROR:", stderr.getvalue())
        self.assertFalse(os.path.exists(out))

    def test_bundle_atomic_write_cleanup_on_replace_error(self):
        out = os.path.join(self.tmp, "atomic.zip")
        with mock.patch("cli.os.replace", side_effect=OSError("replace failed")):
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(cli.main(["bundle", self.axe, "--out", out]), 2)
        self.assertIn("ERROR: replace failed", stderr.getvalue())
        self.assertFalse(os.path.exists(out))
        leftovers = [n for n in os.listdir(self.tmp) if n.startswith(".accessdoc-")]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
