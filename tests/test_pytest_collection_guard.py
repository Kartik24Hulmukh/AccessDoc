"""Pin pytest collection to tests/ so a bare `pytest` cannot import scripts.

Regression: running `pytest` from the repo root collected
scripts/stress_test.py (default *_test.py pattern); its module-level
sys.exit() raised SystemExit during collection -> INTERNALERROR, 0 tests run.
"""
import subprocess
import sys
try:  # py>=3.11
    import tomllib
except ModuleNotFoundError:  # requires-python is >=3.10
    tomllib = None
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class PytestCollectionGuard(unittest.TestCase):
    @unittest.skipIf(tomllib is None, "tomllib needs Python 3.11+")
    def test_testpaths_pinned_to_tests(self):
        cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        opts = cfg["tool"]["pytest"]["ini_options"]
        self.assertEqual(opts["testpaths"], ["tests"])

    @unittest.skipIf(importlib.util.find_spec("pytest") is None,
                     "pytest not installed (unittest-only runner, e.g. accessdoc-evidence)")
    def test_bare_collect_from_root_never_touches_scripts(self):
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
            cwd=ROOT, capture_output=True, text=True, timeout=120,
        )
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, out[-2000:])
        self.assertNotIn("INTERNALERROR", out)
        self.assertNotIn("scripts/", out)
        self.assertIn("tests/", out)


if __name__ == "__main__":
    unittest.main()
