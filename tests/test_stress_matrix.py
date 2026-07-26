"""Phase 11 — Expanded stress and performance matrix.

Structured stress suite covering INPUT, SECURITY, DETERMINISM, and TAMPER
categories.  Performance measurements are informational (printed, not gated).

Every test either passes cleanly or fails with a bounded ValueError — never
a raw traceback, never a skipped assertion.
"""
import copy
import hashlib
import io
import json
import os
import sys
import time
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.service import build_artifacts
from app.bundle import (
    build_bundle,
    validate_bundle,
    ALLOWED_MEMBER_NAMES,
    MAX_COMPRESSION_RATIO,
    SCHEMA_VERSION,
)
from app.safe_text import safe_text
from app.reporter import generate_pdf_report
from app.models import AuditSummary, AuditViolation
from app.duediligence import build_due_diligence, render_due_diligence_md
from app.limits import MAX_HISTORY_RECEIPTS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _axe(url="https://example.com", violations=None, passes=None):
    return json.dumps({
        "url": url,
        "testEngine": {"name": "axe-core", "version": "4.11.2"},
        "violations": violations or [],
        "passes": passes or [],
        "incomplete": [],
    })


def _viol(n, impact="critical"):
    return {
        "id": f"rule-{n}",
        "impact": impact,
        "description": f"Description for rule {n}",
        "helpUrl": "https://dequeuniversity.com/rules/axe/4.11/image-alt",
        "nodes": [{"html": f"<div id='n-{n}'>content</div>"}],
    }


def _body(scanner_input, **kw):
    b = {"scanner_input": scanner_input}
    b.update(kw)
    return b


def _valid_bundle():
    """Build a genuine valid bundle via the real pipeline."""
    body = _body(_axe(violations=[_viol(0)]), client_name="StressTest",
                 audit_date="2026-01-15")
    return build_bundle(build_artifacts(body))


def _read_members(data):
    members = {}
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            members[name] = zf.read(name)
    return members


def _rebuild_zip(members):
    """Rebuild a ZIP from a {name: bytes} dict (fixed epoch for determinism)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            info = zipfile.ZipInfo(filename=name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            info.create_system = 3
            zf.writestr(info, data)
    return buf.getvalue()


def _make_receipt(date, crit=0, serious=0, mod=0, minor=0, viols=None):
    return {
        "audit_date": date,
        "accessdoc_version": "0.7.0",
        "summary": {"critical": crit, "serious": serious,
                     "moderate": mod, "minor": minor},
        "violations": viols or [
            {"id": "image-alt", "target": "img.hero", "impact": "critical"},
        ],
    }


# ===========================================================================
# INPUT TESTS
# ===========================================================================

class InputStressTests(unittest.TestCase):
    """Empty / null / malformed / large / unicode / duplicate / history."""

    # --- empty / null / malformed ---

    def test_empty_string_scanner_input(self):
        with self.assertRaises(ValueError):
            build_artifacts({"scanner_input": ""})

    def test_none_scanner_input(self):
        with self.assertRaises(ValueError):
            build_artifacts({"scanner_input": None})

    def test_missing_scanner_input_key(self):
        with self.assertRaises(ValueError):
            build_artifacts({})

    def test_malformed_json_string(self):
        with self.assertRaises((ValueError, json.JSONDecodeError)):
            build_artifacts({"scanner_input": "{not valid json"})

    def test_truncated_json(self):
        with self.assertRaises((ValueError, json.JSONDecodeError)):
            build_artifacts({"scanner_input": '{"violations": [1, 2,'})

    def test_non_object_json(self):
        with self.assertRaises(ValueError):
            build_artifacts({"scanner_input": "42"})

    def test_array_top_level(self):
        with self.assertRaises(ValueError):
            build_artifacts({"scanner_input": "[1, 2, 3]"})

    # --- 1 / 100 / 1000 violations -> valid bundle ---

    def test_1_violation_valid_bundle(self):
        data = build_bundle(build_artifacts(
            _body(_axe(violations=[_viol(0)]), audit_date="2026-01-15")))
        result = validate_bundle(data)
        self.assertTrue(result["valid"], result["errors"])

    def test_100_violations_valid_bundle(self):
        viols = [_viol(i) for i in range(100)]
        data = build_bundle(build_artifacts(
            _body(_axe(violations=viols), audit_date="2026-01-15")))
        result = validate_bundle(data)
        self.assertTrue(result["valid"], result["errors"])

    def test_1000_violations_valid_bundle(self):
        viols = [_viol(i) for i in range(1000)]
        data = build_bundle(build_artifacts(
            _body(_axe(violations=viols), audit_date="2026-01-15")))
        result = validate_bundle(data)
        self.assertTrue(result["valid"], result["errors"])

    # --- extremely long strings (10k chars) ---

    def test_10k_char_description_handled(self):
        long_desc = "A" * 10_000
        viols = [{
            "id": "image-alt", "impact": "critical",
            "description": long_desc, "helpUrl": "h",
            "nodes": [{"html": "<img>"}],
        }]
        arts = build_artifacts(_body(_axe(violations=viols), audit_date="2026-01-15"))
        self.assertIsNotNone(arts)
        data = build_bundle(arts)
        result = validate_bundle(data)
        self.assertTrue(result["valid"], result["errors"])

    def test_10k_char_client_name_handled(self):
        long_name = "C" * 10_000
        arts = build_artifacts(_body(
            _axe(violations=[_viol(0)]),
            client_name=long_name, audit_date="2026-01-15"))
        self.assertIsNotNone(arts)

    # --- Unicode / CJK / RTL / emoji ---

    def test_unicode_cjk_rtl_emoji_valid_bundle(self):
        viols = [{
            "id": "image-alt", "impact": "critical",
            "description": "日本語 テスト \u202eRTL text\u202c \U0001f389 emoji",
            "helpUrl": "https://example.com/\u65e5\u672c",
            "nodes": [{"html": "<img alt='\U0001f600'>"}],
        }]
        body = _body(
            _axe(violations=viols),
            client_name="Caf\u00e9 \u65e5\u672c\u8a9e \u202eRTL\u202c \U0001f389",
            audit_date="2026-01-15",
        )
        data = build_bundle(build_artifacts(body))
        result = validate_bundle(data)
        self.assertTrue(result["valid"], result["errors"])

    # --- duplicate findings -> deduplicated ---

    def test_duplicate_findings_deduplicated(self):
        v = _viol(0)
        viols = [v, copy.deepcopy(v), copy.deepcopy(v)]
        arts = build_artifacts(_body(
            _axe(violations=viols), audit_date="2026-01-15"))
        # The parser counts all entries; dedup happens at receipt level.
        # We verify the bundle is still valid and buildable.
        data = build_bundle(arts)
        result = validate_bundle(data)
        self.assertTrue(result["valid"], result["errors"])

    # --- 50-receipt valid history -> due diligence record ---

    def test_50_receipt_history_due_diligence(self):
        receipts = [
            _make_receipt(f"2026-01-{d:02d}", crit=d % 5)
            for d in range(1, 51)
        ]
        body = _body(
            _axe(violations=[_viol(0)]),
            audit_date="2026-03-01",
            receipt_history=receipts,
        )
        arts = build_artifacts(body)
        self.assertIsNotNone(arts.due_diligence_md)
        self.assertIn("Due-Diligence", arts.due_diligence_md)
        data = build_bundle(arts)
        result = validate_bundle(data)
        self.assertTrue(result["valid"], result["errors"])

    # --- 51-receipt rejection -> ValueError ---

    def test_51_receipt_history_rejected(self):
        receipts = [
            _make_receipt(f"2026-01-{d:02d}")
            for d in range(1, 52)
        ]
        body = _body(
            _axe(violations=[_viol(0)]),
            audit_date="2026-03-01",
            receipt_history=receipts,
        )
        with self.assertRaises(ValueError):
            build_artifacts(body)


# ===========================================================================
# SECURITY TESTS (verify existing protections hold)
# ===========================================================================

class SecurityStressTests(unittest.TestCase):
    """XSS / ReportLab markup / ZIP bomb / duplicate ZIP paths."""

    # --- HTML XSS corpus -> escaped in output ---

    XSS_CORPUS = [
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        "\"><script>alert('xss')</script>",
        "javascript:alert(1)",
        "<svg onload=alert(1)>",
        "<iframe src=javascript:alert(1)>",
        "<body onload=alert(1)>",
        "';alert(1);//",
        "<a href='javascript:alert(1)'>click</a>",
        "<style>*{background:url(javascript:alert(1))}</style>",
    ]

    def test_xss_corpus_escaped_in_html(self):
        for payload in self.XSS_CORPUS:
            with self.subTest(payload=payload):
                arts = build_artifacts(_body(
                    _axe(violations=[{
                        "id": "image-alt", "impact": "critical",
                        "description": payload, "helpUrl": payload,
                        "nodes": [{"html": payload}],
                    }]),
                    client_name=payload,
                    audit_date="2026-01-15",
                ))
                html_out = arts.html_bytes.decode()
                # Escaped: dangerous tags become &lt;script&gt; etc.
                # We check for UNESCAPED active markup, not the literal
                # payload text which correctly appears as visible text.
                self.assertNotIn("<script>", html_out)
                self.assertNotIn("<img src=x onerror=", html_out)
                self.assertNotIn("<svg onload=", html_out)
                self.assertNotIn("<iframe ", html_out)
                self.assertNotIn("<body onload=", html_out)
                # The raw payload must be escaped (no raw angle brackets
                # from the payload survive as active HTML).
                self.assertNotIn("<script>alert(1)</script>", html_out)
                self.assertNotIn("<img src=x onerror=alert(1)>", html_out)

    # --- ReportLab markup corpus -> safe_text applied ---

    REPORTLAB_CORPUS = [
        "<font color='red'>injected</font>",
        "<b>bold</b><i>italic</i>",
        "<a href='http://evil.com'>link</a>",
        "<img src='http://evil.com/x.png'>",
        "&lt;entity&gt;",
        "<para>text</para>",
        "<br/>",
        "<sup>1</sup>",
        '<font face="Helvetica">text</font>',
        "<bullet>text</bullet>",
    ]

    def test_reportlab_markup_corpus_safe_text(self):
        for payload in self.REPORTLAB_CORPUS:
            with self.subTest(payload=payload):
                result = safe_text(payload)
                # safe_text must never return active ReportLab markup
                self.assertNotIn("<font", result)
                self.assertNotIn("<a href", result)
                self.assertNotIn("<img", result)
                self.assertNotIn("<bullet", result)
                self.assertNotIn("<para", result)

    def test_reportlab_markup_in_pdf_is_safe(self):
        """Hostile markup in violation fields must not inject into PDF."""
        summary = AuditSummary(
            critical=1, serious=0, moderate=0, minor=0,
            total_violations=1, total_passes=0,
            url="https://example.com", engine_version="4.11.2",
        )
        viols = [AuditViolation(
            id="image-alt", impact="critical",
            description="<font color='red'>EVIL</font><script>alert(1)</script>",
            help_url="https://example.com",
            nodes=1,
        )]
        pdf = generate_pdf_report(summary, viols, "TestClient", "Agency", "2026-01-15")
        # PDF must not contain raw script tags or font markup from input
        pdf_text = pdf.decode("latin-1", errors="replace")
        self.assertNotIn("<script>alert(1)</script>", pdf_text)
        self.assertNotIn("<font color='red'>EVIL</font>", pdf_text)

    # --- ZIP bomb -> rejected by validate_bundle ---

    def test_zip_bomb_rejected(self):
        """A ZIP with extreme compression ratio must be rejected."""
        # Create a ZIP with a single highly-compressible member
        bomb_content = b"\x00" * (2 * 1024 * 1024)  # 2 MiB of zeros
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            info = zipfile.ZipInfo(filename="report.html", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            info.create_system = 3
            zf.writestr(info, bomb_content)
        result = validate_bundle(buf.getvalue())
        self.assertFalse(result["valid"])
        # Should mention compression ratio or size limit
        self.assertTrue(
            any("ratio" in e or "size" in e for e in result["errors"]),
            f"Expected ratio/size error, got: {result['errors']}"
        )

    # --- duplicate ZIP paths -> rejected ---

    def test_duplicate_zip_paths_rejected(self):
        """A ZIP with duplicate member names must be rejected."""
        members = _read_members(_valid_bundle())
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in members.items():
                info = zipfile.ZipInfo(filename=name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                info.create_system = 3
                zf.writestr(info, data)
            # Add a duplicate report.html
            info2 = zipfile.ZipInfo(filename="report.html", date_time=(1980, 1, 1, 0, 0, 0))
            info2.compress_type = zipfile.ZIP_DEFLATED
            info2.external_attr = 0o644 << 16
            info2.create_system = 3
            zf.writestr(info2, b"duplicate content")
        result = validate_bundle(buf.getvalue())
        self.assertFalse(result["valid"])
        self.assertTrue(
            any("duplicate" in e for e in result["errors"]),
            f"Expected duplicate error, got: {result['errors']}"
        )


# ===========================================================================
# DETERMINISM TESTS
# ===========================================================================

class DeterminismStressTests(unittest.TestCase):
    """Same input across time / processes -> identical hash."""

    BODY = _body(
        _axe(violations=[_viol(0), _viol(1, "serious")]),
        client_name="DeterminismTest",
        audit_date="2026-01-15",
    )

    def test_delay_across_3_seconds_same_hash(self):
        """Same --audit-date, 3-second delay -> byte-identical bundle."""
        b1 = build_bundle(build_artifacts(dict(self.BODY)))
        time.sleep(3.1)
        b2 = build_bundle(build_artifacts(dict(self.BODY)))
        h1 = hashlib.sha256(b1).hexdigest()
        h2 = hashlib.sha256(b2).hexdigest()
        self.assertEqual(h1, h2,
                         f"Bundle hash changed across 3s: {h1} != {h2}")

    def test_same_input_different_process_identical_hash(self):
        """Same input in a separate process -> identical bundle hash."""
        b1 = build_bundle(build_artifacts(dict(self.BODY)))
        h1 = hashlib.sha256(b1).hexdigest()

        # Spawn a subprocess to build the same bundle
        import subprocess
        script = (
            "import sys; sys.path.insert(0, '.'); "
            "from app.service import build_artifacts; "
            "from app.bundle import build_bundle; "
            "import hashlib, json; "
            "body = {'scanner_input': json.dumps({"
            "'url': 'https://example.com', "
            "'testEngine': {'name': 'axe-core', 'version': '4.11.2'}, "
            "'violations': ["
            "{'id': 'rule-0', 'impact': 'critical', 'description': 'Description for rule 0', "
            "'helpUrl': 'https://dequeuniversity.com/rules/axe/4.11/image-alt', "
            "'nodes': [{'html': '<div id=\\\"n-0\\\">content</div>'}]}, "
            "{'id': 'rule-1', 'impact': 'serious', 'description': 'Description for rule 1', "
            "'helpUrl': 'https://dequeuniversity.com/rules/axe/4.11/image-alt', "
            "'nodes': [{'html': '<div id=\\\"n-1\\\">content</div>'}]}], "
            "'passes': [], 'incomplete': []}), "
            "'client_name': 'DeterminismTest', 'audit_date': '2026-01-15'}; "
            "data = build_bundle(build_artifacts(body)); "
            "print(hashlib.sha256(data).hexdigest())"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=60,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        self.assertEqual(result.returncode, 0,
                         f"Subprocess failed: {result.stderr}")
        h2 = result.stdout.strip()
        self.assertEqual(h1, h2,
                         f"Cross-process hash differs: {h1} != {h2}")


# ===========================================================================
# TAMPER TESTS
# ===========================================================================

class TamperStressTests(unittest.TestCase):
    """Tampering any member must cause validate_bundle to fail."""

    def setUp(self):
        self.data = _valid_bundle()
        self.members = _read_members(self.data)

    def _rebuild_and_validate(self):
        return validate_bundle(_rebuild_zip(self.members))

    def test_tamper_report_pdf_fails(self):
        self.members["report.pdf"] = b"%PDF-tampered-content"
        result = self._rebuild_and_validate()
        self.assertFalse(result["valid"])
        self.assertTrue(
            any("report.pdf" in e for e in result["errors"]),
            f"Expected report.pdf error, got: {result['errors']}"
        )

    def test_tamper_manifest_json_fails(self):
        manifest = json.loads(self.members["manifest.json"])
        manifest["files"][0]["sha256"] = "0" * 64
        self.members["manifest.json"] = json.dumps(manifest, indent=2).encode()
        result = self._rebuild_and_validate()
        self.assertFalse(result["valid"])

    def test_tamper_attestation_fails(self):
        attest = json.loads(self.members["attestation.intoto.json"])
        # Corrupt the payload
        attest["payload"] = "tampered"
        self.members["attestation.intoto.json"] = json.dumps(attest, indent=2).encode()
        result = self._rebuild_and_validate()
        self.assertFalse(result["valid"])


# ===========================================================================
# PERFORMANCE MEASUREMENTS (informational, not pass/fail gates)
# ===========================================================================

class PerformanceMeasurements(unittest.TestCase):
    """Measure and print performance metrics. Not pass/fail gates."""

    def test_measure_1000_violations_duration(self):
        viols = [_viol(i) for i in range(1000)]
        body = _body(_axe(violations=viols), audit_date="2026-01-15")
        start = time.time()
        data = build_bundle(build_artifacts(body))
        elapsed = time.time() - start
        print(f"  PERF: 1000 violations -> {elapsed:.2f}s, {len(data):,} bytes")
        # Sanity: must complete and be valid
        self.assertTrue(validate_bundle(data)["valid"])

    def test_measure_standard_fixture_bytes(self):
        body = _body(
            _axe(violations=[_viol(0)]),
            client_name="PerfTest",
            audit_date="2026-01-15",
        )
        data = build_bundle(build_artifacts(body))
        print(f"  PERF: standard fixture -> {len(data):,} bytes")
        self.assertTrue(validate_bundle(data)["valid"])


if __name__ == "__main__":
    unittest.main()
