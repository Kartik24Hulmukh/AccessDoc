"""Hosted completion correlation over real sockets, not a mocked ZIP endpoint."""
import contextlib
import io
import http.client
import json
import unittest
from unittest.mock import patch

from app import telemetry, otlp_export
from tests.test_operational_controls import serve, request, PAYLOAD, REMEDIATION_PAYLOAD, hosted


class Recorder:
    def __init__(self):
        self.spans = []

    def record(self, *args, **kwargs):
        self.spans.append((args, kwargs))
        return True

    def stats(self):
        return {'enabled': False, 'exported': 0}


class HostedLifecycleTests(unittest.TestCase):
    def test_all_response_paths_share_one_completion_context(self):
        matrix = (
            ('GET', '/healthz', None, 200, '/healthz'),
            ('HEAD', '/readyz', None, 200, '/readyz'),
            ('GET', '/static/app.js', None, 200, '/static/app.js'),
            ('GET', '/metrics', None, 200, '/metrics'),
            ('POST', '/api/bundle', PAYLOAD, 200, '/api/bundle'),
            ('POST', '/api/remediate', REMEDIATION_PAYLOAD, 200, '/api/remediate'),
            ('OPTIONS', '/api/bundle', None, 204, '/api/bundle'),
            ('PUT', '/api/bundle', None, 405, '/api/bundle'),
            ('GET', '/private-path-canary?private-query-canary', None, 404, '/[unmatched]'),
        )
        for method, path, body, expected, route in matrix:
            with self.subTest(method=method, path=path):
                recorder, output = Recorder(), io.StringIO()
                with patch.object(otlp_export, 'get_exporter', return_value=recorder), \
                     contextlib.redirect_stdout(output), serve(hosted, hosted.handler) as server:
                    status, headers, data = request(server, method, path, body)
                self.assertEqual(status, expected, data)
                if method == 'HEAD':
                    self.assertEqual(data, b'')
                rows = [json.loads(x) for x in output.getvalue().splitlines() if x.startswith('{')]
                completions = [x for x in rows if x.get('event') == 'http_request']
                self.assertEqual(len(completions), 1, rows)
                row = completions[0]
                self.assertEqual((row['method'], row['route'], row['status']), (method, route, expected))
                self.assertEqual(row['request_id'], headers['X-Request-ID'])
                trace = headers['traceparent'].split('-')
                self.assertEqual((row['trace_id'], row['span_id']), (trace[1], trace[2]))
                servers = [(a, k) for a, k in recorder.spans if k.get('kind') == 2]
                self.assertEqual(len(servers), 1, recorder.spans)
                a, k = servers[0]
                self.assertEqual((a[1], a[2]), (trace[1], trace[2]))
                self.assertEqual(a[6]['http.route'], route)
                self.assertEqual(a[6]['http.response.status_code'], expected)
                self.assertNotIn('private-path-canary', output.getvalue())
                self.assertNotIn('private-query-canary', output.getvalue())
                self.assertNotIn('synthetic-private-client', output.getvalue())

    def test_auth_denial_is_correlated_without_body_admission(self):
        recorder, output = Recorder(), io.StringIO()
        with patch.object(otlp_export, 'get_exporter', return_value=recorder), \
             contextlib.redirect_stdout(output), serve(hosted, hosted.handler) as server:
            status, headers, body = request(server, 'POST', '/api/bundle', authenticated=False, declared_only=True)
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(body)['request_id'], headers['X-Request-ID'])
        row = next(json.loads(x) for x in output.getvalue().splitlines() if '"event":"http_request"' in x)
        self.assertEqual(row['request_id'], headers['X-Request-ID'])
        self.assertEqual(len([1 for _, k in recorder.spans if k.get('kind') == 2]), 1)

    def test_route_and_method_vocabulary_is_finite(self):
        for path in ('/private-secret?token=private', '//private-secret', 'http://[invalid'):
            self.assertEqual(telemetry.http_route(path), '/[unmatched]')
        self.assertEqual(telemetry.http_route('/download/secret-token?q=secret'), '/download/[token]')
        self.assertEqual(telemetry.http_method('PRIVATE-CANARY'), '_OTHER')

    def test_keepalive_context_is_reset_without_phantom_completion(self):
        class KeepAlive(hosted.handler):
            protocol_version = 'HTTP/1.1'

        recorder, output = Recorder(), io.StringIO()
        with patch.object(otlp_export, 'get_exporter', return_value=recorder), \
             contextlib.redirect_stdout(output), serve(hosted, KeepAlive) as server:
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
            try:
                seen = []
                for trace_id, path in (('a' * 32, '/healthz'), ('b' * 32, '/readyz')):
                    conn.request('GET', path, headers={
                        'traceparent': '00-' + trace_id + '-' + 'c' * 16 + '-01',
                    })
                    response = conn.getresponse()
                    response.read()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.getheader('traceparent').split('-')[1], trace_id)
                    seen.append(response.getheader('X-Request-ID'))
                self.assertNotEqual(seen[0], seen[1])
            finally:
                conn.close()
        rows = [json.loads(x) for x in output.getvalue().splitlines() if x.startswith('{')]
        completions = [x for x in rows if x.get('event') == 'http_request']
        self.assertEqual(len(completions), 2, rows)
        self.assertEqual([x['trace_id'] for x in completions], ['a' * 32, 'b' * 32])
        self.assertEqual(len([1 for _, k in recorder.spans if k.get('kind') == 2]), 2)
