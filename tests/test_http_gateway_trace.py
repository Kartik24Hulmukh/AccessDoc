"""Actual native loopback serial/hedged calls inherit the HTTP trace.

Synthetic upstream and routing token only; no provider or external service.
"""
import contextlib
import http.client
import io
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from app import gateway, remediate, otlp_export
from app.gateway import ModelGateway, CANONICAL_CHAIN
from tests.test_hosted_lifecycle import Recorder
from tests.test_operational_controls import serve, local, hosted


class HttpGatewayTraceTests(unittest.TestCase):
    def test_inbound_trace_survives_native_work_and_completion(self):
        received = []
        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                received.append(self.headers.get('traceparent'))
                body = json.dumps({'choices': [{'message': {'content': 'Synthetic loopback plan'}}],
                                   'usage': {'total_tokens': 15}}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        runner = threading.Thread(target=lambda: upstream.serve_forever(poll_interval=.01))
        runner.start()
        payload = json.dumps({'scanner_input': {'violations': [{
            'id': 'image-alt', 'impact': 'serious', 'help': 'Synthetic missing alt',
            'nodes': [{'target': ['img']}],
        }]}}).encode()
        trace_id = 'c' * 32
        try:
            for delay in ('-1', '150'):
                for module, cls in ((local, local.Handler), (hosted, hosted.handler)):
                    with self.subTest(adapter=module.__name__, hedge_delay=delay):
                        received.clear()
                        gw = ModelGateway(api_key='synthetic-loopback-only', chain=CANONICAL_CHAIN[:2])
                        output, recorder = io.StringIO(), Recorder()
                        try:
                            with patch.object(gateway, 'MELIOUS_BASE_URL', f'http://127.0.0.1:{upstream.server_port}/v1'), \
                                 patch.object(remediate, '_GATEWAY', gw), \
                                 patch.object(otlp_export, 'get_exporter', return_value=recorder), \
                                 contextlib.redirect_stdout(output), \
                                 serve(module, cls, GATEWAY_HEDGE_DELAY_MS=delay) as server:
                                conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                                try:
                                    conn.request('POST', '/api/remediate', payload, {
                                        'Content-Type': 'application/json',
                                        'Authorization': 'Bearer synthetic-ops-pilot',
                                        'traceparent': '00-' + trace_id + '-' + 'd' * 16 + '-01',
                                    })
                                    response = conn.getresponse()
                                    data = json.loads(response.read())
                                    self.assertEqual(response.status, 200, data)
                                    self.assertFalse(data['fallback'])
                                    self.assertEqual(response.getheader('traceparent').split('-')[1], trace_id)
                                finally:
                                    conn.close()
                            self.assertTrue(received)
                            self.assertTrue(all(x.split('-')[1] == trace_id for x in received))
                            rows = [json.loads(x) for x in output.getvalue().splitlines() if x.startswith('{')]
                            calls = [x for x in rows if x.get('event', '').startswith('gateway_')]
                            self.assertTrue(calls, rows)
                            self.assertTrue(all(x['trace_id'] == trace_id for x in calls))
                            if delay != '-1':
                                self.assertTrue(any(x['event'] == 'gateway_dispatch' for x in calls))
                            completed = [x for x in rows if x.get('event') == 'http_request']
                            self.assertEqual(len(completed), 1)
                            self.assertEqual(completed[0]['trace_id'], trace_id)
                            servers = [(a, k) for a, k in recorder.spans if k.get('kind') == 2]
                            self.assertEqual(len(servers), 1)
                            self.assertEqual(servers[0][0][1], trace_id)
                            self.assertEqual(gw._session.snapshot()['active_calls'], 0)
                        finally:
                            gw._session.close()
        finally:
            upstream.shutdown()
            upstream.server_close()
            runner.join(3)
            self.assertFalse(runner.is_alive())
