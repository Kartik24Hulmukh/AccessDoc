"""Tests for in-toto attestation module."""
import base64
import json
import unittest
from app.intoto import (
    build_statement, build_dsse_envelope, build_intoto_bundle,
    verify_statement_subjects, STATEMENT_TYPE, PREDICATE_TYPE, _sha256
)


FILES_ = {"report.pdf": b"PDF content", "report.html": b"<html>test</html>"}


class TestInToto(unittest.TestCase):
    def test_build_statement_type(self):
        stmt = build_statement(FILES_, {"buildType": "test"})
        self.assertEqual(stmt["_type"], STATEMENT_TYPE)

    def test_build_statement_predicate_type(self):
        stmt = build_statement(FILES_, {"buildType": "test"})
        self.assertEqual(stmt["predicateType"], PREDICATE_TYPE)

    def test_build_statement_subjects(self):
        stmt = build_statement(FILES_, {})
        names = {s["name"] for s in stmt["subject"]}
        self.assertEqual(names, set(FILES_.keys()))

    def test_build_statement_digest_correct(self):
        stmt = build_statement(FILES_, {})
        for s in stmt["subject"]:
            expected = _sha256(FILES_[s["name"]])
            self.assertEqual(s["digest"]["sha256"], expected)

    def test_dsse_envelope_structure(self):
        stmt = build_statement(FILES_, {})
        env = build_dsse_envelope(stmt)
        self.assertIn("payloadType", env)
        self.assertIn("payload", env)
        self.assertIn("signatures", env)
        self.assertEqual(env["signatures"], [])

    def test_dsse_envelope_payload_decodable(self):
        stmt = build_statement(FILES_, {})
        env = build_dsse_envelope(stmt)
        decoded = json.loads(base64.b64decode(env["payload"]))
        self.assertEqual(decoded["_type"], STATEMENT_TYPE)

    def test_build_intoto_bundle_returns_bytes(self):
        result = build_intoto_bundle(FILES_)
        self.assertIsInstance(result, bytes)

    def test_build_intoto_bundle_is_valid_json(self):
        result = build_intoto_bundle(FILES_)
        parsed = json.loads(result)
        self.assertIn("payloadType", parsed)

    def test_build_intoto_bundle_with_extra_meta(self):
        result = build_intoto_bundle(FILES_, {"custom_key": "custom_value"})
        parsed = json.loads(result)
        stmt = json.loads(base64.b64decode(parsed["payload"]))
        self.assertIn("custom_key", stmt["predicate"])

    def test_verify_statement_subjects_all_match(self):
        stmt = build_statement(FILES_, {})
        mismatches = verify_statement_subjects(stmt, FILES_)
        self.assertEqual(mismatches, [])

    def test_verify_statement_subjects_mismatch(self):
        stmt = build_statement(FILES_, {})
        tampered = dict(FILES_)
        tampered["report.pdf"] = b"tampered content"
        mismatches = verify_statement_subjects(stmt, tampered)
        self.assertEqual(len(mismatches), 1)
        self.assertIn("report.pdf", mismatches[0])


if __name__ == "__main__":
    unittest.main()
