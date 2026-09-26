"""Cross-platform process memory/thread telemetry (single source of truth).

Launch telemetry gap (Sessions 8/9/10): /healthz and /readyz must expose a RAM
floor/ceiling so capacity claims are verifiable. The original implementation
lived twice -- once in ``app.main`` and once in ``api.handler`` -- and only
understood POSIX primitives (``resource.getrusage`` + ``/proc/self/status``).
On Windows both copies silently returned ``{}``, so the probes under-reported
the very numbers they were added to publish. That is a correctness bug on any
non-POSIX runtime, not a cosmetic one.

This module is the one implementation both runtimes call:

* ``max_rss_kib`` -- peak resident set since process start (monotonic).
* ``rss_kib``     -- current resident set.
* ``threads``     -- live thread count.

Everything is a bounded non-negative integer, no PII. Every probe is
best-effort: a missing primitive omits its key rather than raising.

Windows uses ``psapi!GetProcessMemoryInfo`` via ctypes (WorkingSetSize /
PeakWorkingSetSize). POSIX keeps the original primitives so existing
behaviour on Linux/macOS is byte-identical.
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
    """(peak, current) KiB from POSIX primitives; either element may be None."""
    peak = current = None
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux reports KiB; macOS reports bytes. Normalise to KiB.
        if sys.platform == "darwin":
            peak = int(peak) // 1024
    except Exception:
        peak = None
    try:
        with open("/proc/self/status", "rb") as fh:
            for line in fh:
                if line.startswith(b"VmRSS:"):
                    current = int(line.split()[1])
                    break
    except Exception:
        current = None
    return peak, current


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
    peak = peak_rss_kib()
    if peak is not None:
        out["max_rss_kib"] = peak
    current = current_rss_kib()
    if current is not None:
        out["rss_kib"] = current
    try:
        threads = _sanitize(threading.active_count())
        if threads is not None:
            out["threads"] = threads
    except Exception:
        pass
    return out
