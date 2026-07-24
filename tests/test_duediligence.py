import unittest
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
        self.assertEqual(rec["remediated_count"], 1)   # image-alt fixed
        self.assertEqual(rec["persisting_count"], 1)   # label still there
        self.assertEqual(rec["introduced_count"], 1)   # region is new

    def test_trend_improving(self):
        rec = build_due_diligence([R1, R2])
        self.assertEqual(rec["trend"], "improving")
        self.assertEqual(rec["blocking_before"], 5)
        self.assertEqual(rec["blocking_after"], 1)
        self.assertEqual(rec["blocking_delta"], -4)

    def test_trend_regressing(self):
        rec = build_due_diligence([R2, R1])
        self.assertEqual(rec["trend"], "improving")  # sorted by date, not order
        rec2 = build_due_diligence([
            dict(R1, audit_date="2026-01-01", summary={"critical": 0, "serious": 0, "moderate": 0, "minor": 0}),
            dict(R2, audit_date="2026-02-01", summary={"critical": 2, "serious": 0, "moderate": 0, "minor": 0}),
        ])
        self.assertEqual(rec2["trend"], "regressing")

    def test_single_receipt_is_flat(self):
        rec = build_due_diligence([R1])
        self.assertEqual(rec["trend"], "flat")
        self.assertEqual(rec["audits_in_record"], 1)

    def test_knowledge_date_is_earliest(self):
        rec = build_due_diligence([R2, R1])
        self.assertEqual(rec["knowledge_established"], "2026-01-10")

    def test_schema_version_present(self):
        self.assertEqual(build_due_diligence([R1])["schema_version"],
                         DUE_DILIGENCE_SCHEMA_VERSION)

    def test_tolerates_malformed_violations(self):
        bad = {"audit_date": "2026-01-01", "summary": {}, "violations": ["x", None, 5]}
        rec = build_due_diligence([bad])
        self.assertEqual(rec["persisting_count"], 0)

    def test_markdown_renders_and_disclaims(self):
        md = render_due_diligence_md(build_due_diligence([R1, R2]))
        self.assertIn("# Due-Diligence Record", md)
        self.assertIn("not a conformance claim", md)
        self.assertIn("30-57%", md)
        self.assertIn("2026-01-10", md)

    def test_markdown_lists_unresolved(self):
        md = render_due_diligence_md(build_due_diligence([R1, R2]))
        self.assertIn("Unresolved barriers", md)
        self.assertIn("label", md)

    def test_deterministic_output(self):
        a = render_due_diligence_md(build_due_diligence([R1, R2]))
        b = render_due_diligence_md(build_due_diligence([R1, R2]))
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
