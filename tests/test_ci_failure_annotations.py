"""Synthetic report fixtures; diagnostic output never substitutes for test gates."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / 'scripts/report_test_failures.py'
spec = importlib.util.spec_from_file_location('failure_annotations', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class FailureAnnotationTests(unittest.TestCase):
    def report(self, text):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'result.xml'; p.write_text(text)
            return module.annotations(p)

    def test_failed_assertion_visible_but_credentials_filtered(self):
        with patch.dict(os.environ, {'SYNTHETIC_API_KEY': 'private-synthetic-canary'}):
            rows = self.report('<testsuite><testcase classname="tests.test_x.C" name="test_count"><failure>AssertionError: 0 != 1\nprivate-synthetic-canary Bearer synthetic-value sk-synthetic-test</failure></testcase></testsuite>')
        self.assertEqual(len(rows), 1)
        self.assertIn('AssertionError: 0 != 1%0A', rows[0])
        for secret in ('private-synthetic-canary', 'synthetic-value', 'sk-synthetic-test'):
            self.assertNotIn(secret, rows[0])

    def test_pass_and_skip_are_not_failures(self):
        self.assertEqual(self.report('<testsuite><testcase/><testcase><skipped/></testcase></testsuite>'), [])

    def test_annotation_and_failure_count_bounded(self):
        rows = self.report('<testsuite>' + ('<testcase name="n"><failure>' + 'x' * 5000 + '</failure></testcase>') * 25 + '</testsuite>')
        self.assertEqual(len(rows), 20)
        self.assertTrue(all(len(x) < 3200 for x in rows))

    def test_malformed_or_missing_report_is_generic(self):
        self.assertEqual(self.report('<invalid'), ['::error::Test failure report could not be parsed'])
        self.assertEqual(module.annotations('/nonexistent-synthetic-ci-report'), ['::error::Test failure report missing or exceeds diagnostic bound'])

    def test_annotation_control_characters_escaped(self):
        self.assertEqual(module.safe('a%\r\nb'), 'a%25%0D%0Ab')
