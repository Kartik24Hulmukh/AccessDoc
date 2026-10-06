"""Darwin peak/current counters must describe the same Mach snapshot."""
import ctypes
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import procstats


class DarwinMemorySnapshotTests(unittest.TestCase):
    def test_paired_snapshot_avoids_older_getrusage_peak(self):
        resource = SimpleNamespace(
            RUSAGE_SELF=0, getrusage=lambda _: SimpleNamespace(ru_maxrss=1024))
        with patch.object(procstats.sys, "platform", "darwin"), \
             patch.object(procstats.os, "name", "posix"), \
             patch.object(procstats, "_darwin_rss_kib", return_value=(51000, 49900)) as read, \
             patch.dict(sys.modules, {"resource": resource}):
            stats = procstats.process_stats()
        self.assertEqual(stats["max_rss_kib"], 51000)
        self.assertEqual(stats["rss_kib"], 49900)
        read.assert_called_once_with()

    def test_native_failure_preserves_resource_peak_without_inventing_current(self):
        resource = SimpleNamespace(
            RUSAGE_SELF=0, getrusage=lambda _: SimpleNamespace(ru_maxrss=51000 * 1024))
        with patch.object(procstats.sys, "platform", "darwin"), \
             patch.object(procstats.os, "name", "posix"), \
             patch.object(procstats, "_darwin_rss_kib", return_value=(None, None)), \
             patch("builtins.open", side_effect=OSError), \
             patch.dict(sys.modules, {"resource": resource}):
            stats = procstats.process_stats()
        self.assertEqual(stats["max_rss_kib"], 51000)
        self.assertNotIn("rss_kib", stats)

    def test_mach_abi_reads_both_counters_in_kib_once(self):
        calls = []
        class TaskInfo:
            def __call__(self, task, flavor, info, count):
                calls.append((task.value, flavor, count._obj.value))
                info._obj.resident_size = 49900 * 1024
                info._obj.resident_size_max = 51000 * 1024
                return 0
        libc = SimpleNamespace(task_info=TaskInfo())
        with patch.object(ctypes, "CDLL", return_value=libc), \
             patch.object(ctypes.c_uint, "in_dll", return_value=ctypes.c_uint(7)):
            self.assertEqual(procstats._darwin_rss_kib(), (51000, 49900))
        self.assertEqual(calls, [(7, 20, 12)])

    def test_mach_error_omits_both_counters(self):
        class TaskInfo:
            def __call__(self, *args):
                return 5
        with patch.object(ctypes, "CDLL", return_value=SimpleNamespace(task_info=TaskInfo())), \
             patch.object(ctypes.c_uint, "in_dll", return_value=ctypes.c_uint(7)):
            self.assertEqual(procstats._darwin_rss_kib(), (None, None))