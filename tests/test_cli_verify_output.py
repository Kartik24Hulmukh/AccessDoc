"""Regression tests for the machine-readable verify output contract."""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import cli


class TestVerifyOutputContract(unittest.TestCase):
    def test_valid_verify_keeps_stdout_machine_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = os.path.join(tmp, "bundle.zip")
            with open(bundle, "wb") as f:
                f.write(b"fixture")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with mock.patch("cli.validate_bundle", return_value={"valid": True}), \
                    redirect_stdout(stdout), redirect_stderr(stderr):
                rc = cli.main(["verify", bundle])

        self.assertEqual(rc, 0)
        self.assertTrue(json.loads(stdout.getvalue())["valid"])
        self.assertIn("Validity proves only ZIP members", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
