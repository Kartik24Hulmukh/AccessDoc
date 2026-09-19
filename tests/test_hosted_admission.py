"""Deterministic hosted capacity handoff; no scheduling sleeps or provider calls."""
import http.client
import json
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import api.handler as adapter
from app.bundle import validate_bundle


class ObservedCapacity:
    def __init__(self):
        self.sem = threading.BoundedSemaphore(1)
        self.successor_entered = threading.Event()
        self.calls = 0
        self.lock = threading.Lock()
        self.kwargs = []

    def acquire(self, *args, **kwargs):
        with self.lock:
            self.calls += 1
            self.kwargs.append(kwargs)
            if self.calls == 2:
                self.successor_entered.set()
        return self.sem.acquire(*args, **kwargs)

    def release(self):
        self.sem.release()


class HostedAdmissionTests(unittest.TestCase):
    def test_completed_response_successor_waits_for_capacity_handoff(self):
        capacity = ObservedCapacity()
        tail_started = threading.Event()
        tail_finished = threading.Event()

        class DelayedTail(adapter.handler):
            def _post(self):
                super()._post()
                # The client has the whole body, but the slot is not released yet.
                if not tail_started.is_set():
                    tail_started.set()
                    if not capacity.successor_entered.wait(5):
                        raise AssertionError("successor never attempted admission")
                    tail_finished.set()

        server = ThreadingHTTPServer(("127.0.0.1", 0), DelayedTail)
        runner = threading.Thread(target=server.serve_forever)
        runner.start()

        def post():
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
            try:
                conn.request("POST", "/api/bundle", json.dumps({"scanner_input": {"violations": []}}),
                             {"Content-Type": "application/json"})
                response = conn.getresponse()
                return response.status, response.read()
            finally:
                conn.close()

        try:
            with patch.object(adapter, "GENERATION_CAPACITY", capacity):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    first = pool.submit(post).result(timeout=10)
                    self.assertTrue(tail_started.wait(5))
                    second = pool.submit(post).result(timeout=10)
                self.assertTrue(tail_finished.wait(5))
            self.assertEqual(first[0], 200)
            self.assertEqual(second[0], 200, second[1])
            self.assertTrue(validate_bundle(second[1])["valid"])
            self.assertEqual(first[1], second[1])
            self.assertTrue(capacity.sem.acquire(blocking=False))
            capacity.sem.release()
        finally:
            server.shutdown()
            server.server_close()
            runner.join(5)

    def test_saturated_pool_is_bounded_and_recovers(self):
        capacity = threading.BoundedSemaphore(1)
        capacity.acquire()
        server = ThreadingHTTPServer(("127.0.0.1", 0), adapter.handler)
        runner = threading.Thread(target=server.serve_forever)
        runner.start()
        try:
            with patch.object(adapter, "GENERATION_CAPACITY", capacity):
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                started = time.monotonic()
                try:
                    conn.request("POST", "/api/bundle", b"{}", {"Content-Type": "application/json"})
                    response = conn.getresponse()
                    self.assertEqual(response.status, 503)
                    self.assertEqual(response.getheader("Retry-After"), "1")
                    self.assertIn("error", json.loads(response.read()))
                    self.assertLess(time.monotonic() - started, 1)
                finally:
                    conn.close()
                capacity.release()
                self.assertTrue(capacity.acquire(blocking=False))
                capacity.release()
        finally:
            server.shutdown()
            server.server_close()
            runner.join(5)


if __name__ == "__main__":
    unittest.main()
