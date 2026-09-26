"""Real-socket regression: HTTP 429 must carry a usable Retry-After header.

RFC 6585 s.4 and the published AccessDoc error contract both tell clients to
honour Retry-After. Before this fix the rate-limiter returned a bare 429, so a
chaotic burst of back-to-back uploads (the 120-profile journey harness) had no
backoff signal and hot-looped into a 429 storm. No mocks, no sleeps: a real
ThreadingHTTPServer on a real loopback socket with RATE_LIMIT_PER_MINUTE=2.
"""
import json
import os
import unittest
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app import main as app_main

PAYLOAD = json.dumps({"scanner_input": {"violations": []}}).encode()


class RateLimitRetryAfterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._prev = os.environ.get("RATE_LIMIT_PER_MINUTE")
        os.environ["RATE_LIMIT_PER_MINUTE"] = "2"
        app_main.RATE.clear()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app_main.Handler)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        app_main.RATE.clear()
        if cls._prev is None:
            os.environ.pop("RATE_LIMIT_PER_MINUTE", None)
        else:
            os.environ["RATE_LIMIT_PER_MINUTE"] = cls._prev

    def _post(self):
        host = "127.0.0.1:%d" % self.port
        req = Request("http://%s/api/bundle" % host, data=PAYLOAD,
                      headers={"Content-Type": "application/json",
                               "Host": host,
                               "Origin": "http://%s" % host})
        try:
            with urlopen(req, timeout=10) as resp:
                return resp.status, dict(resp.headers)
        except HTTPError as exc:
            headers = dict(exc.headers)
            exc.close()
            return exc.code, headers

    def test_rate_limited_response_carries_retry_after(self):
        os.environ["ALLOWED_HOSTS"] = "127.0.0.1:%d" % self.port
        os.environ["ALLOWED_ORIGINS"] = "http://127.0.0.1:%d" % self.port
        seen = [self._post() for _ in range(5)]
        limited = [(s, h) for s, h in seen if s == 429]
        self.assertTrue(limited, "expected at least one 429 with limit=2, got %r"
                        % [s for s, _ in seen])
        for status, headers in limited:
            self.assertIn("Retry-After", headers,
                          "429 without Retry-After leaves clients hot-looping")
            value = int(headers["Retry-After"])
            self.assertGreaterEqual(value, 1)
            self.assertLessEqual(value, 60)

    def test_rate_limit_state_reports_bounded_retry_after(self):
        app_main.RATE.clear()
        ip = "203.0.113.9"
        self.assertEqual(app_main.rate_limit_state(ip), (True, 0))
        self.assertEqual(app_main.rate_limit_state(ip), (True, 0))
        ok, retry = app_main.rate_limit_state(ip)
        self.assertFalse(ok)
        self.assertGreaterEqual(retry, 1)
        self.assertLessEqual(retry, 60)
        self.assertIs(app_main.allowed(ip), False)
        app_main.RATE.clear()


if __name__ == "__main__":
    unittest.main()
