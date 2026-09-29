"""Real-socket validation parity: invalid evidence must never reach the gateway."""
import json
import os
import threading
import unittest
from http.server import HTTPServer
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from api.handler import handler as HostedHandler
from app.main import Handler as SelfHostedHandler, Server
from app import remediate


class SpyGateway:
    def __init__(self):
        self.calls = []

    def chat(self, prompt, model=None, static_fallback=True):
        self.calls.append(prompt)
        return SimpleNamespace(model="test", fallback=False, attempts=1,
                               latency_ms=1, tokens=1, text="offline test response")


class RemediationAdapterParityTests(unittest.TestCase):
    def _request(self, server, payload):
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/remediate",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=5) as response:
                return response.status
        except HTTPError as exc:
            with exc:
                exc.read()
                return exc.code

    def test_both_adapters_reject_invalid_evidence_before_model_dispatch(self):
        invalid_cases = (
            ({"scanner_input": {"violations": [{"id": 123, "nodes": []}]}}, 422),
            ({"scanner_input": {"violations": [{"id": "image-alt",
                                                "nodes": [{"target": [{"selector": "img"}]}]}]}}, 422),
            ({"scanner_input": {"violations": [{"id": "x" * 10001}]}}, 413),
            ({"violations": [{"id": 123, "nodes": []}]}, 422),
            ({"scanner_input": {"violations": [{"id": "image-alt"}]},
              "violations": [{"id": 123}]}, 422),
        )
        for server_type, handler_type in ((HTTPServer, HostedHandler),
                                          (Server, SelfHostedHandler)):
            with self.subTest(adapter=server_type.__name__):
                server = server_type(("127.0.0.1", 0), handler_type)
                thread = threading.Thread(target=server.serve_forever)
                thread.start()
                gateway = SpyGateway()
                remediate.reset_gateway(gateway)
                env = {"MELIOUS_API_KEY": "local-test-only",
                       "ACCESSDOC_REQUIRE_AUTH": "false",
                       "RATE_LIMIT_PER_MINUTE": "100000",
                       "ALLOWED_HOSTS": f"127.0.0.1:{server.server_port}",
                       "ALLOWED_ORIGINS": f"http://127.0.0.1:{server.server_port}"}
                try:
                    with patch.dict(os.environ, env):
                        for payload, expected in invalid_cases:
                            self.assertEqual(self._request(server, payload), expected)
                        valid = {"violations": [{"id": "image-alt",
                                                  "nodes": [{"target": ["img"]}]}],
                                 "untrusted_extra": "must not enter prompt"}
                        self.assertEqual(self._request(server, valid), 200)
                    self.assertEqual(len(gateway.calls), 1)
                    self.assertNotIn("untrusted_extra", gateway.calls[0])
                finally:
                    remediate.reset_gateway(None)
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)
                    self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()