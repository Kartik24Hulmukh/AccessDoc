"""Portability regression guards for the non-POSIX defects fixed in PR #73.

The ubuntu-only CI matrix could not see a top-level ``import resource`` or a
POSIX-only RSS probe. These tests emulate a host without ``resource`` (and
without ``/proc``) on *any* runner, and pin the cross-platform CI job so the
guard cannot be silently dropped.
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_PROBE = r"""
import builtins, json, sys
sys.modules["resource"] = None  # emulate a non-POSIX interpreter
_real_open = builtins.open
def _no_proc(path, *a, **k):
    if str(path).startswith("/proc/"):
        raise FileNotFoundError(path)
    return _real_open(path, *a, **k)
builtins.open = _no_proc
import app.main, api.handler, app.procstats
stats = app.procstats.process_stats()
print(json.dumps({"stats": stats, "main": app.main.process_stats() if hasattr(app.main, "process_stats") else None}))
"""


class NonPosixImportTests(unittest.TestCase):
    def test_app_imports_and_probes_without_resource_or_proc(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        proc = subprocess.run(
            [sys.executable, "-c", _PROBE],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
        stats = payload["stats"]
        self.assertIsInstance(stats, dict)
        for key, value in stats.items():
            self.assertIsInstance(value, int, key)
            self.assertGreater(value, 0, key)
            self.assertLess(value, 1 << 40, key)
        # Thread count needs no OS primitive, so it must always survive.
        self.assertIn("threads", stats)


class CiMatrixTests(unittest.TestCase):
    def test_ci_runs_a_non_linux_portability_job(self):
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("portability:", ci)
        self.assertIn("windows-latest", ci)
        self.assertIn("macos-latest", ci)
        self.assertIn("python -m pytest tests -q", ci.split("portability:", 1)[1])

    def test_gitattributes_pins_lf_for_hashed_assets(self):
        attrs = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("eol=lf", attrs)


if __name__ == "__main__":
    unittest.main()
