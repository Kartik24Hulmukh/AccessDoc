"""Portable PDF test reader: required dev dependency, no Poppler or fallback."""
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf.errors import PdfReadError

from app.models import AuditSummary, AuditViolation
from app.reporter import generate_pdf_report
from tests.test_cross_export_source_fidelity import pdf_metadata, pdf_text


class PdfTextExtractionPortabilityTests(unittest.TestCase):
    def test_actual_pdf_text_metadata_and_bytes_without_cli(self):
        findings = [AuditViolation(id='keyboard-review', impact='serious',
            description='Manual keyboard observation', help_url='', wcag_scs=['2.1.1'],
            source='manual', target='#dialog')]
        summary = AuditSummary(total_violations=1, manual_findings=1)
        first = generate_pdf_report(summary, findings)
        self.assertEqual(first, generate_pdf_report(summary, findings))
        digest = hashlib.sha256(first).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'evidence.pdf'
            path.write_bytes(first)
            with patch('subprocess.check_output', side_effect=AssertionError('No PDF CLI allowed')):
                text, metadata = pdf_text(path), pdf_metadata(path)
            for expected in ('Supplied Accessibility Evidence Report', 'DRAFT - UNREVIEWED',
                             'Manual keyboard observation', 'Supplied manual findings: 1',
                             'No reviewer approval is recorded'):
                self.assertIn(expected, text)
            self.assertIn('Supplied accessibility evidence', metadata)
            self.assertNotIn('PDF/UA', text + metadata)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_malformed_pdf_is_error_not_empty_text_or_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'invalid.pdf'
            path.write_bytes(b'not a PDF')
            for helper in (pdf_text, pdf_metadata):
                with self.subTest(helper=helper.__name__), self.assertRaises(PdfReadError):
                    helper(path)

    def test_missing_dev_dependency_is_explicit_import_failure(self):
        target = Path(__file__).with_name('test_cross_export_source_fidelity.py')
        code = '''import builtins, runpy, sys
original = builtins.__import__
def blocked(name, *args, **kwargs):
    if name == "pypdf" or name.startswith("pypdf."):
        raise ModuleNotFoundError("Required test dependency pypdf missing")
    return original(name, *args, **kwargs)
builtins.__import__ = blocked
runpy.run_path(sys.argv[1])
'''
        result = subprocess.run([sys.executable, '-c', code, str(target)],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ModuleNotFoundError: Required test dependency pypdf missing', result.stderr)
