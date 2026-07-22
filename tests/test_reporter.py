"""Tests for PDF reporter."""
import unittest
from app.models import AuditSummary, AuditViolation
from app.reporter import generate_pdf_report


class TestReporter(unittest.TestCase):
    def _summary(self):
        return AuditSummary(critical=1, serious=2, moderate=1, minor=0,
                            total_violations=4, total_passes=10,
                            url="https://example.com", engine_version="4.11.2")

    def _violations(self):
        return [
            AuditViolation(id="image-alt", impact="critical",
                           description="Images must have alt text",
                           help_url="https://dequeuniversity.com",
                           wcag_scs=["1.1.1"], nodes=2),
            AuditViolation(id="color-contrast", impact="serious",
                           description="Color contrast too low",
                           help_url="https://dequeuniversity.com",
                           wcag_scs=["1.4.3"], nodes=5),
        ]

    def test_returns_bytes(self):
        pdf = generate_pdf_report(self._summary(), self._violations())
        self.assertIsInstance(pdf, bytes)

    def test_is_pdf_magic(self):
        pdf = generate_pdf_report(self._summary(), self._violations())
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_nonzero_size(self):
        pdf = generate_pdf_report(self._summary(), self._violations())
        self.assertGreater(len(pdf), 1000)

    def test_empty_violations(self):
        pdf = generate_pdf_report(self._summary(), [])
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_custom_client_name(self):
        pdf = generate_pdf_report(self._summary(), self._violations(),
                                   client_name="ACME Corp", agency_name="Audit Co",
                                   audit_date="2026-07-23")
        self.assertGreater(len(pdf), 1000)


if __name__ == "__main__":
    unittest.main()
