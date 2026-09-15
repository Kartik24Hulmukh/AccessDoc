"""Keep the cold-start runner aligned with the public bundle service."""
import importlib.util
from pathlib import Path
import unittest


class StressEntrypointTests(unittest.TestCase):
    def test_one_request_uses_current_receipt_schema(self):
        path = Path(__file__).resolve().parents[1] / "scripts/serverless_stress.py"
        spec = importlib.util.spec_from_file_location("serverless_stress", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        ms, size, digest = module.one(0)
        self.assertGreaterEqual(ms, 0)
        self.assertGreater(size, 0)
        self.assertEqual(len(digest), 64)
