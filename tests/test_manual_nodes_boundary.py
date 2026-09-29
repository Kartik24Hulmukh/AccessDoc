"""Node-count representation and generic errors never echo interpreter details."""
import json
import os
import threading
import unittest
from http.server import HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from app.limits import LimitExceeded, MAX_NODES_PER_VIOLATION
from app.manual import parse_manual_findings


class ManualNodesBoundaryTests(unittest.TestCase):
    def test_valid_counts_and_empty_defaults(self):
        for value, expected in ((None, 0), ("", 0), ("  ", 0), (0, 0),
                                (" 003 ", 3), (7, 7),
                                (str(MAX_NODES_PER_VIOLATION),
                                 MAX_NODES_PER_VIOLATION)):
            with self.subTest(value=value):
                self.assertEqual(parse_manual_findings(
                    [{"id": "x", "nodes": value}])[0].nodes, expected)

    def test_non_ascii_negative_and_non_integer_counts_reject_generically(self):
        for value in ("²", "١", "-1", -1, True, 1.5, {}, [], "private-cell"):
            with self.subTest(value=value), self.assertRaisesRegex(
                    ValueError, "^Invalid manual finding node count$"):
                parse_manual_findings([{"id": "x", "nodes": value}])

    def test_large_decimal_rejects_before_integer_conversion(self):
        for value in (MAX_NODES_PER_VIOLATION + 1, "9" * 5000):
            with self.subTest(shape=type(value).__name__), self.assertRaises(
                    LimitExceeded):
                parse_manual_findings([{"id": "x", "nodes": value}])

    def test_both_adapters_never_echo_raw_validation_exception(self):
        from api.handler import handler
        from app.main import Handler, Server
        for server_type, handler_type in ((HTTPServer, handler), (Server, Handler)):
            with self.subTest(adapter=handler_type.__module__):
                server = server_type(("127.0.0.1", 0), handler_type)
                runner = threading.Thread(
                    target=lambda: server.serve_forever(poll_interval=0.01))
                runner.start()
                env = {"ACCESSDOC_REQUIRE_AUTH": "false", "ACCESSDOC_API_KEY": "",
                       "ACCESSDOC_API_KEYS": "", "RATE_LIMIT_PER_MINUTE": "100000",
                       "ALLOWED_HOSTS": "127.0.0.1:%d" % server.server_port}
                try:
                    with patch.dict(os.environ, env), patch(
                            "app.service.generate_pdf_report") as renderer:
                        for manual, expected in (
                                ("id,nodes\nx,²", 422),
                                ("|id|nodes|\n|---|---|\n|x|²|", 422),
                                ([{"id": "x", "nodes": "9" * 5000}], 413)):
                            request = Request(
                                "http://127.0.0.1:%d/api/bundle" % server.server_port,
                                data=json.dumps({"scanner_input": {"violations": []},
                                                 "manual_findings": manual}).encode(),
                                headers={"Content-Type": "application/json"})
                            with self.assertRaises(HTTPError) as error:
                                urlopen(request, timeout=5)
                            with error.exception:
                                self.assertEqual(error.exception.code, expected)
                                body = error.exception.read()
                                json.loads(body)
                                for marker in (b"invalid literal", b"Traceback",
                                               b"ValueError", "²".encode(),
                                               b"999999999"):
                                    self.assertNotIn(marker, body)
                        renderer.assert_not_called()
                    with patch.dict(os.environ, env), patch(
                            handler_type.__module__ + ".build_artifacts",
                            side_effect=ValueError("private-parser-detail")):
                        request = Request(
                            "http://127.0.0.1:%d/api/bundle" % server.server_port,
                            data=b'{"scanner_input":{"violations":[]}}',
                            headers={"Content-Type": "application/json"})
                        with self.assertRaises(HTTPError) as error:
                            urlopen(request, timeout=5)
                        with error.exception:
                            self.assertEqual(error.exception.code, 422)
                            self.assertNotIn(b"private-parser-detail",
                                             error.exception.read())
                finally:
                    server.shutdown()
                    server.server_close()
                    runner.join(2)
                    self.assertFalse(runner.is_alive())