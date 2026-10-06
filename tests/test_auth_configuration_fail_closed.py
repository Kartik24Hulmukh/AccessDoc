"""Strict auth config, real loopback adapters; synthetic keys only."""
import http.client
import json
import os
import unittest
from email.message import Message
from http.server import HTTPServer
from threading import Thread
from unittest.mock import patch

from app import http_policy
from app.main import Handler as LocalHandler
from api.handler import handler as ServerlessHandler

INVALID = ('', ' ', 'yes', '1', 'falsee', 'synthetic-invalid-config-canary')
KEY = 'synthetic-auth-config-key'


class AuthConfigurationUnitTests(unittest.TestCase):
    def test_explicit_invalid_values_fail_closed_even_with_matching_keys(self):
        for value in INVALID:
            for keys in ({}, {'ACCESSDOC_API_KEY': KEY}, {'ACCESSDOC_API_KEYS': KEY}):
                with self.subTest(value=value, keys=bool(keys)), patch.dict(
                        os.environ, {'ACCESSDOC_REQUIRE_AUTH': value, **keys}, clear=True):
                    headers = Message()
                    headers['Authorization'] = 'Bearer ' + KEY
                    headers['X-API-Key'] = KEY
                    self.assertTrue(http_policy.auth_required())
                    self.assertEqual(http_policy.readiness_reasons(), ['AUTH_CONFIG_INVALID'])
                    self.assertEqual(http_policy.auth_error(headers), (503, 'AUTH_CONFIG_INVALID'))

    def test_absent_and_explicit_false_preserve_local_default(self):
        for env in ({}, {'ACCESSDOC_REQUIRE_AUTH': 'false'}, {'ACCESSDOC_REQUIRE_AUTH': ' FALSE '}):
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True):
                self.assertFalse(http_policy.auth_required())
                self.assertEqual(http_policy.readiness_reasons(), [])
                self.assertIsNone(http_policy.auth_error(Message()))

    def test_true_without_key_is_still_not_configured(self):
        for value in ('true', 'TRUE', ' true '):
            with self.subTest(value=value), patch.dict(os.environ, {'ACCESSDOC_REQUIRE_AUTH': value}, clear=True):
                self.assertTrue(http_policy.auth_required())
                self.assertEqual(http_policy.readiness_reasons(), ['AUTH_NOT_CONFIGURED'])
                self.assertEqual(http_policy.auth_error(Message()), (503, 'AUTH_NOT_CONFIGURED'))

    def test_false_never_bypasses_configured_single_or_legacy_key(self):
        for env, header in (({'ACCESSDOC_API_KEY': KEY}, 'Authorization'),
                            ({'ACCESSDOC_API_KEYS': KEY}, 'X-API-Key')):
            with self.subTest(header=header), patch.dict(os.environ, {'ACCESSDOC_REQUIRE_AUTH': 'false', **env}, clear=True):
                self.assertTrue(http_policy.auth_required())
                self.assertEqual(http_policy.auth_error(Message()), (401, 'UNAUTHORIZED'))
                headers = Message()
                headers[header] = ('Bearer ' if header == 'Authorization' else '') + KEY
                self.assertIsNone(http_policy.auth_error(headers))
                headers[header] = headers[header]
                self.assertEqual(http_policy.auth_error(headers), (401, 'UNAUTHORIZED'))


class AuthConfigurationHTTPTests(unittest.TestCase):
    def exercise(self, handler, callback):
        # Numeric metadata avoids unrelated reverse-DNS fixture latency.
        server = HTTPServer(('127.0.0.1', 0), handler, bind_and_activate=False)
        server.server_name = '127.0.0.1'
        server.socket.bind(server.server_address)
        server.server_address = server.socket.getsockname()
        server.server_port = server.server_address[1]
        server.server_activate()
        thread = Thread(target=server.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
        host = '127.0.0.1:' + str(server.server_port)
        try:
            with patch.dict(os.environ, {'ALLOWED_HOSTS': host, 'ALLOWED_ORIGINS': 'http://' + host}, clear=True):
                thread.start()
                callback(server.server_port)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())

    def request(self, port, method, path, headers=None, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def test_both_adapters_reject_invalid_auth_before_payload_and_remediation(self):
        def check(port):
            for value in INVALID:
                for keys in ({}, {'ACCESSDOC_API_KEY': KEY}, {'ACCESSDOC_API_KEYS': KEY}):
                    with self.subTest(value=value, keys=bool(keys)), patch.dict(
                            os.environ, {'ACCESSDOC_REQUIRE_AUTH': value, **keys}):
                        for path in ('/api/bundle', '/api/remediate'):
                            status, raw = self.request(port, 'POST', path, {
                                'Content-Type': 'application/json', 'Authorization': 'Bearer ' + KEY,
                                'X-API-Key': KEY}, b'not-json')
                            self.assertEqual(status, 503)
                            self.assertIn('AUTH_CONFIG_INVALID', raw.decode())
                            self.assertNotIn('synthetic-invalid-config-canary', raw.decode())
                            self.assertNotIn(KEY, raw.decode())
                        status, raw = self.request(port, 'GET', '/readyz')
                        self.assertEqual(status, 503)
                        self.assertIn('AUTH_CONFIG_INVALID', json.loads(raw)['readiness_reasons'])
                        status, raw = self.request(port, 'GET', '/limits')
                        self.assertEqual(status, 200)
                        self.assertIs(json.loads(raw)['api_key_required'], True)
        for adapter in (LocalHandler, ServerlessHandler):
            with self.subTest(adapter=adapter.__module__):
                self.exercise(adapter, check)

    def test_both_adapters_preserve_absent_false_and_true_auth_contract(self):
        def check(port):
            malformed_status = 422 if adapter is LocalHandler else 400
            for env, expected in (({}, malformed_status), ({'ACCESSDOC_REQUIRE_AUTH': 'false'}, malformed_status),
                                  ({'ACCESSDOC_REQUIRE_AUTH': 'true'}, 503),
                                  ({'ACCESSDOC_REQUIRE_AUTH': 'false', 'ACCESSDOC_API_KEY': KEY}, 401)):
                with self.subTest(env=env), patch.dict(os.environ, env):
                    status, _ = self.request(port, 'POST', '/api/bundle', {'Content-Type': 'application/json'}, b'not-json')
                    self.assertEqual(status, expected)
        for adapter in (LocalHandler, ServerlessHandler):
            with self.subTest(adapter=adapter.__module__):
                self.exercise(adapter, check)
