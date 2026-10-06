"""PDF table display folding must not change canonical supplied evidence.

Exercises actual ReportLab layout and both production HTTP handlers over
loopback. No provider, remote service, or optional PDF engine is involved.
"""
import copy
import html
import http.client
import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from api import handler as hosted
from app import main, reporter, service
from app.bundle import build_bundle, validate_bundle
from app.limits import MAX_HTTP_BODY_BYTES, MAX_STRING_CHARS
from app.models import AuditSummary, AuditViolation
from app.parser import parse_axe_json
from app.receipt_builder import build_receipt, receipt_json_str
from app.safe_text import safe_text


def sample_body():
    path = Path(__file__).resolve().parents[1] / 'public/sample/axe-sample.json'
    return {'scanner_input': json.loads(path.read_text(encoding='utf-8')),
            'audit_date': '2026-10-06'}


def edge_bodies():
    for label, field, value in (
        ('newline-id', 'id', 'x\n' * 300),
        ('newline-description', 'description', '\n' * 70),
        ('crlf-tab-markup', 'id', '<b>rule & "quoted"</b>\r\n\t' * 65),
    ):
        body = sample_body()
        body['scanner_input']['violations'][0][field] = value
        if label == 'crlf-tab-markup':
            body['scanner_input']['violations'][0]['description'] = (
                '<img src=x onerror="bad">\r\n\t& <script>bad</script>'
            )
        yield label, body


class ReporterTableLinefoldTests(unittest.TestCase):
    def expected_receipt(self, body):
        summary, violations = parse_axe_json(body['scanner_input'], allow_oversized=False)
        return receipt_json_str(build_receipt(summary, violations, {
            'audit_date': body['audit_date'],
            'client_name': body.get('client_name', 'Client'),
        }))

    def assert_bundle_evidence(self, data, body):
        verdict = validate_bundle(data)
        self.assertTrue(verdict['valid'], verdict['errors'])
        with ZipFile(BytesIO(data)) as archive:
            self.assertTrue(archive.read('report.pdf').startswith(b'%PDF'))
            self.assertEqual(archive.read('receipt.json').decode(), self.expected_receipt(body))
            document = archive.read('report.html').decode()
            summary, violations = parse_axe_json(body['scanner_input'], allow_oversized=False)
            for finding in violations:
                self.assertIn(html.escape(finding.id), document)
                self.assertIn(html.escape(finding.description), document)
            self.assertIn('DRAFT - unreviewed supplied evidence', document)
            self.assertNotIn('<script>bad</script>', document)
            self.assertNotIn('<img src=x onerror="bad">', document)
            self.assertEqual(json.loads(archive.read('receipt.json'))['summary']['total_violations'],
                             summary.total_violations)

    def test_newline_edges_build_valid_bundles_without_evidence_mutation(self):
        for label, body in edge_bodies():
            with self.subTest(case=label):
                before = copy.deepcopy(body)
                self.assertLess(len(json.dumps(body).encode()), MAX_HTTP_BODY_BYTES)
                for entry in body['scanner_input']['violations']:
                    self.assertLessEqual(len(entry.get('id', '')), MAX_STRING_CHARS)
                    self.assertLessEqual(len(entry.get('description', '')), MAX_STRING_CHARS)
                # Pre-render core is a baseline even when old PDF layout fails.
                with patch.object(service, 'generate_pdf_report', return_value=b'%PDF baseline'):
                    canonical = service.build_artifacts(body)
                artifacts = service.build_artifacts(body)
                self.assertEqual(artifacts.receipt_json, canonical.receipt_json)
                self.assertEqual(artifacts.html_bytes, canonical.html_bytes)
                self.assertEqual(artifacts.openacr_yaml, canonical.openacr_yaml)
                self.assertEqual(body, before)
                self.assert_bundle_evidence(build_bundle(artifacts), body)

    def test_all_finding_table_fields_are_single_line_escaped_and_nonmutating(self):
        finding = AuditViolation(
            id='rule\r\n\t<b>unsafe & quoted</b>' + 'x\n' * 300,
            impact='serious\n\t', nodes=1,
            description='<img src=x>\r\n\t& "quoted"', help_url='',
            wcag_scs=['1.1.1\n\t'], source='manual\r\n\t<script>bad</script>',
            target='#evidence',
        )
        original_finding = copy.deepcopy(finding)
        summary = AuditSummary(serious=1, total_violations=1)
        captured = []
        original_table = reporter.Table

        def capture(rows, *args, **kwargs):
            if rows[0] == ['Rule ID', 'Impact', 'Nodes', 'WCAG SC', 'Description']:
                captured.extend(copy.deepcopy(rows[1:]))
            return original_table(rows, *args, **kwargs)

        with patch.object(reporter, 'Table', side_effect=capture):
            pdf = reporter.generate_pdf_report(summary, [finding], audit_date='2026-10-06')
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertEqual(finding, original_finding)
        self.assertEqual(len(captured), 1)
        for cell in captured[0]:
            self.assertNotIn('\n', cell)
            self.assertNotIn('\t', cell)
            self.assertNotIn('\r', cell)
            self.assertNotIn('<', cell)
            self.assertNotIn('>', cell)
        fold = lambda value: safe_text(value).replace('\n', ' ').replace('\t', ' ')
        self.assertEqual(captured[0], [
            fold(finding.id), fold(finding.impact), '1',
            fold(', '.join(finding.wcag_scs)) + ' [' + fold(finding.source) + ']',
            fold(finding.description),
        ])

    def test_healthy_sample_exact_pdf_receipt_attestation_and_bundle_bytes(self):
        body = sample_body()
        # safe_text is exactly the former table-field display implementation.
        # Local byte comparison avoids a version-specific ReportLab golden hash.
        with patch.object(reporter, '_table_display', safe_text, create=True):
            baseline = service.build_artifacts(body)
            baseline_zip = build_bundle(baseline)
        actual = service.build_artifacts(body)
        self.assertEqual(actual.payloads(), baseline.payloads())
        self.assertEqual(build_bundle(actual), baseline_zip)
        self.assert_bundle_evidence(baseline_zip, body)

    def test_pending_display_and_global_safe_text_keep_intentional_linebreaks(self):
        value = 'one\n\ttwo\r\nthree'
        self.assertEqual(safe_text(value), 'one\n\ttwo\nthree')
        self.assertEqual(reporter._pending_display(value, ''), safe_text(value))
        pending = {'scanner_input': {'violations': [], 'incomplete': [{
            'id': 'pending', 'description': value, 'nodes': [{'target': ['#pending']}],
        }]}, 'audit_date': '2026-10-06'}
        with patch.object(reporter, '_table_display', safe_text, create=True):
            baseline = build_bundle(service.build_artifacts(pending))
        actual = build_bundle(service.build_artifacts(pending))
        self.assertEqual(actual, baseline)
        self.assertTrue(validate_bundle(actual)['valid'])

    def test_both_real_http_adapters_accept_within_limit_hostile_lines(self):
        env = {'ACCESSDOC_API_KEY': '', 'ACCESSDOC_API_KEYS': '',
               'ACCESSDOC_REQUIRE_AUTH': 'false', 'RATE_LIMIT_PER_MINUTE': '100000',
               'ACCESSDOC_ALLOW_OVERSIZED': '', 'ACCESSDOC_GENERATION_ENABLED': 'true'}
        with patch.dict(os.environ, env):
            for adapter in (main.Handler, hosted.handler):
                server = ThreadingHTTPServer(('127.0.0.1', 0), adapter)
                thread = threading.Thread(target=server.serve_forever,
                                          kwargs={'poll_interval': 0.01}, daemon=True)
                thread.start()
                try:
                    with patch.dict(os.environ, {'ALLOWED_HOSTS': f'127.0.0.1:{server.server_port}'}):
                        for label, body in list(edge_bodies()) + [('healthy-recovery', sample_body())]:
                            with self.subTest(adapter=adapter.__module__, case=label):
                                raw = json.dumps(body).encode()
                                self.assertLess(len(raw), MAX_HTTP_BODY_BYTES)
                                conn = http.client.HTTPConnection('127.0.0.1', server.server_port,
                                                                  timeout=10)
                                try:
                                    conn.request('POST', '/api/bundle', raw,
                                                 {'Content-Type': 'application/json'})
                                    response = conn.getresponse()
                                    data = response.read()
                                    self.assertEqual(response.status, 200, data)
                                    self.assertIn('application/zip', response.getheader('Content-Type'))
                                    self.assert_bundle_evidence(data, body)
                                finally:
                                    conn.close()
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)
                    self.assertFalse(thread.is_alive())


if __name__ == '__main__':
    unittest.main()
