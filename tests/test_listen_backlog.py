"""Listen-backlog sizing for the self-hosted server (launch hardening).

Root cause recorded in the 100x torture runs: with the kernel accept backlog
at 128, a 100-worker burst overflowed the SYN/accept queue and the kernel
answered with RST before the ThreadingHTTPServer ever saw the connection
(transport errors, not HTTP errors). 512 removed every reset.
"""
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNIPPET = "import app.main as m; print(m.Server.request_queue_size)"


class ListenBacklogTests(unittest.TestCase):
    def _backlog(self, env_value):
        env = dict(os.environ)
        env.pop("LISTEN_BACKLOG", None)
        if env_value is not None:
            env["LISTEN_BACKLOG"] = env_value
        out = subprocess.run([sys.executable, "-c", SNIPPET], cwd=ROOT, env=env,
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        return int(out.stdout.strip().splitlines()[-1])

    def test_default_backlog_survives_100x_burst(self):
        self.assertEqual(self._backlog(None), 512)

    def test_env_override_is_honoured(self):
        self.assertEqual(self._backlog("1024"), 1024)

    def test_floor_prevents_regression_below_128(self):
        # A misconfigured deploy must never shrink the backlog below the old
        # (already-proven-insufficient) default.
        self.assertEqual(self._backlog("16"), 128)


if __name__ == "__main__":
    unittest.main()
