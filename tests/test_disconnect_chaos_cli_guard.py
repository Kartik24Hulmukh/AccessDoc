# Guard: disconnect_chaos.py must run with no CLI argument (IndexError regression).
import importlib.util
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
            self.assertEqual(proc.returncode, 0,
                             "stderr:\n" + proc.stderr[-2000:] + "\nstdout tail (gate verdict):\n" + proc.stdout[-1500:])
            report = json.loads((Path(tmp) / "chaos_report.json").read_text())
            self.assertTrue(report["pass"])
            cancelled = [r for r in report["workflows"] if r["case"] == "cancel-body"]
            self.assertEqual(len(cancelled), 20)
            for row in cancelled:
                self.assertEqual(row.get("status"), 422)
                self.assertTrue(row.get("body_read_interrupted"), row)
            self.assertEqual(report.get("server_errors"), [])
            self.assertEqual(report["unhandled_thread_exceptions"], [])
            self.assertEqual(report["new_threads_after_shutdown"], [])


class DisconnectEvidenceGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("disconnect_guard", SCRIPT)
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def test_rejects_false_coverage(self):
        for status, body in [
            (421, {"error": {"code": "INVALID_HOST", "message": "Request host is not allowed"}}),
            (422, {"error": {"code": "INVALID_INPUT", "message": "Invalid JSON request"}}),
            (503, {"error": {"code": "BUSY"}}),
            (200, {"error": {"code": "INVALID_INPUT", "message": "Truncated request body"}}),
            (422, []), (422, {"error": None}),
        ]:
            with self.subTest(status=status, body=body):
                self.assertFalse(self.mod.body_read_interrupted(status, json.dumps(body)))
        self.assertFalse(self.mod.body_read_interrupted(422, b"broken"))

    def test_accepts_only_truncated_body_evidence(self):
        body = json.dumps({"error": {"code": "INVALID_INPUT", "message": "Truncated request body"}})
        self.assertTrue(self.mod.body_read_interrupted(422, body))

    def test_output_flag_and_positional(self):
        for argv, expected in [([], "chaos_report.json"), (["a.json"], "a.json"),
                               (["--output", "b.json"], "b.json"),
                               (["a.json", "--output", "b.json"], "b.json")]:
            with self.subTest(argv=argv):
                self.assertEqual(self.mod.parse_args(argv).output, expected)


if __name__ == "__main__":
    unittest.main()
