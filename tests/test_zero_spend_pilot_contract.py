"""Static deployment/documentation contracts; no host/provider calls."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(os.environ.get('ACCESSDOC_TEST_REPO', Path(__file__).resolve().parents[1]))

class ZeroSpendPilotContract(unittest.TestCase):
    def service(self):
        return yaml.safe_load((ROOT / 'render.yaml').read_text(encoding='utf-8'))['services'][0]
    def env(self):
        return {row['key']: row for row in self.service()['envVars']}
    def test_blueprint_explicitly_selects_free_compute(self):
        self.assertEqual(self.service().get('plan'), 'free')
        self.assertIs(self.service()['autoDeploy'], False)
    def test_blueprint_requires_private_pilot_auth(self):
        env = self.env()
        self.assertEqual(env.get('ACCESSDOC_REQUIRE_AUTH', {}).get('value'), 'true')
        self.assertIs(env.get('ACCESSDOC_API_KEY', {}).get('sync'), False)
        self.assertNotIn('value', env['ACCESSDOC_API_KEY'])
    def test_blueprint_disables_http_remediation(self):
        self.assertEqual(self.env().get('ACCESSDOC_REMEDIATION_ENABLED', {}).get('value'), 'false')
    def test_blueprint_does_not_install_provider_credentials(self):
        self.assertNotIn('MELIOUS_API_KEY', self.env())
    def test_origins_are_operator_supplied_not_a_compute_plan(self):
        origins = self.env()['ALLOWED_ORIGINS']
        self.assertIs(origins['sync'], False)
        self.assertNotIn('value', origins)
    def test_roadmap_agrees_with_existing_mit_license(self):
        self.assertTrue((ROOT / 'LICENSE').read_text(encoding='utf-8').startswith('MIT License'))
        text = (ROOT / 'ROADMAP.md').read_text(encoding='utf-8')
        self.assertIn('MIT-licensed community/security/release', text)
        self.assertNotIn('Apache-2.0 community/security/release package', text)
    def test_readme_does_not_deny_implemented_serverless_route(self):
        text = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertNotIn('Not yet exposed on the Vercel serverless adapter.', text)
        self.assertIn('ACCESSDOC_STRICT_GATEWAY', text)
        self.assertIn('ACCESSDOC_REMEDIATION_ENABLED=false', text)
    def test_documentation_distinguishes_adapter_queue_settings(self):
        text = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertIn('GENERATION_QUEUE_TIMEOUT_SECONDS', text)
        self.assertIn('REMEDIATION_QUEUE_TIMEOUT_SECONDS', text)
        self.assertIn('local service', text)
        self.assertIn('Vercel adapter', text)
    def test_readme_does_not_promise_undeclared_platform_duration(self):
        text = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertIn('not declared by `vercel.json`', text)
        self.assertNotIn('are never cut off by the platform', text)
        self.assertNotIn('maxDuration', (ROOT / 'vercel.json').read_text(encoding='utf-8'))
    def test_documentation_distinguishes_pilot_and_production(self):
        text = (ROOT / 'docs/ZERO_SPEND_PILOT.md').read_text(encoding='utf-8')
        for phrase in ('not production approval', 'budget alert is not a spending cap',
                       'not tenant isolation', 'ACCESSDOC_REMEDIATION_ENABLED=false',
                       'No upstream provider credential', 'capability'):
            self.assertIn(phrase, text)
    def test_recognized_controls_keep_generation_ready_with_remediation_off(self):
        from app.http_policy import operation_error, readiness_reasons
        with patch.dict(os.environ, {'ACCESSDOC_REQUIRE_AUTH':'true',
                'ACCESSDOC_API_KEY':'synthetic-pilot-key',
                'ACCESSDOC_GENERATION_ENABLED':'true',
                'ACCESSDOC_REMEDIATION_ENABLED':'false'}, clear=True):
            self.assertEqual(operation_error(remediation=True), (503, 'REMEDIATION_DISABLED'))
            self.assertIsNone(operation_error())
            self.assertEqual(readiness_reasons(), [])
    def test_required_auth_without_secret_is_not_ready(self):
        from app.http_policy import readiness_reasons
        with patch.dict(os.environ, {'ACCESSDOC_REQUIRE_AUTH':'true'}, clear=True):
            self.assertIn('AUTH_NOT_CONFIGURED', readiness_reasons())

if __name__ == '__main__':
    unittest.main()
