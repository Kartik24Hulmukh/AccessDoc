"""Determinism and tamper-evidence regression tests.

Tests that:
1. Same scanner_input produces byte-identical bundles (end-to-end, including
   PDF, with reportlab.rl_config.invariant=1 set in app/reporter.py).
2. validate_bundle detects every form of tampering.
3. Bundle generation is timezone-independent.
"""
import copy
import io
import json
import os
import sys
import time
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.service import build_artifacts
from app.bundle import build_bundle, validate_bundle

_AXE = json.dumps({
    "url": "https://example.com",
    "testEngine": {"name": "axe-core", "version": "4.11.2"},
    "violations": [
        {"id": "image-alt", "impact": "critical", "description": "alt",
         "helpUrl": "h", "nodes": [{}]},
        {"id": "color-contrast", "impact": "serious", "description": "c",
         "helpUrl": "h", "nodes": [{}, {}]},
    ],
})

_BODY = {
    "scanner_input": _AXE,
    "client_name": "TestClient",
    "audit_date": "2026-01-15",  # fixed date for determinism
}


class TestDeterminism(unittest.TestCase):
    """Same input must produce byte-identical output end-to-end.

    With reportlab.rl_config.invariant=1 (set in app/reporter.py), the PDF
    is fully deterministic: /CreationDate, /ModDate, and /ID are replaced
    with fixed values. This makes the entire bundle byte-reproducible.
    """

    def test_receipt_deterministic(self):
        b1 = build_artifacts(dict(_BODY))
        b2 = build_artifacts(dict(_BODY))
        self.assertEqual(b1.receipt_json, b2.receipt_json)

    def test_openacr_deterministic(self):
        b1 = build_artifacts(dict(_BODY))
        b2 = build_artifacts(dict(_BODY))
        self.assertEqual(b1.openacr_yaml, b2.openacr_yaml)

    def test_html_deterministic(self):
        b1 = build_artifacts(dict(_BODY))
        b2 = build_artifacts(dict(_BODY))
        self.assertEqual(b1.html_bytes, b2.html_bytes)

    def test_pdf_byte_identical(self):
        """PDF must be byte-identical for same input + fixed date.

        This is achieved via reportlab.rl_config.invariant=1, which replaces
        the random /ID digest and live /CreationDate + /ModDate timestamps
        with fixed values. Without invariant=1, the PDF is non-deterministic.
        """
        b1 = build_artifacts(dict(_BODY))
        b2 = build_artifacts(dict(_BODY))
        self.assertEqual(b1.pdf_bytes, b2.pdf_bytes)

    def test_pdf_has_meaningful_title(self):
        """PDF /Title must be a meaningful string, not '(anonymous)'."""
        import re
        b = build_artifacts(dict(_BODY))
        pdf_text = b.pdf_bytes.decode("latin-1")
        title = re.search(r"/Title\s*\(([^)]*)\)", pdf_text)
        self.assertIsNotNone(title, "/Title not set in PDF")
        self.assertNotIn("anonymous", title.group(1).lower(),
                         "PDF title is still '(anonymous)'")

    def test_pdf_has_language(self):
        """PDF /Lang must be set (document language)."""
        import re
        b = build_artifacts(dict(_BODY))
        pdf_text = b.pdf_bytes.decode("latin-1")
        lang = re.search(r"/Lang\s*\(([^)]*)\)", pdf_text)
        self.assertIsNotNone(lang, "/Lang not set in PDF")
        self.assertEqual(lang.group(1), "en")

    def test_pdf_has_author(self):
        """PDF /Author must be set to AccessDoc version."""
        import re
        b = build_artifacts(dict(_BODY))
        pdf_text = b.pdf_bytes.decode("latin-1")
        author = re.search(r"/Author\s*\(([^)]*)\)", pdf_text)
        self.assertIsNotNone(author, "/Author not set in PDF")
        self.assertIn("AccessDoc", author.group(1))

    def test_bundle_byte_identical_end_to_end(self):
        """The FULL bundle (every file including PDF, manifest, in-toto)
        must be byte-identical for same input + fixed date.

        This is the product's core claim: reproducible evidence. With
        invariant=1, the in-toto timestamp is the ONLY non-deterministic
        field, and it too is fixed when audit_date is provided.
        """
        zip1 = build_bundle(build_artifacts(dict(_BODY)))
        zip2 = build_bundle(build_artifacts(dict(_BODY)))

        def _extract(zip_bytes):
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                return {n: zf.read(n) for n in zf.namelist()}

        f1 = _extract(zip1)
        f2 = _extract(zip2)

        for name in f1:
            self.assertEqual(f1[name], f2[name],
                             f"{name} differs across runs — bundle is not "
                             f"byte-reproducible")

    def test_bundle_sha256_identical(self):
        """Bundle SHA-256 must be identical across runs."""
        import hashlib
        z1 = build_bundle(build_artifacts(dict(_BODY)))
        z2 = build_bundle(build_artifacts(dict(_BODY)))
        self.assertEqual(hashlib.sha256(z1).hexdigest(),
                         hashlib.sha256(z2).hexdigest())

    def test_timezone_independence(self):
        """Bundle generation must not depend on the system timezone."""
        import subprocess

        repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env_utc = dict(os.environ, TZ="UTC")
        env_ist = dict(os.environ, TZ="Asia/Calcutta")

        axe_path = os.path.join(repo_dir, "fixtures", "axe-sample.json")
        script = (
            "import json, sys; sys.path.insert(0, %r); "
            "from app.service import build_artifacts; from app.bundle import build_bundle; "
            "axe = open(%r).read(); "
            "body = {'scanner_input': axe, 'client_name': 'TZTest', 'audit_date': '2026-01-15'}; "
            "arts = build_artifacts(body); "
            "import zipfile, io; "
            "z = build_bundle(arts); "
            "zf = zipfile.ZipFile(io.BytesIO(z)); "
            "print(json.dumps({n: zf.read(n).hex() for n in zf.namelist()}))"
            % (repo_dir, axe_path)
        )

        r_utc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, env=env_utc,
            cwd=repo_dir, timeout=30,
        )
        r_ist = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, env=env_ist,
            cwd=repo_dir, timeout=30,
        )

        if r_utc.returncode != 0:
            self.fail(f"UTC run failed: {r_utc.stderr}")
        if r_ist.returncode != 0:
            self.fail(f"IST run failed: {r_ist.stderr}")

        files_utc = json.loads(r_utc.stdout.strip())
        files_ist = json.loads(r_ist.stdout.strip())

        # The in-toto attestation contains a timestamp (_utc_now()) that
        # differs between the two subprocess calls (they run at different
        # seconds). The manifest.json contains the SHA-256 of the in-toto
        # attestation, so it also differs. We exclude both and verify the
        # rest is timezone-independent. The timestamp is always UTC
        # regardless of TZ, so timezone-independence is about the other
        # fields.
        _tz_skip = {"attestation.intoto.json", "manifest.json"}
        for name in files_utc:
            if name in _tz_skip:
                if name == "attestation.intoto.json":
                    import base64
                    a1 = json.loads(bytes.fromhex(files_utc[name]))
                    a2 = json.loads(bytes.fromhex(files_ist[name]))
                    p1 = json.loads(base64.b64decode(a1["payload"])).get("predicate", {})
                    p2 = json.loads(base64.b64decode(a2["payload"])).get("predicate", {})
                    p1_c = {k: v for k, v in p1.items() if k != "timestamp"}
                    p2_c = {k: v for k, v in p2.items() if k != "timestamp"}
                    self.assertEqual(p1_c, p2_c,
                                     "in-toto differs across timezones (outside timestamp)")
                # manifest.json: skip (contains hash of in-toto with timestamp)
                continue
            self.assertEqual(files_utc[name], files_ist[name],
                             f"{name} differs across timezones")


class TestTamperDetection(unittest.TestCase):
    """validate_bundle must detect every form of tampering."""

    @classmethod
    def setUpClass(cls):
        cls.bundle = build_bundle(build_artifacts(dict(_BODY)))

    def _read_members(self, zip_bytes):
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            return {n: zf.read(n) for n in zf.namelist()}

    def _rebuild(self, members):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in members.items():
                zf.writestr(name, data)
        return buf.getvalue()

    def test_valid_bundle_passes(self):
        result = validate_bundle(self.bundle)
        self.assertTrue(result["valid"], f"Valid bundle failed: {result['errors']}")

    def test_tamper_report_pdf(self):
        members = self._read_members(self.bundle)
        members["report.pdf"] = members["report.pdf"][:-1] + b"X"
        result = validate_bundle(self._rebuild(members))
        self.assertFalse(result["valid"])
        self.assertTrue(any("report.pdf" in e for e in result["errors"]))

    def test_tamper_receipt_json(self):
        members = self._read_members(self.bundle)
        receipt = json.loads(members["receipt.json"])
        receipt["client_name"] = "TAMPERED"
        members["receipt.json"] = json.dumps(receipt).encode()
        result = validate_bundle(self._rebuild(members))
        self.assertFalse(result["valid"])
        self.assertTrue(any("receipt.json" in e for e in result["errors"]))

    def test_remove_manifest_member(self):
        members = self._read_members(self.bundle)
        del members["openacr.yaml"]
        result = validate_bundle(self._rebuild(members))
        self.assertFalse(result["valid"])

    def test_add_unmanifested_file(self):
        members = self._read_members(self.bundle)
        members["injected.txt"] = b"malicious"
        result = validate_bundle(self._rebuild(members))
        self.assertFalse(result["valid"])

    def test_corrupt_manifest(self):
        members = self._read_members(self.bundle)
        members["manifest.json"] = b"{not valid json"
        result = validate_bundle(self._rebuild(members))
        self.assertFalse(result["valid"])

    def test_corrupt_intoto_statement(self):
        members = self._read_members(self.bundle)
        members["attestation.intoto.json"] = b'{"tampered": true}'
        result = validate_bundle(self._rebuild(members))
        self.assertFalse(result["valid"])
        self.assertTrue(any("attestation" in e for e in result["errors"]))

    def test_missing_manifest(self):
        members = self._read_members(self.bundle)
        del members["manifest.json"]
        result = validate_bundle(self._rebuild(members))
        self.assertFalse(result["valid"])
        self.assertTrue(any("manifest" in e.lower() for e in result["errors"]))


if __name__ == "__main__":
    unittest.main()
