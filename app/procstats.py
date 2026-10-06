"""Cross-platform process memory/thread telemetry (single source of truth).

Launch telemetry gap (Sessions 8/9/10): /healthz and /readyz must expose a RAM
floor/ceiling so capacity claims are verifiable. The original implementation
lived twice -- once in ``app.main`` and once in ``api.handler`` -- and only
understood POSIX primitives (``resource.getrusage`` + ``/proc/self/status``).
On Windows both copies silently returned ``{}``, so the probes under-reported
the very numbers they were added to publish. That is a correctness bug on any
non-POSIX runtime, not a cosmetic one.

This module is the one implementation both runtimes call:

* ``max_rss_kib`` -- peak resident set since process start (monotonic on
  platforms that provide a peak counter).
* ``rss_kib``     -- current resident set.
* ``threads``     -- live thread count.

Everything is a bounded non-negative integer, no PII. Every probe is
best-effort: a missing primitive omits its key rather than raising.

Windows uses ``psapi!GetProcessMemoryInfo`` via ctypes (WorkingSetSize /
PeakWorkingSetSize). Linux reads VmHWM and VmRSS from one /proc snapshot;
other POSIX systems retain resource.getrusage and platform-specific RSS.
"""

from __future__ import annotations

import os
import sys
import threading

__all__ = ["process_stats", "peak_rss_kib", "current_rss_kib"]

# Guard against absurd readings (test contract: 0 < value < 1 << 40).
_MAX_KIB = 1 << 40


def _sanitize(value):
    """Coerce to a bounded positive int, else None (never raise)."""
    try:
        n = int(value)
    except Exception:
        return None
    if n <= 0 or n >= _MAX_KIB:
        return None
    return n


def _posix_rss_kib():
    """(peak, current) KiB from one Linux status snapshot where available."""
    peak = current = None
    if sys.platform == "darwin":
        # Mach supplies both counters in one task_info call. Sampling
        # getrusage's peak before Mach's current RSS can produce current >
        # peak when allocations occur between those calls.
        peak, current = _darwin_rss_kib()
        if peak is not None and current is not None:
            return peak, current
    if sys.platform.startswith("linux"):
        try:
            # VmHWM and VmRSS are both resident-memory counters in KiB. Taking
            # them from the same snapshot avoids comparing ru_maxrss with a
            # later /proc RSS reading (which can report current > peak).
            with open("/proc/self/status", "rb") as fh:
                for line in fh:
                    if line.startswith(b"VmHWM:"):
                        peak = int(line.split()[1])
                    elif line.startswith(b"VmRSS:"):
                        current = int(line.split()[1])
            if peak is not None and current is not None:
                return peak, current
        except (OSError, ValueError, IndexError):
            pass
    try:
        import resource

        if peak is None:
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux reports KiB; macOS reports bytes. Normalise to KiB.
        if sys.platform == "darwin":
            peak = int(peak) // 1024
    except Exception:
        peak = None
    if current is None:
        try:
            with open("/proc/self/status", "rb") as fh:
                for line in fh:
                    if line.startswith(b"VmRSS:"):
                        current = int(line.split()[1])
                        break
        except OSError:
            pass
    return peak, current


def _darwin_rss_kib():
    """(peak, current) RSS KiB from one MACH_TASK_BASIC_INFO snapshot.

    macOS has no ``/proc``, so without this the probes silently dropped
    ``rss_kib`` (caught by the macOS portability CI job). Native syscall, no
    subprocess; returns (None, None) on any failure.
    """
    try:
        import ctypes

        class _TimeValue(ctypes.Structure):
            _fields_ = [("seconds", ctypes.c_int), ("microseconds", ctypes.c_int)]

        class _MachTaskBasicInfo(ctypes.Structure):
            _pack_ = 4
            _fields_ = [
                ("virtual_size", ctypes.c_uint64),
                ("resident_size", ctypes.c_uint64),
                ("resident_size_max", ctypes.c_uint64),
                ("user_time", _TimeValue),
                ("system_time", _TimeValue),
                ("policy", ctypes.c_int),
                ("suspend_count", ctypes.c_int),
            ]

        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        task = ctypes.c_uint.in_dll(libc, "mach_task_self_")
        info = _MachTaskBasicInfo()
        count = ctypes.c_uint(ctypes.sizeof(info) // ctypes.sizeof(ctypes.c_uint))
        libc.task_info.argtypes = [
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint),
        ]
        libc.task_info.restype = ctypes.c_int
        MACH_TASK_BASIC_INFO = 20
        if libc.task_info(task, MACH_TASK_BASIC_INFO, ctypes.byref(info), ctypes.byref(count)) != 0:
            return None, None
        return int(info.resident_size_max) // 1024, int(info.resident_size) // 1024
    except Exception:
        return None, None


def _darwin_current_rss_kib():
    """Compatibility helper; public probes use the paired Mach snapshot."""
    return _darwin_rss_kib()[1]


def _windows_rss_kib():
    """(peak, current) KiB via psapi!GetProcessMemoryInfo; either may be None."""
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        get_info = psapi.GetProcessMemoryInfo
        get_info.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
            wintypes.DWORD,
        ]
        get_info.restype = wintypes.BOOL
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.GetCurrentProcess()
        if not get_info(handle, ctypes.byref(counters), counters.cb):
            return None, None
        # Bytes -> KiB.
        peak = counters.PeakWorkingSetSize // 1024
        current = counters.WorkingSetSize // 1024
        return peak, current
    except Exception:
        return None, None


def peak_rss_kib():
    """Peak resident set size in KiB, or None when unavailable."""
    if os.name == "nt":
        return _sanitize(_windows_rss_kib()[0])
    return _sanitize(_posix_rss_kib()[0])


def current_rss_kib():
    """Current resident set size in KiB, or None when unavailable."""
    if os.name == "nt":
        return _sanitize(_windows_rss_kib()[1])
    return _sanitize(_posix_rss_kib()[1])


def process_stats():
    """Best-effort process telemetry: ``max_rss_kib``, ``rss_kib``, ``threads``.

    Keys are omitted when the underlying primitive is unavailable; values are
    bounded positive integers when present.
    """
    out = {}
    if os.name == "nt":
        peak, current = _windows_rss_kib()
    else:
        peak, current = _posix_rss_kib()
    peak = _sanitize(peak)
    current = _sanitize(current)
    if peak is not None:
        out["max_rss_kib"] = peak
    if current is not None:
        out["rss_kib"] = current
    try:
        threads = _sanitize(threading.active_count())
        if threads is not None:
            out["threads"] = threads
    except Exception:
        pass
    return out
