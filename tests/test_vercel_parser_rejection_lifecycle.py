"""Partial runtime parsing must not reuse headers from a keepalive request."""
import http.client
import os
import socket
import threading
import time
import unittest
from http.server import HTTPServer
from unittest.mock import patch

from api import handler as api
from app import telemetry
from tests.test_vercel_runtime_lifecycle import RuntimeInline, RuntimeDelegated, StdlibKeepAlive


class BoundedRuntimeInline(RuntimeInline):
    def handle_one_request(self):
        self.raw_requestline = self.rfile.readline(65537)
        if len(self.raw_requestline) > 65536:
            self.requestline = ''
            self.request_version = ''
            self.command = ''
            self.send_error(414)
            self.observe_completion()
            return
        if not self.raw_requestline:
            self.close_connection = True
            return
        if not self.parse_request():
            self.observe_completion()
            return
        self.dispatch_method()
        self.wfile.flush()
        self.observe_completion()


class BoundedRuntimeDelegated(BoundedRuntimeInline, RuntimeDelegated):
    dispatch_method = RuntimeDelegated.dispatch_method


class ParserRejectionLifecycleTests(unittest.TestCase):
    def exercise(self, adapter, raw, expected, parsed_parent=None):
        first_parent = '00-' + '1' * 32 + '-' + '2' * 16 + '-01'
        with patch.dict(os.environ, {'SOCKET_TIMEOUT_SECONDS': '2'}, clear=True), \
             patch.object(telemetry, 'record_server_span', return_value=True) as spans, \
             patch.object(telemetry, 'log_event', return_value={}) as logs:
            server = HTTPServer(('127.0.0.1', 0), adapter)
            server.completions = []
            thread = threading.Thread(target=server.serve_forever,
                                      kwargs={'poll_interval': .01}, daemon=True)
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
            before = dict(api._METRICS)
            thread.start()
            try:
                conn.request('GET', '/healthz', headers={'traceparent': first_parent})
                response = conn.getresponse(); response.read()
                first_id = response.getheader('X-Request-ID')
                conn.sock.sendall(raw)
                output = b''
                while True:
                    chunk = conn.sock.recv(65536)
                    if not chunk:
                        break
                    output += chunk
                deadline = time.monotonic() + 2
                while len(server.completions) < 2 and time.monotonic() < deadline:
                    time.sleep(.001)
                self.assertEqual(spans.call_count, 2)
                events = [c.kwargs for c in logs.call_args_list if c.args == ('http_request',)]
                self.assertEqual(len(events), 2)
                self.assertEqual(server.completions, [(False, None, None)] * 2)
                self.assertEqual(api._METRICS['requests_total'] - before['requests_total'], 2)
                self.assertEqual(api._METRICS['errors_total'] - before['errors_total'], 1)
                first, rejected = [c.args for c in spans.call_args_list]
                ctx = rejected[0]
                self.assertEqual(first[0]['trace_id'], '1' * 32)
                self.assertEqual(rejected[3], expected)
                self.assertEqual(events[1]['status'], expected)
                self.assertNotEqual(ctx['request_id'], first_id)
                self.assertEqual(ctx['request_id'], events[1]['request_id'])
                self.assertNotEqual(ctx['span_id'], first[0]['span_id'])
                if parsed_parent:
                    self.assertEqual(ctx['trace_id'], '3' * 32)
                    self.assertEqual(ctx['parent_span_id'], '4' * 16)
                else:
                    self.assertNotIn(ctx['trace_id'], ('1' * 32, '3' * 32))
                    self.assertIsNone(ctx['parent_span_id'])
                if output.startswith(b'HTTP/'):
                    self.assertIn((' ' + str(expected) + ' ').encode(), output.split(b'\r\n')[0])
                    self.assertIn(('traceparent: ' + telemetry.traceparent_header(ctx)).encode(), output)
                self.assertNotIn(b'private-parser-canary', output)
                self.assertNotIn('private-parser-canary', str(events) + str(spans.call_args_list))
            finally:
                conn.close(); server.shutdown(); server.server_close(); thread.join(3)
                self.assertFalse(thread.is_alive())

    def test_parser_rejections_discard_partial_or_prior_headers(self):
        partial = b'traceparent: 00-' + b'3' * 32 + b'-' + b'4' * 16 + b'-01\r\n'
        cases = [
            (b'GET /private-parser-canary HTTP/1.1\r\n' + partial + b'X-Probe: no-trace\r\n' * 101 + b'\r\n', 431),
            (b'GET /private-parser-canary HTTP/1.1\r\n' + partial + b'X-Probe: ' + b'x' * 65537 + b'\r\n\r\n', 431),
            (b'GET /private-parser-canary HTTP/1.1 extra\r\n\r\n', 400),
            (b'GET /private-parser-canary HTTP/2.0\r\n\r\n', 505),
            (b'GET /' + b'x' * 65537 + b' HTTP/1.1\r\n\r\n', 414),
        ]
        for adapter in (BoundedRuntimeInline, BoundedRuntimeDelegated, StdlibKeepAlive):
            for index, (raw, expected) in enumerate(cases):
                with self.subTest(adapter=adapter.__name__, case=index, expected=expected):
                    self.exercise(adapter, raw, expected)

    def test_fully_parsed_unsupported_501_keeps_current_inbound_parent(self):
        parent = '00-' + '3' * 32 + '-' + '4' * 16 + '-01'
        raw = ('TRACE /private-parser-canary HTTP/1.1\r\ntraceparent: ' + parent + '\r\n\r\n').encode()
        for adapter in (RuntimeInline, RuntimeDelegated, StdlibKeepAlive):
            with self.subTest(adapter=adapter.__name__):
                self.exercise(adapter, raw, 501, parsed_parent=parent)
