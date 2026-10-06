"""Real loopback dispatch regression: Vercel can bypass our parser envelope.

No provider or collector calls; synthetic keys/payloads only. Both runtime
shapes parse with stdlib but invoke HTTP methods without handler's envelope.
"""
import http.client
import json
import os
import socket
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

from api import handler as api
from app import telemetry


class RuntimeInline(api.handler):
    protocol_version = 'HTTP/1.1'

    def handle_one_request(self):
        # Deliberately NOT super(): models vc_init taking over this boundary.
        self.raw_requestline = self.rfile.readline(65537)
        if not self.raw_requestline:
            self.close_connection = True
            return
        if not self.parse_request():
            self.observe_completion()
            return
        self.dispatch_method()
        self.wfile.flush()
        self.observe_completion()

    def observe_completion(self):
        self.server.completions.append((
            getattr(self, '_request_scope_active', False),
            getattr(self, '_trace_ctx', None),
            getattr(telemetry._local, 'ctx', None)))

    def dispatch_method(self):
        method = getattr(self, 'do_' + self.command, None)
        if method is None:
            self.send_error(501)
        else:
            method()


class RuntimeDelegated(RuntimeInline):
    def dispatch_method(self):
        self.handle_request()

    def handle_request(self):
        method = getattr(self, 'do_' + self.command, None)
        if method is None:
            self.send_error(501)
        else:
            method()


class StdlibKeepAlive(api.handler):
    protocol_version = 'HTTP/1.1'
    observe_completion = RuntimeInline.observe_completion

    def handle_one_request(self):
        super().handle_one_request()
        if self.raw_requestline:
            self.observe_completion()


class VercelRuntimeLifecycleTests(unittest.TestCase):
    def exercise(self, handler, callback):
        env = {'ACCESSDOC_REQUIRE_AUTH': 'true', 'ACCESSDOC_API_KEY': 'synthetic-only',
               'ACCESSDOC_REMEDIATION_ENABLED': 'false', 'SOCKET_TIMEOUT_SECONDS': '2'}
        with patch.dict(os.environ, env, clear=True), \
             patch.object(telemetry, 'log_event', wraps=telemetry.log_event) as logs, \
             patch.object(telemetry, 'record_server_span', return_value=True) as spans:
            server = HTTPServer(('127.0.0.1', 0), handler)
            server.completions = []
            thread = threading.Thread(target=server.serve_forever,
                                      kwargs={'poll_interval': .01}, daemon=True)
            before = dict(api._METRICS)
            thread.start()
            try:
                callback(server.server_port, logs, spans, before)
                deadline = time.monotonic() + 2
                while len(server.completions) < spans.call_count and time.monotonic() < deadline:
                    time.sleep(.001)
                self.assertEqual(len(server.completions), spans.call_count)
                self.assertTrue(all(state == (False, None, None) for state in server.completions),
                                server.completions)
            finally:
                server.shutdown(); server.server_close(); thread.join(3)
                self.assertFalse(thread.is_alive())

    def request(self, port, method, path, body=None, headers=None, conn=None):
        own = conn is None
        conn = conn or http.client.HTTPConnection('127.0.0.1', port, timeout=3)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, response.read(), response.headers
        finally:
            if own:
                conn.close()

    def completed(self, logs, spans, expected):
        deadline = time.monotonic() + 2
        while spans.call_count < expected and time.monotonic() < deadline:
            time.sleep(.001)
        events = [c.kwargs for c in logs.call_args_list if c.args == ('http_request',)]
        self.assertEqual(len(events), expected)
        self.assertEqual(spans.call_count, expected)
        return events

    def test_browser_static_regression_both_runtime_dispatch_forms(self):
        for adapter in (RuntimeInline, RuntimeDelegated):
            with self.subTest(adapter=adapter.__name__):
                def check(port, logs, spans, before):
                    status, body, headers = self.request(port, 'GET', '/', headers={
                        'Accept': 'text/html,application/xhtml+xml'})
                    self.assertEqual(status, 200)
                    self.assertIn(b'<html', body.lower())
                    self.assertTrue(headers['X-Request-ID'])
                    self.assertIsNotNone(telemetry.parse_traceparent(headers['traceparent']))
                    self.completed(logs, spans, 1)
                    self.assertEqual(api._METRICS['requests_total'] - before['requests_total'], 1)
                self.exercise(adapter, check)

    def test_routes_auth_errors_head_options_and_exact_once(self):
        payload = json.dumps({'scanner_input': {'violations': [
            {'id': 'image-alt', 'impact': 'critical', 'nodes': [{'html': '<img>'}]}]}}).encode()
        good = {'Authorization': 'Bearer synthetic-only', 'Content-Type': 'application/json'}
        cases = [
            ('GET', '/', None, {'Accept': 'text/html'}, 200),
            ('GET', '/static/app.css', None, {}, 200),
            ('GET', '/static/app.js', None, {}, 200),
            ('GET', '/healthz', None, {}, 200),
            ('GET', '/readyz', None, {}, 200),
            ('GET', '/metrics', None, {}, 200),
            ('HEAD', '/', None, {'Accept': 'text/html'}, 200),
            ('HEAD', '/metrics', None, {}, 200),
            ('OPTIONS', '/api/bundle', None, {}, 204),
            ('POST', '/api/bundle', payload, good, 200),
            ('POST', '/api/bundle', payload, {'Content-Type': 'application/json'}, 401),
            ('POST', '/api/bundle', payload, {**good, 'Authorization': 'Bearer wrong'}, 401),
            ('POST', '/api/bundle', b'private-body-canary', good, 400),
            ('POST', '/api/remediate', b'{}', good, 503),
            ('GET', '/unknown-private-canary?token=private-query-canary', None, {}, 404),
            ('PUT', '/', None, {}, 405),
            ('TRACE', '/', None, {}, 501),
        ]
        for adapter in (RuntimeInline, RuntimeDelegated, StdlibKeepAlive):
            with self.subTest(adapter=adapter.__name__):
                def check(port, logs, spans, before):
                    ids, traces = [], []
                    for method, path, body, headers, expected in cases:
                        status, output, response = self.request(port, method, path, body, headers)
                        self.assertEqual(status, expected, (method, path))
                        ids.append(response['X-Request-ID']); traces.append(response['traceparent'])
                        self.assertEqual(len(response.get_all('X-Request-ID')), 1)
                        self.assertEqual(len(response.get_all('traceparent')), 1)
                        if method == 'HEAD' or status == 204:
                            self.assertEqual(output, b'')
                        if method == 'POST' and status == 200:
                            self.assertTrue(output.startswith(b'PK'))
                    events = self.completed(logs, spans, len(cases))
                    self.assertEqual(len(set(ids)), len(cases))
                    self.assertEqual(len(set(traces)), len(cases))
                    self.assertEqual(api._METRICS['requests_total'] - before['requests_total'], len(cases))
                    self.assertEqual(api._METRICS['errors_total'] - before['errors_total'],
                                     sum(c[-1] >= 400 for c in cases))
                    for event, call, request_id, trace, case in zip(events, spans.call_args_list, ids, traces, cases):
                        ctx, method, route, status, started, ended = call.args
                        self.assertEqual((event['request_id'], ctx['request_id']), (request_id, request_id))
                        self.assertEqual(telemetry.traceparent_header(ctx), trace)
                        self.assertEqual(event['status'], case[-1]); self.assertEqual(status, case[-1])
                        self.assertEqual(method, case[0]); self.assertLessEqual(started, ended)
                        self.assertEqual(event['route'], route)
                    rendered = str(events) + str(spans.call_args_list)
                    for secret in ('synthetic-only', 'private-body-canary', 'private-query-canary', 'unknown-private-canary'):
                        self.assertNotIn(secret, rendered)
                self.exercise(adapter, check)

    def test_keepalive_inbound_parent_reset_and_teardown(self):
        for adapter in (RuntimeInline, RuntimeDelegated, StdlibKeepAlive):
            with self.subTest(adapter=adapter.__name__):
                def check(port, logs, spans, before):
                    parent = '00-' + '1' * 32 + '-' + '2' * 16 + '-01'
                    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
                    try:
                        first = self.request(port, 'GET', '/healthz', headers={'traceparent': parent}, conn=conn)
                        second = self.request(port, 'HEAD', '/healthz', conn=conn)
                    finally:
                        conn.close()
                    self.completed(logs, spans, 2)
                    a, b = [c.args[0] for c in spans.call_args_list]
                    self.assertEqual(a['trace_id'], '1' * 32)
                    self.assertEqual(a['parent_span_id'], '2' * 16)
                    self.assertNotEqual(b['trace_id'], a['trace_id'])
                    self.assertIsNone(b['parent_span_id'])
                    self.assertNotEqual(first[2]['X-Request-ID'], second[2]['X-Request-ID'])
                    self.assertEqual(api._METRICS['requests_total'] - before['requests_total'], 2)
                self.exercise(adapter, check)

    def test_unhandled_method_exception_is_private_accounted_and_cleared(self):
        for adapter in (RuntimeInline, RuntimeDelegated, StdlibKeepAlive):
            with self.subTest(adapter=adapter.__name__):
                def check(port, logs, spans, before):
                    with patch.object(api.handler, '_send_static', side_effect=RuntimeError('private-exception-canary')):
                        status, body, headers = self.request(port, 'GET', '/', headers={'Accept': 'text/html'})
                    self.assertEqual(status, 500)
                    self.assertNotIn(b'private-exception-canary', body)
                    events = self.completed(logs, spans, 1)
                    self.assertEqual(events[0]['status'], 500)
                    self.assertEqual(api._METRICS['errors_total'] - before['errors_total'], 1)
                    self.assertNotIn('private-exception-canary', str(events) + str(spans.call_args_list))
                self.exercise(adapter, check)

    def test_stdlib_idle_keepalive_does_not_reaccount_previous_request(self):
        def check(port, logs, spans, before):
            with patch.dict(os.environ, {'SOCKET_TIMEOUT_SECONDS': '.05'}):
                conn = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
                try:
                    self.request(port, 'GET', '/static/app.css', conn=conn)
                    # Wait for the server to close an idle HTTP/1.1 connection.
                    self.assertEqual(conn.sock.recv(1), b'')
                finally:
                    conn.close()
            self.completed(logs, spans, 1)
            self.assertEqual(api._METRICS['requests_total'] - before['requests_total'], 1)
            self.assertEqual(api._METRICS['errors_total'] - before['errors_total'], 0)
        self.exercise(StdlibKeepAlive, check)

    def test_stdlib_malformed_request_remains_logged_without_reflection(self):
        def check(port, logs, spans, before):
            with socket.create_connection(('127.0.0.1', port), timeout=3) as sock:
                sock.sendall(b'GET /private-parse-canary HTTP/1.1 extra\r\n\r\n')
                result = b''
                while True:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    result += chunk
            self.assertNotIn(b'private-parse-canary', result)
            events = self.completed(logs, spans, 1)
            self.assertEqual(events[0]['status'], 400)
            self.assertNotIn('private-parse-canary', str(events))
            self.assertEqual(api._METRICS['requests_total'] - before['requests_total'], 1)
        for adapter in (StdlibKeepAlive, RuntimeInline, RuntimeDelegated):
            with self.subTest(adapter=adapter.__name__):
                self.exercise(adapter, check)
