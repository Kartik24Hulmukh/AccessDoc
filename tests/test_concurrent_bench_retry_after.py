# Guard: the concurrency torture bench must never crash or stall on a hostile Retry-After header.
# The bench module starts a server at import time and reads sys.argv, so the helper is
# extracted via ast and executed in isolation.
import ast
import unittest
from email.utils import format_datetime
from datetime import datetime, timedelta, timezone
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "scripts" / "concurrent_bench.py"


def _load():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    keep = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name == "retry_after_seconds")
            or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "RETRY_AFTER_CAP_S" for t in n.targets))]
    ns = {}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(SRC), "exec"), ns)
    return ns["retry_after_seconds"], ns["RETRY_AFTER_CAP_S"]


class RetryAfterGuard(unittest.TestCase):
    def setUp(self):
        self.parse, self.cap = _load()

    def test_numeric_within_cap(self):
        self.assertEqual(self.parse("1"), 1.0)
        self.assertEqual(self.parse(" 0.5 "), 0.5)

    def test_hostile_values_are_bounded(self):
        for v in ("999999", "inf", "1e308"):
            self.assertEqual(self.parse(v), self.cap, v)
        for v in ("-5", "-inf"):
            self.assertEqual(self.parse(v), 0.0, v)

    def test_malformed_never_raises(self):
        for v in (None, "", "nan", "soon", "Wed, 99 Foo 2026", "\x00"):
            d = self.parse(v)
            self.assertTrue(0.0 <= d <= self.cap, (v, d))

    def test_http_date_form(self):
        past = format_datetime(datetime.now(timezone.utc) - timedelta(hours=1), usegmt=True)
        future = format_datetime(datetime.now(timezone.utc) + timedelta(days=1), usegmt=True)
        self.assertEqual(self.parse(past), 0.0)
        self.assertEqual(self.parse(future), self.cap)


if __name__ == "__main__":
    unittest.main()
