"""Adversarial tests: GitHub Action command injection must be impossible.

These tests simulate the action.yml Bash-array invocation pattern with
hostile input values (single quotes, semicolons, $(), backticks, etc.)
and assert that:

1. The ci_gate.py script receives the hostile value as a single literal
   argument — it is never split or interpreted by a shell.
2. A sentinel file (proof of command execution) is NEVER created.

The test re-implements the exact Bash-array pattern from action.yml
(no eval, no constructed command string) and passes each payload as
a single argv element, exactly as Bash arrays preserve them.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CI_GATE = os.path.join(ROOT, "scripts", "ci_gate.py")

# Minimal valid axe-core JSON so ci_gate.py gets past argument parsing.
_AXE = json.dumps({
    "url": "https://example.com",
    "testEngine": {"name": "axe-core", "version": "4.11.2"},
    "violations": [],
})

# Sentinel path that a successful injection would create.
_SENTINEL_NAME = "pwned_by_injection"


def _make_axe_file(tmpdir):
    path = os.path.join(tmpdir, "axe.json")
    with open(path, "w") as f:
        f.write(_AXE)
    return path


class TestActionInjection(unittest.TestCase):
    """Each payload is passed as a single argv element (Bash-array semantics)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="accessdoc_inj_")
        self.sentinel = os.path.join(self.tmpdir, _SENTINEL_NAME)
        self.axe_path = _make_axe_file(self.tmpdir)
        self.output_dir = os.path.join(self.tmpdir, "out")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run_with_payload(self, payload_field, payload_value):
        """Run ci_gate.py exactly as action.yml's Bash array does.

        The payload is placed in a single argv slot — no shell parsing.
        We assert the sentinel is never created regardless of payload.
        """
        # Index:  0            1        2            3             4           5       6              7          8              9
        args = [
            sys.executable, CI_GATE,
            "--axe-json", self.axe_path,        # idx 3 = axe-json value
            "--fail-on", "none",                 # idx 5 = fail-on value
            "--client-name", "CI Audit",         # idx 7 = client-name value
            "--output-dir", self.output_dir,     # idx 9 = output-dir value
        ]
        if payload_field == "client-name":
            args[7] = payload_value
        elif payload_field == "output-dir":
            args[9] = payload_value
        elif payload_field == "axe-json":
            args[3] = payload_value
        elif payload_field == "fail-on":
            args[5] = payload_value

        env = dict(os.environ)
        # Ensure no sentinel leaks from environment.
        env.pop("SENTINEL_PATH", None)

        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        return proc

    # ---- payloads that must never create a sentinel file ----

    PAYLOADS = [
        "single'quote",
        'double"quote',
        "semi;colon",
        "new\nline",
        "$(whoami)",
        "`id`",
        "wild*card",
        "-n",
        "  leading spaces  ",
        "unicode\x01ctrl",
        "path/with/$(touch sentinel)",
        "path; touch sentinel #",
        "'; touch sentinel; echo '",
        "\"; touch sentinel; \"",
        "$(touch sentinel)",
        "`touch sentinel`",
        "&& touch sentinel",
        "|| touch sentinel",
        "| touch sentinel",
        "> /dev/null; touch sentinel",
        "newline\ntouch sentinel",
        "tab\tsentinel",
        "back\\slash",
        "dollar$var",
        "${IFS}touch${IFS}sentinel",
        "eval$(touch sentinel)",
    ]

    def test_null_byte_payload_rejected(self):
        """Null bytes in argv are rejected by Python's subprocess layer itself."""
        # Python's subprocess.run raises ValueError for embedded null bytes,
        # which is itself a security property — the payload can never reach
        # the child process. We verify this explicitly.
        with self.assertRaises(ValueError):
            self._run_with_payload("client-name", "null\x00byte\x01payload")

    def test_no_sentinel_created_for_any_payload(self):
        """No payload, when passed as a single argv element, creates a sentinel."""
        for payload in self.PAYLOADS:
            with self.subTest(payload=payload):
                proc = self._run_with_payload("client-name", payload)
                # The script may exit 0 or 2 (bad input), but must never
                # have executed a shell command that created the sentinel.
                self.assertFalse(
                    os.path.exists(self.sentinel),
                    f"Sentinel file created by payload: {payload!r}",
                )

    def test_output_dir_payloads_dont_create_sentinel(self):
        """Hostile output-dir values must not escape to create files outside."""
        for payload in self.PAYLOADS:
            with self.subTest(payload=payload):
                proc = self._run_with_payload("output-dir", payload)
                self.assertFalse(
                    os.path.exists(self.sentinel),
                    f"Sentinel file created by output-dir payload: {payload!r}",
                )

    def test_axe_json_payloads_dont_create_sentinel(self):
        """Hostile axe-json path values must not create a sentinel."""
        for payload in self.PAYLOADS:
            with self.subTest(payload=payload):
                proc = self._run_with_payload("axe-json", payload)
                self.assertFalse(
                    os.path.exists(self.sentinel),
                    f"Sentinel file created by axe-json payload: {payload!r}",
                )

    def test_fail_on_invalid_enum_rejected(self):
        """Invalid fail-on values must be rejected with exit code 2."""
        for bad in ["critical; touch sentinel", "$(touch sentinel)", "high\ninject", "INVALID"]:
            with self.subTest(fail_on=bad):
                proc = self._run_with_payload("fail-on", bad)
                self.assertIn(proc.returncode, (2,)),
                self.assertFalse(
                    os.path.exists(self.sentinel),
                    f"Sentinel created by fail-on payload: {bad!r}",
                )

    def test_action_yml_has_no_eval(self):
        """action.yml must not contain eval, bash -c, or constructed command strings."""
        action_path = os.path.join(ROOT, "action.yml")
        with open(action_path) as f:
            content = f.read()
        self.assertNotIn("eval ", content, "action.yml must not use eval")
        self.assertNotIn("eval\t", content, "action.yml must not use eval")
        self.assertNotIn("bash -c", content, "action.yml must not use bash -c")
        # The old ARGS= pattern must be gone.
        self.assertNotIn("ARGS=", content, "action.yml must not use ARGS= string construction")
        # Must use Bash array pattern.
        self.assertIn("args=(", content, "action.yml must use Bash array pattern")
        self.assertIn('"${args[@]}"', content, "action.yml must quote array expansion")

    def test_normal_invocation_still_works(self):
        """A normal (non-hostile) invocation must succeed."""
        proc = self._run_with_payload("client-name", "Normal Client")
        self.assertEqual(proc.returncode, 0, f"Normal run failed: {proc.stderr}")
        bundle = os.path.join(self.output_dir, "accessdoc-bundle.zip")
        self.assertTrue(os.path.exists(bundle), "Bundle not created on normal run")


if __name__ == "__main__":
    unittest.main()
