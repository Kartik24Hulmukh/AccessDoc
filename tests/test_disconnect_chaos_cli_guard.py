# Guard: disconnect_chaos.py must run with no CLI argument (IndexError regression).
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "disconnect_chaos.py"


class DisconnectChaosCliGuard(unittest.TestCase):
    def test_runs_without_output_argument(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run([sys.executable, str(SCRIPT)], cwd=tmp,
                                  capture_output=True, text=True, timeout=300)
            self.assertNotIn("IndexError", proc.stderr)
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            report = json.loads((Path(tmp) / "chaos_report.json").read_text())
            self.assertTrue(report["pass"])
            self.assertEqual(report["unhandled_thread_exceptions"], [])
            self.assertEqual(report["new_threads_after_shutdown"], [])


if __name__ == "__main__":
    unittest.main()
