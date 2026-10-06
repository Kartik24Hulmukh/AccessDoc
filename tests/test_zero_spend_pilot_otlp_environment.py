"""Inspect launch-boundary environment; never launch a provider or collector."""
import os
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
OTLP = tuple('OTEL_EXPORTER_OTLP' + scope + '_' + name
             for scope in ('', '_TRACES', '_METRICS', '_LOGS')
             for name in ('ENDPOINT', 'HEADERS'))


class ZeroSpendPilotOTLPEnvironmentTests(unittest.TestCase):
    def test_inherited_endpoints_and_headers_removed_at_exec_boundary(self):
        env = {key: 'synthetic-collector-canary' for key in OTLP}
        env.update(ACCESSDOC_API_KEY='synthetic-pilot-key', MELIOUS_API_KEY='synthetic-model-key',
                   ACCESSDOC_API_KEYS='synthetic-legacy-key', HOST='0.0.0.0', PORT='8001',
                   OTEL_SERVICE_NAME='local-synthetic-service')
        def inspect_exec(program, args):
            for key in OTLP + ('MELIOUS_API_KEY', 'ACCESSDOC_API_KEYS'):
                self.assertNotIn(key, os.environ)
            self.assertEqual(os.environ['ACCESSDOC_REQUIRE_AUTH'], 'true')
            self.assertEqual(os.environ['ACCESSDOC_REMEDIATION_ENABLED'], 'false')
            self.assertEqual(os.environ['HOST'], '127.0.0.1')
            self.assertEqual(os.environ['ALLOWED_HOSTS'], '127.0.0.1:8001,localhost:8001')
            self.assertEqual(os.environ['OTEL_SERVICE_NAME'], 'local-synthetic-service')
            self.assertEqual(args[-2:], ['-m', 'app.main'])
        with patch.dict(os.environ, env, clear=True), patch('os.chdir'), \
             patch('os.execv', side_effect=inspect_exec) as execute:
            runpy.run_path(str(ROOT/'scripts/start_zero_spend_pilot.py'), run_name='__main__')
            execute.assert_called_once()

    def test_missing_pilot_key_never_executes_even_with_collector_credentials(self):
        with patch.dict(os.environ, {key: 'synthetic-collector-only' for key in OTLP}, clear=True), \
             patch('os.execv') as execute, self.assertRaises(SystemExit):
            runpy.run_path(str(ROOT/'scripts/start_zero_spend_pilot.py'), run_name='__main__')
        execute.assert_not_called()
