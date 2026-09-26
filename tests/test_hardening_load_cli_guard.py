# Guard: hardening_load.py CLI must accept a positional report path (parity
# with disconnect_chaos.py) and keep --output back-compatible.
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "hardening_load.py"


def _load_module():
    sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location("hardening_load_guard", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class HardeningLoadCliGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module()

    def test_positional_output_accepted(self):
        args = self.mod.parse_args(["load_report.json"])
        self.assertEqual(args.output, "load_report.json")

    def test_flag_output_back_compatible(self):
        args = self.mod.parse_args(["--output", "flag.json"])
        self.assertEqual(args.output, "flag.json")

    def test_flag_wins_over_positional(self):
        args = self.mod.parse_args(["pos.json", "--output", "flag.json"])
        self.assertEqual(args.output, "flag.json")

    def test_default_unchanged(self):
        args = self.mod.parse_args([])
        self.assertEqual(args.output, "hardening-load.json")


if __name__ == "__main__":
    unittest.main()
