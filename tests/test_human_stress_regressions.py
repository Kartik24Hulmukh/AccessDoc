"""Regression coverage for independently reproduced stress-test findings."""
import json
import unittest

from app.limits import LimitExceeded, MAX_HTTP_BODY_BYTES, MAX_STRING_CHARS
from app.parser import parse_axe_json
from app.reporter import display_engine_version


class TestScannerEvidenceValidation(unittest.TestCase):
    def test_scalar_violation_is_rejected_instead_of_silently_dropped(self):
        with self.assertRaisesRegex(ValueError, r"violations\[0\] must be an object"):
            parse_axe_json({"violations": [42]})

    def test_violation_requires_nonempty_rule_id(self):
        for payload in ({"violations": [{}]}, {"violations": [{"id": "  "}]}):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(ValueError, "non-empty string"):
                    parse_axe_json(payload)

    def test_nodes_require_list_of_objects(self):
        payloads = (
            {"violations": [{"id": "image-alt", "nodes": "not-a-list"}]},
            {"violations": [{"id": "image-alt", "nodes": [42]}]},
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    parse_axe_json(payload)

    def test_explicit_null_violations_compatibility_is_preserved(self):
        summary, violations = parse_axe_json({"violations": None})
        self.assertEqual(summary.total_violations, 0)
        self.assertEqual(violations, [])

    def test_every_scanner_string_is_bounded(self):
        payload = {
            "violations": [],
            "unrecognized": "x" * (MAX_STRING_CHARS + 1),
        }
        with self.assertRaises(LimitExceeded):
            parse_axe_json(payload)

    def test_serialized_scanner_input_has_a_byte_ceiling(self):
        raw = json.dumps({
            "violations": [],
            "padding": "x" * MAX_HTTP_BODY_BYTES,
        })
        with self.assertRaises(LimitExceeded):
            parse_axe_json(raw)


class TestScannerProvenanceLabels(unittest.TestCase):
    def test_missing_engine_version_stays_unknown(self):
        self.assertEqual(
            display_engine_version(""),
            "unknown / not supplied",
        )

    def test_observed_engine_version_is_preserved(self):
        self.assertEqual(display_engine_version("4.11.2"), "4.11.2")


if __name__ == "__main__":
    unittest.main()
