"""The evidence workflow must install the same required runtime graph as CI."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]

class EvidenceDependenciesTests(unittest.TestCase):
    def test_evidence_gate_uses_shared_runtime_dependency_graph(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/accessdoc-action.yml').read_text())
        step = next(s for s in workflow['jobs']['accessdoc-evidence']['steps']
                    if s.get('name') == 'Install dependencies')
        self.assertIn('pip install --requirement requirements-dev.txt', step['run'])
        self.assertIn('-r requirements.txt', (ROOT / 'requirements-dev.txt').read_text())
        runtime = (ROOT / 'requirements.txt').read_text()
        for dependency in ('aiohttp>=', 'aiodns>=', 'requests>=', 'reportlab>='):
            self.assertIn(dependency, runtime)
