"""Expiry must remove logical payload references even with no client traffic."""
import threading
import unittest
from app.store import TTLReportStore


class IdleExpiryTests(unittest.TestCase):
    def test_idle_expiry_is_traffic_independent(self):
        store = TTLReportStore(ttl_seconds=0.05)
        removed = threading.Event()
        original = store._remove
        def observe(key):
            original(key)
            removed.set()
        store._remove = observe
        try:
            store.put(b"private-pdf", b"private-html", b"private-receipt", "report.pdf")
            self.assertTrue(removed.wait(1), "expiry required a get/put/stats request")
            # Do not trigger lazy cleanup in the assertion.
            with store._lock:
                self.assertEqual(store._items, {})
                self.assertEqual(store._bytes, 0)
        finally:
            store.close()

    def test_close_clears_payloads_and_prevents_new_reports(self):
        store = TTLReportStore()
        store.put(b"p", b"h", b"r", "report.pdf")
        store.close()
        self.assertEqual(store._items, {})
        self.assertEqual(store._bytes, 0)
        with self.assertRaises(RuntimeError):
            store.put(b"p", b"h", b"r", "new.pdf")