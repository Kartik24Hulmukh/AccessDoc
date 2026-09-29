"""Linux RSS peak and current must come from a coherent kernel snapshot."""
import io
import unittest
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
        with patch.object(procstats.sys, "platform", "linux"), \
             patch.object(procstats.os, "name", "posix"), \
             patch("builtins.open", return_value=io.BytesIO(status)), \
             patch("resource.getrusage") as usage:
            usage.return_value.ru_maxrss = 51000
            stats = procstats.process_stats()
        self.assertEqual(stats["max_rss_kib"], 51000)
        self.assertEqual(stats["rss_kib"], 49900)


if __name__ == "__main__":
    unittest.main()