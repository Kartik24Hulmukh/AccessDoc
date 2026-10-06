"""Readiness exposes optional AI degradation without evicting the core service."""
import json
import os
import threading
import unittest
from http.server import HTTPServer
from unittest.mock import patch
from urllib.request import urlopen

from app import remediate
from app.gateway import ModelGateway
from app.main import Handler
from api.handler import handler


class GatewayReadinessTests(unittest.TestCase):
    def setUp(self):
        self.old_gateway = remediate._GATEWAY
        self.env = patch.dict(os.environ, {"MELIOUS_API_KEY": "test-not-secret"})
        self.env.start()
        self.gw = ModelGateway(api_key="test-not-secret")
        remediate.reset_gateway(self.gw)

    def tearDown(self):
        remediate.reset_gateway(self.old_gateway)
        self.gw._session.close()
        self.env.stop()

    def test_unconfigured_is_explicit_and_does_not_construct_gateway(self):
        remediate.reset_gateway(None)
        with patch.dict(os.environ, {"MELIOUS_API_KEY": ""}):
            snap = remediate.health()
        self.assertEqual(snap["status"], "degraded")
        self.assertEqual(snap["degraded_reasons"], ["not_configured"])
        self.assertIsNone(remediate._GATEWAY)

    def test_configured_unprobed_is_not_claimed_healthy(self):
        remediate.reset_gateway(None)
        snap = remediate.health()
        self.assertEqual(snap["status"], "unknown")
        self.assertEqual(snap["degraded_reasons"], [])
        self.assertIsNone(remediate._GATEWAY)

    def test_billing_retry_window_expires_without_provider_probe(self):
        with patch("app.gateway.time.monotonic", return_value=100):
            self.gw._hold_billing("primary")
        with patch("app.gateway.time.monotonic", return_value=101.25):
            snap = remediate.health()
        self.assertEqual(snap["status"], "degraded")
        self.assertEqual(snap["degraded_reasons"], ["billing_exhausted"])
        self.assertEqual(snap["billing_retry_after_seconds"], 299)
        with patch("app.gateway.time.monotonic", return_value=401):
            snap = remediate.health()
        self.assertEqual(snap["billing_retry_after_seconds"], 0)
        self.assertNotIn("billing_exhausted", snap["degraded_reasons"])
        self.assertEqual(snap["status"], "unknown")

    def test_both_http_adapters_keep_core_ready_during_billing_hold(self):
        self.gw._hold_billing("primary")
        for cls in (Handler, handler):
            with self.subTest(adapter=cls.__module__):
                server = HTTPServer(("127.0.0.1", 0), cls)
                port = server.server_port
                thread = threading.Thread(target=server.serve_forever)
                thread.start()
                try:
                    with patch.dict(os.environ, {"ALLOWED_HOSTS": f"127.0.0.1:{port}"}):
                        for route in ("/readyz", "/healthz"):
                            with urlopen(f"http://127.0.0.1:{port}{route}", timeout=5) as response:
                                self.assertEqual(response.status, 200)
                                body = json.load(response)
                                if route == "/healthz" and cls is Handler:
                                    # Self-hosted liveness deliberately omits optional dependencies.
                                    self.assertEqual(body["status"], "ok")
                                    continue
                                snap = body["gateway"]
                            self.assertTrue(snap["billing_exhausted"])
                            self.assertEqual(snap["status"], "degraded")
                            self.assertEqual(snap["degraded_reasons"], ["billing_exhausted"])
                            self.assertGreater(snap["billing_retry_after_seconds"], 0)
                            self.assertNotIn("test-not-secret", json.dumps(snap))
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)
                    self.assertFalse(thread.is_alive())
