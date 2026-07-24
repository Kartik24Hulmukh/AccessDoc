"""Guards the reproducibility claim. These tests exist because the Phase 3.1
determinism check passed only by luck: it compared two runs that happened to
complete inside the same wall-clock second."""
import json
import time
import unittest

from app.intoto import normalize_timestamp, build_intoto_bundle
from app.service import build_artifacts
from app.bundle import build_bundle
from app.reporter import build_pdf_title

BODY = {
    "scanner_input": json.dumps({"violations": [
        {"id": "image-alt", "impact": "critical", "description": "d",
         "helpUrl": "h", "nodes": [{"target": ["img"]}]}
    ], "passes": []}),
    "client_name": "Acme", "audit_date": "2026-07-25",
}


class TestNormalizeTimestamp(unittest.TestCase):
    def test_bare_date_anchors_to_midnight(self):
        self.assertEqual(normalize_timestamp("2026-07-25"), "2026-07-25T00:00:00Z")

    def test_passthrough_rfc3339(self):
        self.assertEqual(normalize_timestamp("2026-07-25T11:22:33Z"),
                         "2026-07-25T11:22:33Z")

    def test_strips_fractional_seconds(self):
        self.assertEqual(normalize_timestamp("2026-07-25T11:22:33.456Z"),
                         "2026-07-25T11:22:33Z")

    def test_empty_returns_none(self):
        self.assertIsNone(normalize_timestamp(""))
        self.assertIsNone(normalize_timestamp(None))


class TestAttestationDeterminism(unittest.TestCase):
    def test_explicit_timestamp_is_used(self):
        out = build_intoto_bundle({"a.txt": b"x"}, timestamp="2026-01-01T00:00:00Z")
        env = json.loads(out)
        import base64
        stmt = json.loads(base64.b64decode(env["payload"]))
        self.assertEqual(stmt["predicate"]["timestamp"], "2026-01-01T00:00:00Z")

    def test_identical_across_second_boundary(self):
        """THE regression test. The old check slept 0s and passed by luck."""
        a = build_intoto_bundle({"a.txt": b"x"}, timestamp=normalize_timestamp("2026-07-25"))
        time.sleep(1.1)
        b = build_intoto_bundle({"a.txt": b"x"}, timestamp=normalize_timestamp("2026-07-25"))
        self.assertEqual(a, b, "attestation changed across a second boundary")


class TestBundleReproducibility(unittest.TestCase):
    def test_bundle_byte_identical_across_delayed_runs(self):
        z1 = build_bundle(build_artifacts(dict(BODY)))
        time.sleep(1.1)
        z2 = build_bundle(build_artifacts(dict(BODY)))
        self.assertEqual(z1, z2, "bundle not byte-reproducible across a second boundary")


class TestPdfTitle(unittest.TestCase):
    def test_no_empty_interpolation(self):
        for t in (build_pdf_title("", ""), build_pdf_title("Client", ""),
                  build_pdf_title(None, None)):
            self.assertNotIn(" -  - ", t)
            self.assertFalse(t.endswith(" - "), t)
            self.assertFalse(t.endswith("- "), t)

    def test_includes_client_and_date(self):
        t = build_pdf_title("Acme Corp", "2026-07-25")
        self.assertIn("Acme Corp", t)
        self.assertIn("2026-07-25", t)

    def test_never_anonymous(self):
        self.assertTrue(build_pdf_title("", "").startswith("Accessibility Evidence Report"))


if __name__ == "__main__":
    unittest.main()
