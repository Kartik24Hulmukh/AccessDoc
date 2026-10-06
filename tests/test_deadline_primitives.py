"""Deterministic regression for Darwin's coalesced long native waits."""
import threading
import time
import unittest

from app import deadline


class CoalescingLock:
    """Model the measured platform defect without sleeping successful paths."""
    def __init__(self):
        self.lock = threading.Lock()

    def acquire(self, blocking=True, timeout=-1):
        if not blocking:
            return self.lock.acquire(False)
        # The frozen macOS probe observed long requested waits overshooting.
        if timeout > .005:
            time.sleep(.12)
            return False
        return self.lock.acquire(timeout=timeout)

    def release(self):
        self.lock.release()


class DeadlinePrimitiveTests(unittest.TestCase):
    def test_sliced_acquire_avoids_coalesced_long_wait(self):
        lock = CoalescingLock(); lock.acquire()
        before = time.monotonic()
        try:
            self.assertFalse(deadline.take(lock, before + .03))
        finally:
            lock.release()
        self.assertLess(time.monotonic() - before, .10)

    def test_wait_succeeds_once_when_released_inside_original_deadline(self):
        lock = threading.Lock(); lock.acquire()
        timer = threading.Timer(.01, lock.release); timer.start()
        before = time.monotonic()
        self.assertTrue(deadline.take(lock, before + .05))
        self.assertLess(time.monotonic() - before, .05)
        lock.release(); timer.join()

    def test_expired_deadline_is_nonblocking(self):
        lock = threading.Lock(); lock.acquire()
        before = time.monotonic()
        try:
            self.assertFalse(deadline.take(lock, before - 1))
        finally:
            lock.release()
        self.assertLess(time.monotonic() - before, .01)
