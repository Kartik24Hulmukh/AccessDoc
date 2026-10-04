"""Launcher policy contracts; live synthetic receipt is separate evidence."""
import os
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
class LocalPilotLauncherTests(unittest.TestCase):
    def test_missing_key_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(SystemExit):
            runpy.run_path(str(ROOT/'scripts/start_zero_spend_pilot.py'), run_name='__main__')
    def test_upstream_secret_removed_and_loopback_enforced(self):
        env = {'ACCESSDOC_API_KEY':'synthetic-pilot-only', 'MELIOUS_API_KEY':'synthetic-upstream-only', 'HOST':'0.0.0.0', 'PORT':'8000'}
        def inspect_exec(program, arguments):
            self.assertNotIn('MELIOUS_API_KEY', os.environ)
            self.assertEqual(os.environ['HOST'], '127.0.0.1')
            self.assertEqual(os.environ['ACCESSDOC_REQUIRE_AUTH'], 'true')
            self.assertEqual(os.environ['ACCESSDOC_REMEDIATION_ENABLED'], 'false')
            self.assertEqual(os.environ['REPORT_TTL_SECONDS'], '1800')
            self.assertEqual(arguments[-2:], ['-m', 'app.main'])
        with patch.dict(os.environ, env, clear=True), patch('os.chdir'), patch('os.execv', side_effect=inspect_exec) as execute:
            runpy.run_path(str(ROOT/'scripts/start_zero_spend_pilot.py'), run_name='__main__')
            execute.assert_called_once()
