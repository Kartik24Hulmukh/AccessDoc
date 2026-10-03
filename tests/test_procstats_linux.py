"""Linux RSS peak and current must come from a coherent kernel snapshot."""
import io
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import procstats


class LinuxMemorySnapshotTests(unittest.TestCase):
    def test_same_status_snapshot_supplies_peak_and_current(self):
        status = b"Name:\tpython\nVmHWM:\t 50100 kB\nVmRSS:\t 49900 kB\n"
        with patch.object(procstats.sys, "platform", "linux"), \
             patch.object(procstats.os, "name", "posix"), \
             patch("builtins.open", return_value=io.BytesIO(status)) as opened:
            stats = procstats.process_stats()
        self.assertEqual(stats["max_rss_kib"], 50100)
        self.assertEqual(stats["rss_kib"], 49900)
        opened.assert_called_once_with("/proc/self/status", "rb")

    def test_missing_hwm_falls_back_without_discarding_current(self):
        status = b"VmRSS:\t 49900 kB\n"
        # This is a simulated Linux fallback test on every CI platform.
        # Windows has no resource module; patching resource.getrusage would
        # fail before the production fallback is even exercised.
        resource = SimpleNamespace(
            RUSAGE_SELF=0, getrusage=lambda _: SimpleNamespace(ru_maxrss=51000))
        with patch.object(procstats.sys, "platform", "linux"), \
             patch.object(procstats.os, "name", "posix"), \
             patch("builtins.open", return_value=io.BytesIO(status)), \
             patch.dict(sys.modules, {"resource": resource}):
            stats = procstats.process_stats()
        self.assertEqual(stats["max_rss_kib"], 51000)
        self.assertEqual(stats["rss_kib"], 49900)

    def test_missing_resource_preserves_current_and_omits_unavailable_peak(self):
        with patch.object(procstats.sys, "platform", "linux"), \
             patch.object(procstats.os, "name", "posix"), \
             patch("builtins.open", return_value=io.BytesIO(b"VmRSS:\t 49900 kB\n")), \
             patch.dict(sys.modules, {"resource": None}):
            stats = procstats.process_stats()
        self.assertEqual(stats["rss_kib"], 49900)
        self.assertNotIn("max_rss_kib", stats)


if __name__ == "__main__":
    unittest.main()