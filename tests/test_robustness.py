"""Robustness tests: large inputs, malformed inputs, fresh XSS payloads.

Every test must either pass cleanly or fail with a useful error — never a
raw traceback.
"""
import json
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.service import build_artifacts
from app.bundle import build_bundle, validate_bundle
from app.parser import parse_axe_json


def _axe(url="https://x.com", violations=None):
    return json.dumps({
        "url": url,
        "testEngine": {"name": "axe-core", "version": "4.11.2"},
        "violations": violations or [],
    })


class TestLargeInput(unittest.TestCase):
    """10,000 violations must build without crash or unbounded memory."""

    def test_10000_violations(self):
        viols = [
            {
                "id": f"rule-{i}",
                "impact": "minor",
                "description": f"d-{i}",
                "helpUrl": "h",
                "nodes": [{}] * 3,
            }
            for i in range(10000)
        ]
        body = {"scanner_input": _axe(violations=viols), "client_name": "BigTest"}
        start = time.time()
        bundle = build_bundle(build_artifacts(body))
        elapsed = time.time() - start
        # Should complete in reasonable time (< 30s)
        self.assertLess(elapsed, 30, f"Bundle build took {elapsed:.1f}s")
        # Bundle should be valid
        result = validate_bundle(bundle)
        self.assertTrue(result["valid"], f"Large bundle invalid: {result['errors']}")
        # Bundle should be within size limit
        self.assertLess(len(bundle), 8_000_000)
        print(f"  10k violations: {elapsed:.2f}s, {len(bundle):,} bytes")


class TestMalformedInput(unittest.TestCase):
    """Malformed inputs must fail cleanly, never traceback."""

    def test_truncated_json(self):
        with self.assertRaises((ValueError, json.JSONDecodeError)):
            build_artifacts({"scanner_input": '{"violations": [1, 2,'})

    def test_wrong_top_level_type(self):
        with self.assertRaises(ValueError):
            build_artifacts({"scanner_input": '42'})

    def test_violations_missing_required_keys(self):
        """Violations missing 'id' or 'impact' should not crash."""
        # Should tolerate missing keys gracefully
        body = {"scanner_input": _axe(violations=[
            {"description": "no id or impact", "helpUrl": "h", "nodes": [{}]},
        ])}
        arts = build_artifacts(body)  # should not raise
        self.assertIsNotNone(arts)

    def test_deeply_nested_junk(self):
        """Deeply nested structures should not crash."""
        nested = {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": "deep"}}}}}}}}
        body = {"scanner_input": json.dumps({
            "url": "https://x.com",
            "testEngine": nested,
            "violations": [nested],
        })}
        arts = build_artifacts(body)
        self.assertIsNotNone(arts)

    def test_unicode_rtl_emoji_client_name(self):
        """Unicode, RTL text, and emoji in client_name must not crash."""
        body = {
            "scanner_input": _axe(),
            "client_name": "مرحبا \u202eRTL\u202c \U0001f389 \u65e5\u672c",
        }
        arts = build_artifacts(body)
        self.assertIsNotNone(arts)

    def test_unicode_rtl_emoji_url(self):
        """Unicode, RTL text, and emoji in URL must not crash."""
        body = {
            "scanner_input": _axe(url="https://ex\u00e4mple.com/\u65e5\u672c/\U0001f389"),
        }
        arts = build_artifacts(body)
        self.assertIsNotNone(arts)

    def test_extremely_long_client_name(self):
        """A 10,000-char client name must not crash."""
        body = {
            "scanner_input": _axe(),
            "client_name": "A" * 10000,
        }
        arts = build_artifacts(body)
        self.assertIsNotNone(arts)

    def test_empty_violations_list(self):
        """Empty violations list should produce a valid bundle."""
        body = {"scanner_input": _axe(violations=[])}
        arts = build_artifacts(body)
        self.assertIsNotNone(arts)

    def test_null_violations(self):
        """null violations should be tolerated."""
        body = {"scanner_input": json.dumps({"violations": None})}
        arts = build_artifacts(body)
        self.assertIsNotNone(arts)


class TestFreshXSSPayloads(unittest.TestCase):
    """Fresh XSS payloads in every field that reaches HTML."""

    def _check_html(self, body, payload):
        """Assert payload does not appear unescaped in HTML output."""
        arts = build_artifacts(body)
        html = arts.html_bytes.decode()
        self.assertNotIn(payload, html,
                         f"Unescaped payload found in HTML: {payload!r}")

    def test_svg_onload_in_client_name(self):
        payload = '<svg onload=alert(1)>'
        self._check_html(
            {"scanner_input": _axe(), "client_name": payload}, payload)

    def test_svg_onload_in_url(self):
        payload = '<svg onload=alert(1)>'
        self._check_html(
            {"scanner_input": _axe(url=f"x{payload}")}, payload)

    def test_javascript_url_in_client_name(self):
        """javascript: URL in client_name appears as text, not as an
        executable URL — html.escape correctly leaves it as inert text
        since it contains no HTML special characters."""
        payload = 'javascript:alert(1)'
        body = {"scanner_input": _axe(), "client_name": payload}
        arts = build_artifacts(body)
        html = arts.html_bytes.decode()
        # The payload appears as text content (not in an href attribute),
        # so it's inert. Verify it's NOT in an attribute context.
        self.assertNotIn(f'href="{payload}"', html)
        self.assertNotIn(f"href='{payload}'", html)
        self.assertNotIn(f'src="{payload}"', html)

    def test_unicode_escaped_script_tag(self):
        """\\u003cscript\\u003e should not appear as actual <script> in HTML."""
        payload = '\u003cscript\u003ealert(1)\u003c/script\u003e'
        body = {"scanner_input": _axe(), "client_name": payload}
        arts = build_artifacts(body)
        html = arts.html_bytes.decode()
        # The literal <script> tag should not appear
        self.assertNotIn('<script>', html)
        self.assertNotIn('<script', html)

    def test_attribute_break_in_client_name(self):
        """Payload that tries to break out of an attribute context."""
        payload = '" onmouseover="alert(1)"'
        self._check_html(
            {"scanner_input": _axe(), "client_name": payload}, payload)

    def test_attribute_break_in_violation_id(self):
        payload = '" onmouseover="alert(1)"'
        self._check_html(
            {"scanner_input": _axe(violations=[
                {"id": payload, "impact": "critical", "description": "d",
                 "helpUrl": "h", "nodes": [{}]}
            ])}, payload)

    def test_attribute_break_in_violation_description(self):
        payload = '" onmouseover="alert(1)"'
        self._check_html(
            {"scanner_input": _axe(violations=[
                {"id": "x", "impact": "critical", "description": payload,
                 "helpUrl": "h", "nodes": [{}]}
            ])}, payload)

    def test_svg_onload_in_violation_id(self):
        payload = '<svg onload=alert(1)>'
        self._check_html(
            {"scanner_input": _axe(violations=[
                {"id": payload, "impact": "critical", "description": "d",
                 "helpUrl": "h", "nodes": [{}]}
            ])}, payload)

    def test_svg_onload_in_violation_description(self):
        payload = '<svg onload=alert(1)>'
        self._check_html(
            {"scanner_input": _axe(violations=[
                {"id": "x", "impact": "critical", "description": payload,
                 "helpUrl": "h", "nodes": [{}]}
            ])}, payload)

    def test_javascript_url_in_url_field(self):
        """javascript: URL in the scanned URL field appears as text content,
        not as an executable href — it's inert."""
        payload = 'javascript:alert(1)'
        body = {"scanner_input": _axe(url=payload)}
        arts = build_artifacts(body)
        html = arts.html_bytes.decode()
        # Verify it's NOT in an attribute context
        self.assertNotIn(f'href="{payload}"', html)
        self.assertNotIn(f"href='{payload}'", html)
        self.assertNotIn(f'src="{payload}"', html)

    def test_data_url_in_url_field(self):
        payload = 'data:text/html,<script>alert(1)</script>'
        self._check_html(
            {"scanner_input": _axe(url=payload)}, payload)

    def test_xss_in_vpat_client_name(self):
        """XSS in VPAT output client_name."""
        from app.vpat import generate_vpat_html
        from app.models import AuditSummary
        payload = '<script>alert(1)</script>'
        html = generate_vpat_html(
            AuditSummary(url="https://x.com"), [],
            client_name=payload)
        self.assertNotIn(payload, html)
        self.assertIn('&lt;script&gt;', html)

    def test_xss_in_vpat_via_violation(self):
        """XSS in VPAT output via violation fields."""
        from app.vpat import generate_vpat_html
        from app.models import AuditSummary, AuditViolation
        payload = '<svg onload=alert(1)>'
        v = AuditViolation(id=payload, impact="critical", description=payload,
                           help_url="h", wcag_scs=["1.1.1"])
        html = generate_vpat_html(
            AuditSummary(url="https://x.com"), [v])
        self.assertNotIn(payload, html)


if __name__ == "__main__":
    unittest.main()
