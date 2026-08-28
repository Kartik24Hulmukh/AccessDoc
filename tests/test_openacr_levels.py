"""The conformance level of a criterion is a fact about WCAG, not a string shape.

Regression for the 28 Aug defect: the emitter's Level A/AA heuristic misfiled Level A criteria
into the Level AA chapter, and put Level AAA criteria in AA while emitting the AAA chapter as disabled.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.wcag_levels import WCAG_LEVELS, chapter_for, level_for, partition

MUST_BE_LEVEL_A = [
    "1.1.1", "1.2.1", "1.2.2", "1.2.3", "1.3.1", "1.3.2", "1.3.3", "1.4.1", "1.4.2",
    "2.1.1", "2.1.2", "2.1.4", "2.2.1", "2.2.2", "2.3.1", "2.4.1", "2.4.2", "2.4.3",
    "2.4.4", "2.5.1", "2.5.2", "2.5.3", "2.5.4", "3.1.1", "3.2.1", "3.2.2", "3.3.1",
    "3.3.2", "4.1.1", "4.1.2"
]
MUST_BE_LEVEL_AA = ["1.4.3", "1.3.4", "2.4.6", "3.1.2", "1.2.4", "1.2.5", "1.3.5", "1.4.4", "1.4.10", "1.4.11", "1.4.12", "1.4.13", "2.4.5", "2.4.7", "3.2.3", "3.2.4", "3.3.3", "3.3.4", "4.1.3"]
MUST_BE_LEVEL_AAA = ["1.4.6", "2.4.9", "2.5.5", "1.2.6", "1.2.7", "1.2.8", "1.2.9", "1.3.6", "1.4.7", "1.4.8", "1.4.9", "2.1.3", "2.2.3", "2.2.4", "2.2.5", "2.2.6", "2.3.2", "2.3.3", "2.4.8", "2.4.10", "2.5.6", "3.1.3", "3.1.4", "3.1.5", "3.1.6", "3.2.5", "3.3.5", "3.3.6"]

BROKEN_HEURISTIC = (
    lambda sc: sc.endswith(".1") and sc[0] in "1234" and sc.split(".")[1] == "1"
)


class TestWcagLevels(unittest.TestCase):
    def test_level_a_criteria_are_level_a(self):
        for sc in MUST_BE_LEVEL_A:
            self.assertEqual(level_for(sc), "A", sc)
            self.assertEqual(chapter_for(sc), "success_criteria_level_a", sc)

    def test_level_aa_criteria_are_level_aa(self):
        for sc in MUST_BE_LEVEL_AA:
            self.assertEqual(chapter_for(sc), "success_criteria_level_aa", sc)

    def test_aaa_criteria_do_not_land_in_aa(self):
        for sc in MUST_BE_LEVEL_AAA:
            self.assertEqual(chapter_for(sc), "success_criteria_level_aaa", sc)

    def test_every_mapped_criterion_has_a_chapter(self):
        buckets, unmapped = partition(WCAG_LEVELS.keys())
        self.assertEqual(unmapped, [])
        self.assertEqual(
            sum(len(v) for v in buckets.values()), len(WCAG_LEVELS)
        )

    def test_unknown_criterion_is_unmapped_not_guessed(self):
        self.assertIsNone(level_for("9.9.9"))
        self.assertIsNone(chapter_for("9.9.9"))

    def test_the_old_heuristic_really_was_wrong(self):
        """Documents the defect so nobody reintroduces the clever one-liner."""
        level_a = [sc for sc, lvl in WCAG_LEVELS.items() if lvl == "A"]
        caught = [sc for sc in level_a if BROKEN_HEURISTIC(sc)]
        self.assertGreater(len(level_a), len(caught))
        self.assertEqual(sorted(caught), ["1.1.1", "2.1.1", "3.1.1", "4.1.1"])


if __name__ == "__main__":
    unittest.main()
