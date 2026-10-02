"""Bounded source fidelity regressions; synthetic evidence, not human review."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from app.eaa import generate_eaa_pack
from app.models import AuditSummary, AuditViolation
from app.reporter import generate_pdf_report
from app.sarif import FINGERPRINT_KEY, generate_sarif
from app.receipt_builder import compute_finding_fingerprint


def finding(source='manual', rule='image-alt', sc='2.1.1', help_url=''):
    return AuditViolation(id=rule, impact='serious', description=f'{source} observation',
                          wcag_scs=[sc], nodes=1, source=source, help_url=help_url,
                          target=f'#{source}')


class CrossExportSourceFidelityTests(unittest.TestCase):
    def test_pdf_neutral_metadata_draft_and_source_breakdown(self):
        cases = [[], [finding()], [finding('automated')],
                 [finding('automated'), finding(), finding('imported')]]
        for findings in cases:
            with self.subTest(sources=[v.source for v in findings]), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'evidence.pdf'
                # Deliberately stale summary source count: actual supplied rows win.
                path.write_bytes(generate_pdf_report(AuditSummary(total_violations=99,
                    manual_findings=99, url='https://example.invalid', engine_version='4.11.0'), findings))
                text = subprocess.check_output(['pdftotext', str(path), '-'], text=True)
                metadata = subprocess.check_output(['pdfinfo', str(path)], text=True)
                self.assertIn('Supplied Accessibility Evidence Report', text)
                self.assertIn('Supplied accessibility evidence', metadata)
                self.assertNotIn('Automated Audit Report', text)
                self.assertNotIn('automated coverage only', metadata)
                self.assertIn('DRAFT - UNREVIEWED', text)
                self.assertIn('No reviewer approval is recorded', text)
                self.assertIn(f'Automated findings: {sum(v.source == "automated" for v in findings)}', text)
                self.assertIn(f'Supplied manual findings: {sum(v.source == "manual" for v in findings)}', text)
                self.assertIn(f'Other supplied findings: {sum(v.source not in ("manual", "automated") for v in findings)}', text)
                self.assertIn('not independently verified', text)
                self.assertNotIn('PDF/UA', text + metadata)
                if not findings:
                    self.assertIn('No supplied findings', text)
                    self.assertIn('not evidence of conformance', text)

    def test_sarif_collision_rule_neutral_in_both_orders_results_unchanged(self):
        auto = finding('automated', sc='1.1.1', help_url='https://example.invalid/axe')
        manual = finding()
        rules = []
        for findings in ([auto, manual], [manual, auto]):
            run = json.loads(generate_sarif(AuditSummary(), findings))['runs'][0]
            rule, = run['tool']['driver']['rules']
            rules.append(rule)
            self.assertEqual(rule['id'], 'image-alt')
            self.assertEqual(rule['properties']['source'], 'mixed')
            self.assertEqual(rule['properties']['sources'], ['automated', 'manual'])
            self.assertEqual(rule['properties']['wcag_success_criteria'], ['1.1.1', '2.1.1'])
            self.assertIn('manual-finding', rule['properties']['tags'])
            self.assertNotIn('helpUri', rule)
            self.assertIn('result', rule['fullDescription']['text'].lower())
            self.assertEqual(len(run['results']), 2)
            for result, original in zip(run['results'], findings):
                self.assertEqual(result['ruleId'], original.id)
                self.assertEqual(result['ruleIndex'], 0)
                self.assertEqual(result['properties']['source'], original.source)
                self.assertEqual(result['partialFingerprints'][FINGERPRINT_KEY],
                    compute_finding_fingerprint(original.id, original.source, original.target))
                self.assertIn(original.description, result['message']['text'])
        self.assertEqual(rules[0], rules[1])

    def test_sarif_manual_no_help_does_not_invent_axe_uri(self):
        for source in ('manual', 'imported'):
            run = json.loads(generate_sarif(AuditSummary(), [finding(source)]))['runs'][0]
            self.assertNotIn('helpUri', run['tool']['driver']['rules'][0])

    def test_sarif_supplied_help_preserved_and_automated_fallback_retained(self):
        for source in ('manual', 'automated'):
            run = json.loads(generate_sarif(AuditSummary(), [finding(source, help_url='https://example.invalid/help')]))['runs'][0]
            self.assertEqual(run['tool']['driver']['rules'][0]['helpUri'], 'https://example.invalid/help')
        rule = json.loads(generate_sarif(AuditSummary(), [finding('automated')]))['runs'][0]['tool']['driver']['rules'][0]
        self.assertEqual(rule['helpUri'], 'https://dequeuniversity.com/rules/axe/')

    def test_eaa_known_levels_and_no_guessed_en_clause(self):
        findings = [finding(sc=sc) for sc in ('2.1.1', '1.4.3', '1.4.6', '1.2.4', '99.9.9')]
        text = generate_eaa_pack(AuditSummary(), findings)
        for row in ('| 2.1.1 | 9.2.1.1 | A |', '| 1.4.3 | 9.1.4.3 | AA |',
                    '| 1.4.6 | 9.1.4.6 | AAA |', '| 1.2.4 | Not mapped | AA |',
                    '| 99.9.9 | Not mapped | Unknown |'):
            self.assertIn(row, text)
        self.assertNotIn('9.99.9.9', text)
        self.assertNotIn('9.1.2.4', text)
        self.assertIn('not a complete or independently validated standards mapping', text)


class PendingPdfFidelityTests(unittest.TestCase):
    def pdf_text(self, summary):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'pending.pdf'
            path.write_bytes(generate_pdf_report(summary, []))
            return subprocess.check_output(['pdftotext', str(path), '-'], text=True)

    def test_pending_details_remain_unresolved_not_findings(self):
        summary = AuditSummary(total_incomplete=1)
        summary.pending_checks = [{'id': 'focus-review', 'description': 'Observe modal focus',
            'help_url': 'https://example.invalid/check', 'target': '#modal',
            'source': 'automated', 'status': 'needs-review'}]
        text = self.pdf_text(summary)
        for value in ('Unresolved checks', 'focus-review', 'Observe modal focus', '#modal',
                      'automated', 'needs-review', 'neither violations nor passes'):
            self.assertIn(value, text)
        self.assertIn('Total supplied findings: 0', text)

    def test_pending_missing_detail_falls_back_without_invention(self):
        summary = AuditSummary(total_incomplete=2)
        summary.pending_checks = []
        text = self.pdf_text(summary)
        self.assertIn('Scanner-reported unresolved rule count: 2', text)
        self.assertIn('No structured details supplied', text)
        summary.pending_checks = [{}]
        text = self.pdf_text(summary)
        self.assertIn('Unidentified check', text)
        self.assertIn('Description not supplied', text)
        self.assertIn('Source not supplied', text)

    def test_pending_display_bound_and_long_detail_are_explicit(self):
        summary = AuditSummary(total_incomplete=51)
        summary.pending_checks = [{'id': f'pending-{i}', 'description': 'x' * 2000,
                                  'source': 'automated', 'target': '#x'} for i in range(51)]
        text = self.pdf_text(summary)
        self.assertIn('Showing 50 of 51 supplied unresolved checks', text)
        self.assertIn('1 additional check not displayed', text)
        self.assertIn('Display shortened', text)
        self.assertIn('receipt.json', text)
        self.assertNotIn('pending-50', text)


class IntegratedSourceFidelityTests(unittest.TestCase):
    def test_actual_bundle_mixed_sources_pending_pdf_and_sarif_agree(self):
        from app.service import build_artifacts
        from app.bundle import build_bundle, validate_bundle
        artifacts = build_artifacts({'scanner_input': {
            'url': 'https://example.invalid', 'testEngine': {'version': '4.11.0'},
            'violations': [{'id': 'image-alt', 'impact': 'serious',
                'description': 'Synthetic automated image observation', 'tags': ['wcag111'],
                'nodes': [{'target': ['#auto']}]}],
            'incomplete': [{'id': 'focus-review', 'description': 'Unresolved focus observation',
                'nodes': [{'target': ['#modal']}]}]},
            'manual_findings': [{'id': 'image-alt', 'description': 'Supplied manual image observation',
                'wcag_scs': ['1.1.1'], 'target': '#manual'}],
            'include_eaa': True, 'include_sarif': True, 'include_vpat': True,
            'audit_date': '2026-10-02'})
        self.assertTrue(validate_bundle(build_bundle(artifacts))['valid'])
        receipt = json.loads(artifacts.receipt_json)
        self.assertEqual([v['source'] for v in receipt['violations']], ['automated', 'manual'])
        self.assertEqual(receipt['summary']['total_incomplete'], 1)
        self.assertEqual(receipt['pending_checks'][0]['target'], '#modal')
        run = json.loads(artifacts.sarif_json)['runs'][0]
        self.assertEqual(run['tool']['driver']['rules'][0]['properties']['source'], 'mixed')
        self.assertEqual([r['properties']['source'] for r in run['results']], ['automated', 'manual'])
        self.assertEqual(len(run['results']), 2)  # unresolved is not a violation
        for text in (artifacts.openacr_yaml, artifacts.vpat_html, artifacts.eaa_markdown):
            self.assertIn('Supplied manual findings', text)
            self.assertIn('No reviewer approval is recorded', text)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'report.pdf'; path.write_bytes(artifacts.pdf_bytes)
            text = subprocess.check_output(['pdftotext', str(path), '-'], text=True)
        self.assertIn('Supplied manual findings: 1', text)
        self.assertIn('Automated findings: 1', text)
        self.assertIn('Unresolved focus observation', text)
        self.assertIn('#modal', text)

    def test_mixed_rule_retains_only_shared_explicit_help_uri(self):
        observations = [finding('manual', help_url='https://example.invalid/help'),
                        finding('automated', help_url='https://example.invalid/help')]
        rule = json.loads(generate_sarif(AuditSummary(), observations))['runs'][0]['tool']['driver']['rules'][0]
        self.assertEqual(rule['helpUri'], 'https://example.invalid/help')
        observations[1].help_url = 'https://example.invalid/different'
        rule = json.loads(generate_sarif(AuditSummary(), observations))['runs'][0]['tool']['driver']['rules'][0]
        self.assertNotIn('helpUri', rule)

    def test_pending_hostile_fields_remain_safe_and_reproducible(self):
        summary = AuditSummary(total_incomplete=1)
        summary.pending_checks = [{'id': '<img src="private">',
            'description': '&' * 1000 + '<script>private</script>',
            'target': '<font color="red">private</font>', 'source': '<a href="x">source</a>'}]
        first = generate_pdf_report(summary, [])
        self.assertEqual(first, generate_pdf_report(summary, []))
        self.assertTrue(first.startswith(b'%PDF'))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'pending.pdf'; path.write_bytes(first)
            text = subprocess.check_output(['pdftotext', str(path), '-'], text=True)
        self.assertIn('Display shortened', text)
        self.assertIn('receipt.json', text)
