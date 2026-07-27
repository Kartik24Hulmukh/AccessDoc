"""Receipt integrity, chain verification, limit parity, and target coverage.

These tests exist because of a specific, documented failure in this project's
history: a release report claimed schema 1.2 with per-finding identity while the
shipped code emitted 1.1, and nothing in the test suite could tell the
difference. Each test below is written so that reverting the corresponding
behaviour fails loudly.

What is deliberately NOT claimed here: none of this proves authorship or time.
A tamperer who edits a finding AND recomputes its fingerprint AND rebuilds the
manifest produces a self-consistent bundle; catching that requires the Sigstore
signature. The tests assert exactly the property each layer provides.
"""
import json
import os
import subprocess
import sys
import unittest
import zipfile
from io import BytesIO
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.bundle import build_bundle, validate_bundle
from app.limits import (
    LimitExceeded,
    MAX_NODES_PER_VIOLATION,
    MAX_VIOLATIONS,
    OVERSIZE_ENV_VAR,
    enforce_axe_limits,
    limits_summary,
)
from app.parser import parse_axe_json
from app.receipt_builder import (
    FINDING_FINGERPRINT_VERSION,
    SCHEMA_VERSION,
    compute_finding_fingerprint,
)
from app.receipt_validate import (
    precision_of,
    validate_receipt,
    verify_receipt_chain,
)
from app.sarif import FINGERPRINT_KEY, generate_sarif
from app.service import build_artifacts

FIXTURE = os.path.join(ROOT, "fixtures", "axe-sample.json")


def _fixture_text():
    with open(FIXTURE, "r", encoding="utf-8") as f:
        return f.read()


def _body(**extra):
    body = {
        "scanner_input": _fixture_text(),
        "client_name": "Integrity Test Client",
        "audit_date": "2026-01-15",
        "format_hint": "axe",
    }
    body.update(extra)
    return body


def _receipt_from_bundle(zip_bytes):
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        return json.loads(zf.read("receipt.json"))


class TestFixtureTargetCoverage(unittest.TestCase):
    """The shipped demo fixture must exercise REAL selectors.

    Before beta.5 every node in axe-sample.json carried only `html`, so every
    production and CI receipt fell back to `<rule>:no-target`. Target-level
    identity was therefore proven only in unit tests and never in the artifact
    a buyer actually downloads.
    """

    def setUp(self):
        self.data = json.loads(_fixture_text())

    def test_every_fixture_node_declares_a_target(self):
        for violation in self.data["violations"]:
            for index, node in enumerate(violation["nodes"]):
                self.assertIn(
                    "target", node,
                    f"{violation['id']} node[{index}] has no target; the demo "
                    f"artifact would fall back to no-target identity",
                )
                self.assertTrue(
                    isinstance(node["target"], list) and node["target"],
                    f"{violation['id']} node[{index}] target must be a "
                    f"non-empty list",
                )

    def test_parsed_fixture_has_no_fallback_identities(self):
        _summary, violations = parse_axe_json(_fixture_text())
        fallbacks = [v.target for v in violations if ":no-target" in v.target]
        self.assertEqual(
            fallbacks, [],
            "the demo fixture must not produce fallback identities",
        )

    def test_multi_node_rules_produce_distinct_identities(self):
        _summary, violations = parse_axe_json(_fixture_text())
        contrast = [v for v in violations if v.id == "color-contrast"]
        self.assertGreaterEqual(len(contrast), 2)
        targets = {v.target for v in contrast}
        self.assertEqual(
            len(targets), len(contrast),
            "two contrast findings on different elements must have different "
            "targets, otherwise they collapse into one identity",
        )
        fingerprints = {
            compute_finding_fingerprint(v.id, v.source, v.target)
            for v in contrast
        }
        self.assertEqual(len(fingerprints), len(contrast))


class TestGeneratedReceiptIsValid(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.artifacts = build_artifacts(_body())
        cls.bundle = build_bundle(cls.artifacts)
        cls.receipt = _receipt_from_bundle(cls.bundle)

    def test_receipt_is_schema_1_2(self):
        self.assertEqual(self.receipt["schema_version"], SCHEMA_VERSION)
        self.assertEqual(self.receipt["schema_version"], "1.2")

    def test_receipt_declares_fingerprint_version(self):
        self.assertEqual(
            str(self.receipt["finding_fingerprint_version"]),
            FINDING_FINGERPRINT_VERSION,
        )

    def test_receipt_validates_strictly(self):
        self.assertEqual(validate_receipt(self.receipt), [])

    def test_receipt_reaches_target_level_precision(self):
        self.assertEqual(precision_of(self.receipt), "target-level")

    def test_every_fingerprint_is_full_length_lowercase_hex(self):
        for violation in self.receipt["violations"]:
            fingerprint = violation["finding_fingerprint"]
            self.assertEqual(len(fingerprint), 64)
            self.assertEqual(fingerprint, fingerprint.lower())
            int(fingerprint, 16)  # raises if not hex

    def test_bundle_validates_end_to_end(self):
        self.assertEqual(validate_bundle(self.bundle), {"valid": True,
                                                        "errors": []})


class TestReceiptTamperRejection(unittest.TestCase):
    """Tampering must be REJECTED, not merely observable in a diff."""

    def setUp(self):
        self.receipt = _receipt_from_bundle(build_bundle(build_artifacts(_body())))

    def test_retargeted_finding_is_rejected(self):
        self.receipt["violations"][0]["target"] = "#somewhere-else"
        errors = validate_receipt(self.receipt)
        self.assertTrue(
            any("does not match its content" in e for e in errors), errors
        )

    def test_relabelled_rule_is_rejected(self):
        self.receipt["violations"][0]["id"] = "a-friendlier-rule"
        errors = validate_receipt(self.receipt)
        self.assertTrue(errors)

    def test_source_laundering_is_rejected(self):
        # Recasting a manual finding as an automated one changes the canonical
        # triple, so the stored fingerprint can no longer re-derive.
        self.receipt["violations"][0]["source"] = "not-the-real-source"
        self.assertTrue(validate_receipt(self.receipt))

    def test_truncated_fingerprint_is_rejected(self):
        self.receipt["violations"][0]["finding_fingerprint"] = "abc123"
        errors = validate_receipt(self.receipt)
        self.assertTrue(any("64-character" in e for e in errors), errors)

    def test_uppercase_fingerprint_is_rejected(self):
        original = self.receipt["violations"][0]["finding_fingerprint"]
        self.receipt["violations"][0]["finding_fingerprint"] = original.upper()
        self.assertTrue(validate_receipt(self.receipt))

    def test_dropped_rule_id_is_rejected(self):
        self.receipt["rule_ids"] = self.receipt["rule_ids"][:-1]
        errors = validate_receipt(self.receipt)
        self.assertTrue(
            any("rule_ids does not agree" in e for e in errors), errors
        )

    def test_negative_summary_count_is_rejected(self):
        self.receipt["summary"]["critical"] = -1
        self.assertTrue(validate_receipt(self.receipt))

    def test_downgraded_schema_version_is_rejected(self):
        self.receipt["schema_version"] = "9.9"
        errors = validate_receipt(self.receipt)
        self.assertTrue(any("unsupported schema_version" in e for e in errors))

    def test_legacy_receipt_passes_in_lenient_mode(self):
        legacy = {"schema_version": "1.1", "rule_ids": ["image-alt"],
                  "summary": {"total_violations": 1}}
        self.assertEqual(validate_receipt(legacy, strict=False), [])
        self.assertEqual(precision_of(legacy), "rule-level")


class TestResealedBundleIsRejected(unittest.TestCase):
    """A bundle whose digests all agree can still be internally dishonest.

    Simulated by generating with a fingerprint function that returns a
    well-formed but incorrect digest. The manifest and attestation are built
    over those exact bytes, so every digest check passes. Only fingerprint
    re-derivation catches it.
    """

    def test_wrong_but_wellformed_fingerprints_fail_validation(self):
        bogus = "0" * 64
        with mock.patch(
            "app.receipt_builder.compute_finding_fingerprint",
            return_value=bogus,
        ):
            bundle = build_bundle(build_artifacts(_body()))

        receipt = _receipt_from_bundle(bundle)
        self.assertEqual(receipt["violations"][0]["finding_fingerprint"], bogus)

        result = validate_bundle(bundle)
        self.assertFalse(
            result["valid"],
            "digest-consistent but self-inconsistent receipt must not validate",
        )
        self.assertTrue(
            any("finding_fingerprint" in e for e in result["errors"]),
            result["errors"],
        )


class TestChainVerification(unittest.TestCase):

    def _receipt(self, audit_date, targets):
        violations = []
        for target in targets:
            violations.append({
                "id": "color-contrast",
                "impact": "serious",
                "source": "axe",
                "target": target,
                "finding_fingerprint": compute_finding_fingerprint(
                    "color-contrast", "axe", target
                ),
            })
        return {
            "schema_version": "1.2",
            "accessdoc_version": "test",
            "axe_core_verified_version": "4.11.2",
            "catalog_version": "test",
            "coverage_note": "Automated scans detect a subset of WCAG issues.",
            "audit_date": audit_date,
            "client_name": "Chain Client",
            "url": "https://example.com",
            "engine_version": "4.11.2",
            "summary": {
                "critical": 0, "serious": len(targets), "moderate": 0,
                "minor": 0, "total_violations": len(targets),
                "total_passes": 0, "manual_findings": 0,
            },
            "rule_ids": ["color-contrast"] if targets else [],
            "finding_fingerprint_version": FINDING_FINGERPRINT_VERSION,
            "violations": violations,
        }

    def test_honest_chain_is_valid_at_target_level(self):
        chain = [
            self._receipt("2026-01-01", ["#a", "#b"]),
            self._receipt("2026-02-01", ["#a"]),
        ]
        result = verify_receipt_chain(chain)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["comparison_precision"], "target-level")

    def test_backdated_link_is_rejected(self):
        chain = [
            self._receipt("2026-02-01", ["#a"]),
            self._receipt("2026-01-01", ["#a"]),
        ]
        result = verify_receipt_chain(chain)
        self.assertFalse(result["valid"])
        self.assertTrue(
            any("chronological" in e for e in result["errors"]),
            result["errors"],
        )

    def test_tampered_link_invalidates_the_chain(self):
        chain = [
            self._receipt("2026-01-01", ["#a"]),
            self._receipt("2026-02-01", ["#a"]),
        ]
        chain[0]["violations"][0]["target"] = "#rewritten"
        result = verify_receipt_chain(chain)
        self.assertFalse(result["valid"])
        self.assertTrue(any("receipt[0]" in e for e in result["errors"]))

    def test_precision_degrades_to_the_weakest_link(self):
        chain = [
            {"schema_version": "1.1", "audit_date": "2026-01-01",
             "rule_ids": ["color-contrast"], "summary": {}},
            self._receipt("2026-02-01", ["#a"]),
        ]
        result = verify_receipt_chain(chain)
        self.assertEqual(result["comparison_precision"], "rule-level")
        self.assertTrue(
            any("weakest link" in w for w in result["warnings"]),
            result["warnings"],
        )

    def test_empty_chain_is_invalid(self):
        self.assertFalse(verify_receipt_chain([])["valid"])

    def test_chain_always_states_its_limits(self):
        result = verify_receipt_chain([self._receipt("2026-01-01", ["#a"])])
        joined = " ".join(result["warnings"])
        self.assertIn("not independently timestamped", joined)
        self.assertIn("Sigstore", joined)


class TestLimitParity(unittest.TestCase):
    """The CLI and the HTTP API must agree on what a valid input is."""

    def tearDown(self):
        os.environ.pop(OVERSIZE_ENV_VAR, None)

    def test_violation_ceiling_is_enforced_in_the_shared_parser(self):
        payload = {"violations": [
            {"id": f"rule-{i}", "impact": "minor", "nodes": []}
            for i in range(MAX_VIOLATIONS + 1)
        ]}
        with self.assertRaises(LimitExceeded):
            parse_axe_json(json.dumps(payload))

    def test_at_the_ceiling_is_accepted(self):
        enforce_axe_limits([{"id": "x", "nodes": []}] * MAX_VIOLATIONS)

    def test_per_violation_node_ceiling_is_enforced(self):
        with self.assertRaises(LimitExceeded) as ctx:
            enforce_axe_limits([
                {"id": "x", "nodes": [{}] * (MAX_NODES_PER_VIOLATION + 1)}
            ])
        self.assertEqual(ctx.exception.limit_name, "MAX_NODES_PER_VIOLATION")

    def test_limit_exceeded_is_a_value_error(self):
        # Existing callers catch ValueError; the new type must not slip past.
        self.assertTrue(issubclass(LimitExceeded, ValueError))

    def test_opt_out_is_explicit_and_env_scoped(self):
        payload = {"violations": [
            {"id": f"rule-{i}", "impact": "minor", "nodes": []}
            for i in range(MAX_VIOLATIONS + 1)
        ]}
        os.environ[OVERSIZE_ENV_VAR] = "1"
        summary, violations = parse_axe_json(json.dumps(payload))
        self.assertGreater(summary.total_violations, MAX_VIOLATIONS)

    def test_http_surface_cannot_be_opted_out(self):
        os.environ[OVERSIZE_ENV_VAR] = "1"
        with self.assertRaises(LimitExceeded):
            enforce_axe_limits(
                [{"id": "x", "nodes": []}] * (MAX_VIOLATIONS + 1),
                allow_oversized=False,
            )

    def test_limits_summary_documents_the_http_asymmetry(self):
        summary = limits_summary()
        self.assertFalse(summary["oversize_opt_out_available_on_http"])
        self.assertEqual(summary["max_violations"], MAX_VIOLATIONS)


class TestSarifFingerprints(unittest.TestCase):
    """SARIF results must carry stable identity so alerts do not churn."""

    @classmethod
    def setUpClass(cls):
        cls.summary, cls.violations = parse_axe_json(_fixture_text())
        cls.sarif = json.loads(generate_sarif(cls.summary, cls.violations))
        cls.results = cls.sarif["runs"][0]["results"]

    def test_every_result_has_a_partial_fingerprint(self):
        for result in self.results:
            self.assertIn(FINGERPRINT_KEY, result["partialFingerprints"])

    def test_partial_fingerprints_match_the_receipt_derivation(self):
        for result, violation in zip(self.results, self.violations):
            self.assertEqual(
                result["partialFingerprints"][FINGERPRINT_KEY],
                compute_finding_fingerprint(
                    violation.id, violation.source, violation.target
                ),
            )

    def test_distinct_elements_get_distinct_fingerprints(self):
        fingerprints = [
            r["partialFingerprints"][FINGERPRINT_KEY] for r in self.results
        ]
        self.assertEqual(len(fingerprints), len(set(fingerprints)))

    def test_results_expose_the_element_as_a_logical_location(self):
        for result, violation in zip(self.results, self.violations):
            logical = result["locations"][0]["logicalLocations"][0]
            self.assertEqual(logical["fullyQualifiedName"], violation.target)


class TestCliIntegrityCommands(unittest.TestCase):
    """The verification path must be usable by someone who distrusts us."""

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, os.path.join(ROOT, "cli.py"), *args],
            capture_output=True, text=True, cwd=ROOT, timeout=180,
        )

    def test_limits_command_emits_json(self):
        proc = self._run("limits")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("max_violations", json.loads(proc.stdout))

    def test_receipt_check_passes_on_a_generated_receipt(self):
        import tempfile
        receipt = _receipt_from_bundle(build_bundle(build_artifacts(_body())))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "receipt.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(receipt, f)
            proc = self._run("receipt-check", path)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        out = json.loads(proc.stdout)
        self.assertTrue(out["valid"])
        self.assertEqual(out["comparison_precision"], "target-level")

    def test_receipt_check_fails_on_a_tampered_receipt(self):
        import tempfile
        receipt = _receipt_from_bundle(build_bundle(build_artifacts(_body())))
        receipt["violations"][0]["target"] = "#moved"
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "receipt.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(receipt, f)
            proc = self._run("receipt-check", path)
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertFalse(json.loads(proc.stdout)["valid"])


if __name__ == "__main__":
    unittest.main()
