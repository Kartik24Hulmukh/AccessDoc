"""Unresolved supplied scanner checks must not disappear or become passes."""
import copy
import json
import unittest

from app.bundle import build_bundle, validate_bundle
from app.limits import LimitExceeded, MAX_NODES_PER_VIOLATION, MAX_VIOLATIONS
from app.parser import parse_axe_json
from app.receipt_validate import validate_receipt
from app.service import build_artifacts


def scanner():
    return {
        "url": "https://synthetic.invalid/page",
        "testEngine": {"version": "4.11.0"},
        "violations": [],
        "incomplete": [{
            "id": "color-contrast", "description": "Contrast needs review",
            "helpUrl": "https://synthetic.invalid/help",
            "nodes": [{"target": ["#first"]}, {"target": ["#second"]}],
        }],
    }


class PendingEvidenceTests(unittest.TestCase):
    def test_pending_instances_are_separate_from_violations(self):
        summary, violations = parse_axe_json(scanner())
        self.assertEqual(violations, [])
        self.assertEqual(summary.total_violations, 0)
        self.assertEqual(summary.total_passes, 0)
        self.assertEqual(summary.total_incomplete, 1)  # supplied rule count
        self.assertEqual(len(summary.pending_checks), 2)
        self.assertEqual({p["target"] for p in summary.pending_checks},
                         {"#first", "#second"})
        self.assertTrue(all(p["status"] == "needs-review" and
                            p["source"] == "automated"
                            for p in summary.pending_checks))

    def test_receipt_preserves_pending_and_remains_valid(self):
        arts = build_artifacts({"scanner_input": scanner(), "audit_date": "2026-10-02"})
        receipt = json.loads(arts.receipt_json)
        self.assertEqual(receipt["summary"]["total_incomplete"], 1)
        self.assertEqual(len(receipt["pending_checks"]), 2)
        self.assertEqual(receipt["violations"], [])
        self.assertEqual(validate_receipt(receipt), [])
        self.assertTrue(validate_bundle(build_bundle(arts))["valid"])

    def test_html_preserves_targets_and_explains_unknown_status(self):
        arts = build_artifacts({"scanner_input": scanner()})
        html = arts.html_bytes.decode()
        self.assertIn("Pending checks", html)
        self.assertIn("#first", html)
        self.assertIn("#second", html)
        self.assertIn("neither violations nor passes", html)
        self.assertIn("No reviewer approval is recorded", html)

    def test_empty_pending_field_is_explicit(self):
        receipt = json.loads(build_artifacts({
            "scanner_input": {"violations": [], "incomplete": []}
        }).receipt_json)
        self.assertEqual(receipt["pending_checks"], [])
        self.assertEqual(receipt["summary"]["total_incomplete"], 0)

    def test_duplicate_targets_are_deduplicated_per_check_not_across_checks(self):
        data = scanner()
        data["incomplete"][0]["nodes"].append({"target": ["#first"]})
        data["incomplete"].append(copy.deepcopy(data["incomplete"][0]))
        summary, _ = parse_axe_json(data)
        self.assertEqual(summary.total_incomplete, 2)
        self.assertEqual(len(summary.pending_checks), 4)

    def test_missing_target_is_unknown_not_invented_selector(self):
        summary, _ = parse_axe_json({"violations": [], "incomplete": [{}]})
        self.assertEqual(summary.pending_checks[0]["target"], "")
        self.assertEqual(summary.pending_checks[0]["id"], "unknown-check")

    def test_pending_shapes_reject_instead_of_stringifying(self):
        for field, value in (("id", {}), ("description", []), ("helpUrl", False),
                             ("nodes", {}), ("nodes", [False]),
                             ("nodes", [{"target": {"private": "value"}}])):
            with self.subTest(field=field, value=value):
                data = scanner()
                data["incomplete"][0][field] = value
                with self.assertRaises(ValueError):
                    parse_axe_json(data)

    def test_pending_arrays_and_nodes_are_bounded(self):
        for data in (
            {"violations": [], "incomplete": [{}] * (MAX_VIOLATIONS + 1)},
            {"violations": [], "incomplete": [{
                "nodes": [{}] * (MAX_NODES_PER_VIOLATION + 1)
            }]},
        ):
            with self.subTest(data_kind=len(data["incomplete"])):
                with self.assertRaises(LimitExceeded):
                    parse_axe_json(data)

    def test_pending_strings_are_escaped_and_unsafe_help_is_not_linked(self):
        data = scanner()
        data["incomplete"][0].update({
            "id": "<script>unsafe</script>", "description": "<img onerror=bad>",
            "helpUrl": "javascript:alert(1)",
            "nodes": [{"target": ["<svg/onload=bad>"]}],
        })
        html = build_artifacts({"scanner_input": data}).html_bytes.decode()
        self.assertNotIn("<script>unsafe</script>", html)
        self.assertIn("&lt;script&gt;unsafe&lt;/script&gt;", html)
        self.assertNotIn('href="javascript:', html)

    def test_pending_does_not_change_violation_fingerprint(self):
        data = scanner()
        data["violations"] = [{
            "id": "image-alt", "impact": "serious",
            "nodes": [{"target": ["#image"]}],
        }]
        one = json.loads(build_artifacts({"scanner_input": data}).receipt_json)
        data["incomplete"] = []
        two = json.loads(build_artifacts({"scanner_input": data}).receipt_json)
        self.assertEqual(one["violations"], two["violations"])

    def test_null_pending_remains_compatible(self):
        summary, _ = parse_axe_json({"violations": None, "incomplete": None})
        self.assertEqual(summary.pending_checks, [])

    def test_additive_pending_receipt_schema(self):
        from pathlib import Path
        import jsonschema
        root = Path(__file__).resolve().parents[1]
        data = scanner()
        data["violations"] = [{"id": "image-alt", "impact": None}]
        receipt = json.loads(build_artifacts({"scanner_input": data}).receipt_json)
        schema = json.loads((root / "schemas/receipt-1.2.schema.json").read_text(encoding="utf-8"))
        jsonschema.validate(receipt, schema)
        broken = copy.deepcopy(receipt)
        broken["pending_checks"][0]["status"] = "passed"
        self.assertTrue(validate_receipt(broken))
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(broken, schema)

    def test_manual_format_guidance_is_not_plain_prose(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        html = (root / "public/index.html").read_text(encoding="utf-8")
        self.assertIn("CSV or Markdown table", html)
        self.assertIn("Plain prose is not supported", html)

    def test_hosted_favicon_fallback_matches_real_asset(self):
        from pathlib import Path
        from api.public_assets import load
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(load("static/favicon.svg"),
                         (root / "public/static/favicon.svg").read_bytes())

    def test_http_headers_preserve_units_in_both_adapters(self):
        import http.client
        import os
        import threading
        from http.server import HTTPServer
        from unittest.mock import patch
        from api.handler import handler
        from app.main import Handler
        for adapter in (handler, Handler):
            with self.subTest(adapter=adapter.__module__):
                server = HTTPServer(("127.0.0.1", 0), adapter)
                port = server.server_address[1]
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                data = scanner()
                data["violations"] = [
                    {"id": "image-alt", "impact": None,
                     "nodes": [{"target": ["#a"]}, {"target": ["#b"]}]},
                    {"id": "custom-unmapped", "impact": "serious"},
                ]
                env = {"ALLOWED_HOSTS": f"127.0.0.1:{port}",
                       "ACCESSDOC_REQUIRE_AUTH": "false",
                       "ACCESSDOC_GENERATION_ENABLED": "true",
                       "RATE_LIMIT_PER_MINUTE": "100000"}
                with patch.dict(os.environ, env):
                    thread.start()
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                    try:
                        conn.request("POST", "/api/bundle", json.dumps({
                            "scanner_input": data,
                        }), {"Content-Type": "application/json"})
                        response = conn.getresponse()
                        bundle = response.read()
                        self.assertEqual(response.status, 200)
                        self.assertTrue(validate_bundle(bundle)["valid"])
                        self.assertEqual(response.getheader("X-AccessDoc-Finding-Count"), "2")
                        self.assertEqual(response.getheader("X-AccessDoc-Instance-Count"), "3")
                        self.assertEqual(response.getheader("X-AccessDoc-Unmapped-Count"), "1")
                        self.assertEqual(response.getheader("X-AccessDoc-Pending-Count"), "2")
                        conn.request("GET", "/static/favicon.svg")
                        icon = conn.getresponse()
                        self.assertEqual(icon.status, 200)
                        self.assertTrue(icon.getheader("Content-Type").startswith("image/svg+xml"))
                        self.assertIn(b"<svg", icon.read())
                    finally:
                        conn.close()
                        server.shutdown()
                        server.server_close()
                        thread.join(timeout=5)
                    self.assertFalse(thread.is_alive())