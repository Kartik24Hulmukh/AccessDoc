"""End-to-end CLI tests."""
import json
import io
import os
import sys
import tempfile
import unittest
import zipfile
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
        self.assertEqual(cli.main(["verify", out]), 1)

    def test_verify_passes_intact(self):
        out = os.path.join(self.tmp, "i.zip")
        cli.main(["bundle", self.axe, "--out", out])
        self.assertEqual(cli.main(["verify", out]), 0)


if __name__ == "__main__":
    unittest.main()
