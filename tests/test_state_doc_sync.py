"""Guard: the headline release-candidate line in STATE.md must match VERSION.

STATE.md is excluded from scripts/version_lint.py because its dated sections
record history and must not be rewritten. That exclusion let the headline
"Release candidate" line drift a full release behind VERSION. This test pins
only that one line, leaving the historical sections alone.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class StateDocSyncTests(unittest.TestCase):
    def test_release_candidate_line_matches_version(self):
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        state = (ROOT / "STATE.md").read_text(encoding="utf-8")
        m = re.search(r"Release candidate: `([^`]+)`", state)
        self.assertIsNotNone(m, "STATE.md must declare a release candidate")
        self.assertEqual(m.group(1), version)


if __name__ == "__main__":
    unittest.main()
