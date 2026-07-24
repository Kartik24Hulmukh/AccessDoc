"""Tests for the `accessdoc doctor` CLI subcommand."""
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cli


class TestDoctor(unittest.TestCase):
    def test_doctor_returns_zero(self):
        """doctor should exit 0 (warnings are not errors)."""
        old_argv = sys.argv
        try:
            rc = cli.main(["doctor"])
            self.assertEqual(rc, 0)
        finally:
            sys.argv = old_argv

    def test_doctor_mentions_python(self):
        """doctor output should mention Python version."""
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli.main(["doctor"])
        output = buf.getvalue()
        self.assertIn("Python", output)

    def test_doctor_mentions_reportlab(self):
        """doctor output should mention reportlab status."""
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli.main(["doctor"])
        output = buf.getvalue()
        self.assertIn("reportlab", output)

    def test_doctor_mentions_accessdoc(self):
        """doctor output should mention AccessDoc version."""
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli.main(["doctor"])
        output = buf.getvalue()
        self.assertIn("AccessDoc", output)


if __name__ == "__main__":
    unittest.main()
