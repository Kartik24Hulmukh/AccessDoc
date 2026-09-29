"""CSV syntax/resource failures are bounded validation errors on both adapters."""
import csv
import json
import os
import threading
import unittest
from http.server import HTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.limits import LimitExceeded
from app.manual import parse_manual_findings


class ManualCSVBoundaryTests(unittest.TestCase):
    def test_field_limit_applies_to_header_recognized_and_ignored_columns(self):
        size = csv.field_size_limit()
        for text in ("x" * (size + 1) + "\nx", "id,description\nx," + "x" * (size + 1),
                     "id,ignored\nx," + "x" * (size + 1)):
            with self.subTest(shape=text[:25]), self.assertRaises(LimitExceeded):
                parse_manual_findings(text)

    def test_field_limit_and_one_below_remain_accepted(self):
        size = csv.field_size_limit()
        for n in (size - 1, size):
            with self.subTest(length=n):
                findings = parse_manual_findings("id,description\nx," + "a" * n)
                self.assertEqual(len(findings[0].description), n)

    def test_unterminated_or_invalid_quoted_cells_fail_closed(self):
        for text in ('id,description\nx,"private-unterminated',
                     'id,description\nx,"closed"junk'):
            with self.subTest(shape=text), self.assertRaises(ValueError):
                parse_manual_findings(text)

    def test_both_adapters_reject_then_recover(self):
        from api.handler import handler
        from app.main import Handler, Server
        for server_type, handler_type in ((HTTPServer, handler), (Server, Handler)):
            with self.subTest(adapter=handler_type.__module__):
                server = server_type(("127.0.0.1", 0), handler_type)
                runner = threading.Thread(
                    target=lambda: server.serve_forever(poll_interval=0.01))
                runner.start()
                base = "http://127.0.0.1:%d" % server.server_port
                env = {"ACCESSDOC_REQUIRE_AUTH": "false", "ACCESSDOC_API_KEY": "",
                       "ACCESSDOC_API_KEYS": "", "RATE_LIMIT_PER_MINUTE": "100000",
                       "ALLOWED_HOSTS": "127.0.0.1:%d" % server.server_port}
                try:
                    with patch.dict(os.environ, env), patch(
                            "app.service.generate_pdf_report") as renderer:
                        for text, expected in (
                                ("id,description\nx," + "a" * (csv.field_size_limit() + 1), 413),
                                ('id,description\nx,"private-unterminated', 422)):
                            request = Request(base + "/api/bundle",
                                data=json.dumps({"scanner_input": {"violations": []},
                                    "manual_findings": text}).encode(),
                                headers={"Content-Type": "application/json"})
                            with self.assertRaises(HTTPError) as error:
                                urlopen(request, timeout=5)
                            with error.exception:
                                self.assertEqual(error.exception.code, expected)
                                self.assertIsNotNone(error.exception.headers.get("X-Request-ID"))
                                body = error.exception.read()
                                json.loads(body)
                                self.assertNotIn(b"private-unterminated", body)
                                self.assertNotIn(b"Traceback", body)
                        renderer.assert_not_called()
                    # Real renderer, same admission pool after all rejections.
                    with patch.dict(os.environ, env):
                        request = Request(base + "/api/bundle",
                            data=json.dumps({"scanner_input": {"violations": []},
                                "manual_findings": "id,description\nx,valid"}).encode(),
                            headers={"Content-Type": "application/json"})
                        with urlopen(request, timeout=5) as response:
                            self.assertEqual(response.status, 200)
                            self.assertTrue(response.read().startswith(b"PK"))
                finally:
                    server.shutdown()
                    server.server_close()
                    runner.join(2)
                    self.assertFalse(runner.is_alive())


if __name__ == "__main__":
    unittest.main()