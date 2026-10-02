"""Real loopback admission controls; synthetic credentials, no provider calls."""
import contextlib
import http.client
import json
import os
import threading
import time
import unittest
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

import app.main as local
import api.handler as hosted
from app.bundle import validate_bundle
from app.http_policy import operation_state, readiness_reasons

ENV = {
    'ACCESSDOC_REQUIRE_AUTH': 'true', 'ACCESSDOC_API_KEY': 'synthetic-ops-pilot',
    'ACCESSDOC_API_KEYS': '', 'ACCESSDOC_GENERATION_ENABLED': 'true',
    'ACCESSDOC_REMEDIATION_ENABLED': 'true', 'MELIOUS_API_KEY': '',
    'ACCESSDOC_STRICT_GATEWAY': 'false', 'RATE_LIMIT_PER_MINUTE': '100000',
    'OTEL_EXPORTER_OTLP_ENDPOINT': '', 'OTEL_EXPORTER_OTLP_TRACES_ENDPOINT': '',
}
PAYLOAD = json.dumps({'scanner_input': {'violations': []},
                      'client_name': 'synthetic-private-client'}).encode()
REMEDIATION_PAYLOAD = json.dumps({
    'scanner_input': json.loads((Path(__file__).resolve().parents[1] / 'fixtures/axe-sample.json').read_text()),
    'client_name': 'synthetic-private-client',
}).encode()

@contextlib.contextmanager
def serve(module, cls, **env):
    server = HTTPServer(('127.0.0.1', 0), cls)
    runner = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01))
    with patch.dict(os.environ, {**ENV, 'ALLOWED_HOSTS': f'127.0.0.1:{server.server_port}', **env}), \
         patch.object(local, 'READY', True):
        runner.start()
        try:
            yield server
        finally:
            server.shutdown()
            server.server_close()
            runner.join(3)
            if runner.is_alive():
                raise AssertionError('loopback server did not stop')


def request(server, method, path, body=None, authenticated=True, declared_only=False):
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
    headers = {'Content-Type': 'application/json', 'Connection': 'close'}
    if authenticated:
        headers['Authorization'] = 'Bearer synthetic-ops-pilot'
    if declared_only:
        headers['Content-Length'] = '1000000'
    try:
        conn.request(method, path, body, headers)
        r = conn.getresponse()
        pairs = r.getheaders()
        for name in ('x-request-id', 'traceparent'):
            if sum(k.lower() == name for k, _ in pairs) != 1:
                raise AssertionError('missing or duplicate correlation header: ' + name)
        return r.status, dict(pairs), r.read()
    finally:
        conn.close()


class OperationalControlsTests(unittest.TestCase):
    adapters = ((local, local.Handler), (hosted, hosted.handler))

    def test_disabled_work_does_not_read_body_or_acquire_capacity(self):
        for module, cls in self.adapters:
            routes = ('/api/bundle', '/api/generate', '/api/v1/generate') if module is local else ('/', '/api/bundle')
            rem = ('/api/remediate',) if module is local else ('/api/remediate', '/api/v1/remediate')
            for flag, paths, code in (
                ('ACCESSDOC_GENERATION_ENABLED', routes, 'GENERATION_DISABLED'),
                ('ACCESSDOC_REMEDIATION_ENABLED', rem, 'REMEDIATION_DISABLED'),
            ):
                body_reader = '_read_json' if module is local else '_read_bounded_body'
                pool = Mock()
                pool.acquire.side_effect = AssertionError('disabled work acquired capacity')
                with serve(module, cls, **{flag: 'false'}) as server, \
                     patch.object(cls, body_reader, side_effect=AssertionError('disabled work read body')), \
                     patch.object(module, 'GENERATION_CAPACITY', pool), \
                     patch.object(module, 'REMEDIATION_CAPACITY', pool):
                    for path in paths:
                        started = time.monotonic()
                        status, headers, body = request(server, 'POST', path, declared_only=True)
                        self.assertEqual(status, 503, body)
                        self.assertIn(code, body.decode())
                        self.assertEqual(headers.get('Retry-After'), '30')
                        self.assertLess(time.monotonic() - started, 1)
                    pool.acquire.assert_not_called()
                    status, _, _ = request(server, 'POST', paths[0], authenticated=False, declared_only=True)
                    self.assertEqual(status, 401)

    def test_readiness_head_and_liveness_parity(self):
        for module, cls in self.adapters:
            for env, status, reason in (
                ({'ACCESSDOC_GENERATION_ENABLED': 'false'}, 503, 'GENERATION_DISABLED'),
                ({'ACCESSDOC_REMEDIATION_ENABLED': 'false'}, 200, None),
                ({'ACCESSDOC_API_KEY': ''}, 503, 'AUTH_NOT_CONFIGURED'),
                ({'ACCESSDOC_GENERATION_ENABLED': 'private-invalid-canary'}, 503, 'GENERATION_CONFIG_INVALID'),
                ({'ACCESSDOC_REMEDIATION_ENABLED': ''}, 503, 'REMEDIATION_CONFIG_INVALID'),
            ):
                with self.subTest(adapter=module.__name__, env=env), serve(module, cls, **env) as server:
                    get_status, headers, body = request(server, 'GET', '/readyz')
                    head_status, head_headers, head_body = request(server, 'HEAD', '/readyz')
                    self.assertEqual(get_status, status, body)
                    self.assertEqual(head_status, status)
                    self.assertEqual(head_body, b'')
                    self.assertGreater(int(head_headers['Content-Length']), 0)
                    self.assertNotIn(b'private-invalid-canary', body)
                    obj = json.loads(body)
                    self.assertIn('tracing', obj)
                    self.assertIn('operations', obj)
                    if reason:
                        self.assertIn(reason, obj['readiness_reasons'])
                    self.assertEqual(request(server, 'GET', '/healthz')[0], 200)
                    self.assertEqual(request(server, 'HEAD', '/healthz')[0], 200)

    def test_real_zip_survives_remediation_disable_and_reenable(self):
        for module, cls in self.adapters:
            with self.subTest(adapter=module.__name__), serve(module, cls, ACCESSDOC_REMEDIATION_ENABLED='false') as server:
                status, headers, body = request(server, 'POST', '/api/bundle', PAYLOAD)
                self.assertEqual(status, 200, body)
                self.assertTrue(validate_bundle(body)['valid'])
                self.assertIn('traceparent', headers)
                self.assertEqual(request(server, 'POST', '/api/remediate', PAYLOAD)[0], 503)
                with patch.dict(os.environ, {'ACCESSDOC_REMEDIATION_ENABLED': 'true'}):
                    status, _, body = request(server, 'POST', '/api/remediate', REMEDIATION_PAYLOAD)
                    self.assertEqual(status, 200, body)
                    self.assertEqual(json.loads(body)['attempts'], 0)
                with patch.dict(os.environ, {'ACCESSDOC_GENERATION_ENABLED': 'false'}):
                    self.assertEqual(request(server, 'POST', '/api/bundle', PAYLOAD)[0], 503)
                self.assertEqual(request(server, 'POST', '/api/bundle', PAYLOAD)[0], 200)

    def test_strict_flag_configuration(self):
        for value in ('garbage', '', '1', 'yes'):
            with self.subTest(value=value), patch.dict(os.environ, {**ENV, 'ACCESSDOC_GENERATION_ENABLED': value}):
                self.assertFalse(operation_state()['generation_enabled'])
                self.assertIn('GENERATION_CONFIG_INVALID', readiness_reasons())
        with patch.dict(os.environ, {**ENV, 'ACCESSDOC_GENERATION_ENABLED': ' TRUE '}):
            self.assertTrue(operation_state()['generation_enabled'])
