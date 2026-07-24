"""Security regression tests - XSS + YAML injection must never reappear."""
import json
import os
import sys
import unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.service import build_artifacts


def _body(client_name="C", url="https://x.com", desc="d", rule_id="image-alt"):
    return {
        "scanner_input": json.dumps({
            "url": url,
            "testEngine": {"name": "axe-core", "version": "4.11.2"},
            "violations": [{"id": rule_id, "impact": "critical",
                            "description": desc, "helpUrl": "h", "nodes": [{}]}],
        }),
        "client_name": client_name,
    }


class TestSecurity(unittest.TestCase):
    def test_xss_client_name_escaped_in_html(self):
        arts = build_artifacts(_body(client_name="<script>alert(1)</script>"))
        self.assertNotIn("<script>alert(1)</script>", arts.html_bytes.decode())
        self.assertIn("&lt;script&gt;", arts.html_bytes.decode())

    def test_xss_url_escaped_in_html(self):
        arts = build_artifacts(_body(url="x</p><script>x</script>"))
        self.assertNotIn("<script>x</script>", arts.html_bytes.decode())

    def test_xss_violation_fields_escaped(self):
        arts = build_artifacts(_body(desc="<script>bad</script>", rule_id="<img onerror=1>"))
        html = arts.html_bytes.decode()
        self.assertNotIn("<script>bad</script>", html)
        self.assertNotIn("<img onerror=1>", html)

    def test_yaml_injection_safe(self):
        import yaml
        arts = build_artifacts(_body(client_name='evil"\ninjected_key: pwned'))
        doc = yaml.safe_load(arts.openacr_yaml)
        self.assertNotIn("injected_key", doc)
        self.assertIn("product", doc)

    def test_yaml_still_valid_with_unicode(self):
        import yaml
        arts = build_artifacts(_body(client_name="Caf\u00e9 \u65e5\u672c \U0001f389"))
        doc = yaml.safe_load(arts.openacr_yaml)
        self.assertIn("Caf\u00e9", doc["product"]["name"])

    def test_control_chars_stripped_from_yaml(self):
        import yaml
        arts = build_artifacts(_body(client_name="a\x00\x07b"))
        yaml.safe_load(arts.openacr_yaml)


if __name__ == "__main__":
    unittest.main()
