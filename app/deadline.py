"""Absolute-deadline adapters for CPython blocking synchronization primitives.

Darwin may coalesce a single long relative pthread/condition wait well beyond
its requested timeout under scheduler pressure.  Use short *native timed waits*
while retaining an absolute monotonic deadline.  This is not a retry of the
protected operation: the same wait remains pending and succeeds at most once.
The cap also bounds the hidden mutex reacquisition performed by Event/Future.
"""
from __future__ import annotations

from concurrent.futures import TimeoutError as FutureTimeout
import time

# The measured macOS probe on the frozen candidate showed 30 ms full waits
# returning 36.6--178.9 ms, while 1 ms native slices returned in 30.9--36.3 ms.
# Keep one constant for every caller-side primitive so nested waits cannot add
# independent grace periods.
_NATIVE_WAIT_SLICE = 0.001


def remaining(deadline: float) -> float:
    return max(0.0, deadline - time.monotonic())


def take(lock, deadline: float) -> bool:
    """Acquire once, fairly rejoining the primitive until absolute expiry."""
    while True:
        left = remaining(deadline)
        if left <= 0:
            return lock.acquire(blocking=False)
        if lock.acquire(timeout=min(_NATIVE_WAIT_SLICE, left)):
            return True


def wait(event, deadline: float) -> bool:
    """Wait for an Event-like object without one overshooting relative wait."""
    while True:
        left = remaining(deadline)
        if left <= 0:
            return event.wait(0)
        if event.wait(min(_NATIVE_WAIT_SLICE, left)):
            return True


def join(thread, deadline: float) -> bool:
    """Join through bounded native waits; return whether the thread exited."""
    while thread.is_alive():
        left = remaining(deadline)
        if left <= 0:
            break
        thread.join(min(_NATIVE_WAIT_SLICE, left))
    return not thread.is_alive()


def result(future, deadline: float):
    """Return one Future result or raise FutureTimeout at absolute expiry."""
    while True:
        left = remaining(deadline)
        if left <= 0:
            return future.result(timeout=0)
        try:
            return future.result(timeout=min(_NATIVE_WAIT_SLICE, left))
        except FutureTimeout:
            if time.monotonic() >= deadline:
                raise
