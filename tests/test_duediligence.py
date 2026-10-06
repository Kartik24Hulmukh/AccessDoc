import unittest
from app.receipt_builder import compute_finding_fingerprint
from app.duediligence import (
    build_due_diligence, render_due_diligence_md, DUE_DILIGENCE_SCHEMA_VERSION,
)

R1 = {
    "audit_date": "2026-01-10", "accessdoc_version": "0.7.0",
    "summary": {"critical": 3, "serious": 2, "moderate": 1, "minor": 0},
    "violations": [
        {"id": "image-alt", "target": "img.hero", "impact": "critical"},
        {"id": "label", "target": "#email", "impact": "serious"},
    ],
}
R2 = {
    "audit_date": "2026-04-10", "accessdoc_version": "0.7.0",
    "summary": {"critical": 0, "serious": 1, "moderate": 1, "minor": 0},
    "violations": [
        {"id": "label", "target": "#email", "impact": "serious"},
        {"id": "region", "target": "main", "impact": "moderate"},
    ],
}


# Explicit compatible supplied identities, not authenticated state or fixes.
for receipt in (R1, R2):
    receipt.update(schema_version="1.2", finding_fingerprint_version="1",
                   url="https://example.test/page", client_name="Synthetic",
                   engine_version="4.11.2", catalog_version="test")
    receipt["rule_ids"] = sorted({v["id"] for v in receipt["violations"]})
    for v in receipt["violations"]:
        v["source"] = "automated"
        v["finding_fingerprint"] = compute_finding_fingerprint(v["id"], v["source"], v["target"])


class TestDueDiligence(unittest.TestCase):
    def test_requires_receipts(self):
        with self.assertRaises(ValueError):
            build_due_diligence([])

    def test_rejects_all_invalid(self):
        with self.assertRaises(ValueError):
            build_due_diligence(["nope", 42, None])

    def test_sorts_out_of_order_receipts(self):
        rec = build_due_diligence([R2, R1])
        self.assertEqual(rec["period_start"], "2026-01-10")
        self.assertEqual(rec["period_end"], "2026-04-10")

    def test_classifies_findings(self):
        rec = build_due_diligence([R1, R2])
        self.assertEqual(rec["not_observed_count"], 1)   # image-alt not observed at end
        self.assertEqual(rec["persisting_count"], 1)   # label observed at both endpoints
        self.assertEqual(rec["introduced_count"], 1)   # region observed only at end

    def test_supplied_counts_decreased(self):
        rec = build_due_diligence([R1, R2])
        self.assertEqual(rec["trend"], "decreased")
        self.assertEqual(rec["blocking_before"], 5)
        self.assertEqual(rec["blocking_after"], 1)
        self.assertEqual(rec["blocking_delta"], -4)

    def test_supplied_counts_increased(self):
        rec = build_due_diligence([R2, R1])
        self.assertEqual(rec["trend"], "decreased")  # sorted by date, not order
        rec2 = build_due_diligence([
            dict(R1, audit_date="2026-01-01", summary={"critical": 0, "serious": 0, "moderate": 0, "minor": 0}),
            dict(R2, audit_date="2026-02-01", summary={"critical": 2, "serious": 0, "moderate": 0, "minor": 0}),
        ])
        self.assertEqual(rec2["trend"], "increased")

    def test_single_receipt_counts_unchanged(self):
        rec = build_due_diligence([R1])
        self.assertEqual(rec["trend"], "unchanged")
        self.assertEqual(rec["audits_in_record"], 1)

    def test_supplied_period_start_is_not_knowledge(self):
        rec = build_due_diligence([R2, R1])
        self.assertEqual(rec["period_start"], "2026-01-10")
        self.assertNotIn("knowledge_established", rec)

    def test_schema_version_present(self):
        self.assertEqual(build_due_diligence([R1])["schema_version"],
                         DUE_DILIGENCE_SCHEMA_VERSION)

    def test_tolerates_malformed_violations(self):
        bad = {"audit_date": "2026-01-01", "summary": {}, "violations": ["x", None, 5]}
        rec = build_due_diligence([bad])
        self.assertIsNone(rec["persisting_count"])
        self.assertEqual(rec["comparison_status"], "not-comparable")

    def test_markdown_renders_and_disclaims(self):
        md = render_due_diligence_md(build_due_diligence([R1, R2]))
        self.assertIn("# Due-Diligence Record", md)
        self.assertIn("not a conformance claim", md)
        self.assertIn("30-57%", md)
        self.assertIn("2026-01-10", md)

    def test_markdown_lists_endpoint_observations(self):
        md = render_due_diligence_md(build_due_diligence([R1, R2]))
        self.assertIn("Observed at both endpoints", md)
        self.assertIn("label", md)

    def test_deterministic_output(self):
        a = render_due_diligence_md(build_due_diligence([R1, R2]))
        b = render_due_diligence_md(build_due_diligence([R1, R2]))
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
