"""Synthetic manual-input and export semantics, not human review/approval."""
import json
import os
from pathlib import Path
import threading
import unittest
from http.server import HTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import jsonschema
import yaml

from app.bundle import build_bundle, validate_bundle
from app.eaa import generate_eaa_pack
from app.manual import parse_manual_findings
from app.models import AuditSummary, AuditViolation, SOURCE_MANUAL
from app.openacr import generate_openacr_yaml
from app.service import build_artifacts
from app.vpat import generate_vpat_html


class ManualFidelityTests(unittest.TestCase):
    def test_nonempty_prose_rejected_without_echo(self):
        for text in ('Private keyboard observation.',
                     'Private keyboard observation.\nAnother observation.'):
            with self.subTest(text=text), self.assertRaises(ValueError) as error:
                parse_manual_findings(text)
            self.assertNotIn('Private', str(error.exception))

    def test_header_only_or_unrecognized_headers_rejected(self):
        for text in ('id,description', 'severity,notes\nserious,Private observation',
                     '|id|description|\n|---|---|', '|notes|\n|---|\n|Private|'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_manual_findings(text)

    def test_empty_observations_rejected(self):
        for data in ([{}], [{'impact': 'serious'}], [{'id': ' ', 'desc': ' '}],
                     'id,description\n,', '|id|description|\n|---|---|\n| | |'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                parse_manual_findings(data)

    def test_invalid_text_values_do_not_become_invented_observations(self):
        for data in ([{'id': {} }], [{'description': []}], [{'id': True}],
                     [{'id': 'x', 'description': {'private': 'text'}}]):
            with self.subTest(data=data), self.assertRaises(ValueError):
                parse_manual_findings(data)

    def test_wrong_input_shapes_even_when_falsy_rejected(self):
        for data in ({}, False, 0, 42):
            with self.subTest(data=data), self.assertRaises(ValueError):
                parse_manual_findings(data)

    def test_empty_optional_inputs_preserved(self):
        for data in (None, '', ' \n\t ', []):
            with self.subTest(data=data):
                self.assertEqual(parse_manual_findings(data), [])

    def test_valid_list_csv_and_markdown_preserve_observation(self):
        cases = (
            [{'id': 'keyboard', 'description': 'Focus trap', 'impact': 'serious',
              'wcag_scs': ['2.1.1'], 'target': '#modal'}],
            'id,description,impact,wcag_scs,target\nkeyboard,Focus trap,serious,2.1.1,#modal',
            '|id|description|impact|wcag_scs|target|\n|---|---|---|---|---|\n'
            '|keyboard|Focus trap|serious|2.1.1|#modal|',
        )
        for data in cases:
            with self.subTest(shape=type(data).__name__):
                found = parse_manual_findings(data)
                self.assertEqual(len(found), 1)
                v = found[0]
                self.assertEqual((v.id, v.description, v.source, v.target),
                                 ('keyboard', 'Focus trap', 'manual', '#modal'))
                self.assertEqual(v.wcag_scs, ['2.1.1'])

    def test_existing_sparse_id_alias_and_duplicate_contracts_preserved(self):
        for data in ([{'id': 'x'}], 'id\nx', '|id|\n|---|\n|x|'):
            with self.subTest(data=data):
                self.assertEqual(parse_manual_findings(data)[0].id, 'x')
        v = parse_manual_findings('rule,desc,wcag,selector\nkbd,"a,b",2.1.1,#x')[0]
        self.assertEqual((v.id, v.description, v.target), ('kbd', 'a,b', '#x'))
        self.assertEqual(parse_manual_findings('id,id\nfirst,last')[0].id, 'last')

    def test_description_only_is_real_observation_not_empty_default(self):
        v = parse_manual_findings([{'description': 'Actual supplied observation'}])[0]
        self.assertEqual(v.description, 'Actual supplied observation')
        self.assertEqual(v.source, 'manual')

    def test_malformed_manual_stops_core_before_render(self):
        with patch('app.service.generate_pdf_report') as renderer:
            with self.assertRaises(ValueError):
                build_artifacts({'scanner_input': {'violations': []},
                                 'manual_findings': 'Private plain prose.'})
            renderer.assert_not_called()

    def test_both_actual_loopback_adapters_reject_and_recover(self):
        from api.handler import handler
        from app.main import Handler, Server
        for server_type, handler_type in ((HTTPServer, handler), (Server, Handler)):
            with self.subTest(adapter=handler_type.__module__):
                server = server_type(('127.0.0.1', 0), handler_type)
                runner = threading.Thread(
                    target=lambda: server.serve_forever(poll_interval=0.01))
                runner.start()
                env = {'ACCESSDOC_REQUIRE_AUTH': 'false', 'ACCESSDOC_API_KEY': '',
                       'ACCESSDOC_API_KEYS': '', 'RATE_LIMIT_PER_MINUTE': '100000',
                       'GENERATION_ENABLED': 'true',
                       'ALLOWED_HOSTS': '127.0.0.1:%d' % server.server_port}
                endpoint = 'http://127.0.0.1:%d/api/bundle' % server.server_port
                def request(data):
                    return Request(endpoint, data=json.dumps({
                        'scanner_input': {'violations': []},
                        'manual_findings': data}).encode(),
                        headers={'Content-Type': 'application/json'})
                try:
                    with patch.dict(os.environ, env), patch(
                            'app.service.generate_pdf_report') as renderer:
                        for manual in ('Private plain prose.', 'id,description\n,', [{}]):
                            with self.assertRaises(HTTPError) as error:
                                urlopen(request(manual), timeout=5)
                            with error.exception as response:
                                self.assertEqual(response.code, 422)
                                self.assertIsNotNone(response.headers.get('X-Request-ID'))
                                body = response.read()
                                json.loads(body)
                                self.assertNotIn(b'Private', body)
                                self.assertNotIn(b'Traceback', body)
                        renderer.assert_not_called()
                    with patch.dict(os.environ, env):
                        with urlopen(request('id,description\nkbd,Actual observation'),
                                     timeout=5) as response:
                            self.assertEqual(response.status, 200)
                            self.assertTrue(validate_bundle(response.read())['valid'])
                finally:
                    server.shutdown()
                    server.server_close()
                    runner.join(2)
                    self.assertFalse(runner.is_alive())


class ExportSourceFidelityTests(unittest.TestCase):
    def setUp(self):
        self.summary = AuditSummary(engine_version='4.11.0')
        self.manual = AuditViolation('keyboard-modal', 'serious', 'Focus escapes modal',
                                    '', ['2.1.1'], source=SOURCE_MANUAL)
        self.auto = AuditViolation('image-alt', 'serious', 'No alternative', '', ['1.1.1'])

    def openacr(self, violations):
        return yaml.safe_load(generate_openacr_yaml(
            self.summary, violations, 'Synthetic client', '2026-10-02'))

    def criterion_notes(self, doc, sc):
        for chapter in doc['chapters'].values():
            for criterion in chapter.get('criteria', []):
                if criterion['num'] == sc:
                    return criterion['components'][0]['adherence']['notes']
        self.fail('Missing criterion '+sc)

    def test_manual_openacr_never_recast_as_axe_rule(self):
        doc = self.openacr([self.manual])
        self.assertIn('supplied manual observations', doc['evaluation_methods_used'])
        notes = self.criterion_notes(doc, '2.1.1')
        self.assertIn('Supplied manual findings', notes)
        self.assertNotIn('axe-core rules: keyboard-modal', notes)
        self.assertNotIn('Automated scan only', doc['notes'])

    def test_manual_vpat_never_recast_as_automated_failure(self):
        text = generate_vpat_html(self.summary, [self.manual])
        self.assertIn('supplied manual observations', text)
        self.assertIn('Supplied manual findings', text)
        self.assertNotIn('Automated failures: keyboard-modal', text)
        self.assertNotIn('AUTOMATED EVIDENCE ONLY', text)

    def test_mixed_sources_on_same_criterion_remain_distinct(self):
        manual = AuditViolation('manual-alt', 'minor', 'Wrong meaning', '',
                                ['1.1.1'], source=SOURCE_MANUAL)
        doc = self.openacr([self.auto, manual])
        notes = self.criterion_notes(doc, '1.1.1')
        self.assertIn('Automated axe-core rules: image-alt', notes)
        self.assertIn('Supplied manual findings (unreviewed): manual-alt', notes)
        text = generate_vpat_html(self.summary, [self.auto, manual])
        self.assertIn('Automated axe-core rules: image-alt', text)
        self.assertIn('Supplied manual findings (unreviewed): manual-alt', text)

    def test_both_exports_explicitly_draft_unreviewed_no_approval(self):
        for findings in ([], [self.auto], [self.manual], [self.auto, self.manual]):
            with self.subTest(sources=[v.source for v in findings]):
                doc = self.openacr(findings)
                self.assertIn('DRAFT', doc['title'])
                self.assertIn('unreviewed', doc['notes'])
                self.assertIn('No reviewer approval is recorded', doc['notes'])
                text = generate_vpat_html(self.summary, findings)
                self.assertIn('DRAFT - UNREVIEWED', text)
                self.assertIn('No reviewer approval is recorded', text)

    def test_automated_only_keeps_automated_method(self):
        doc = self.openacr([self.auto])
        self.assertIn('Automated (axe-core 4.11.0)', doc['evaluation_methods_used'])
        self.assertNotIn('supplied manual', doc['evaluation_methods_used'])
        self.assertIn('Automated axe-core rules: image-alt',
                      self.criterion_notes(doc, '1.1.1'))

    def test_nonstandard_source_is_not_silently_automated(self):
        other = AuditViolation('external-check', 'serious', 'Supplied', '',
                               ['2.1.1'], source='vendor-declaration')
        notes = self.criterion_notes(self.openacr([other]), '2.1.1')
        self.assertIn('Other supplied findings', notes)
        self.assertNotIn('axe-core rules: external-check', notes)
        self.assertIn('Other supplied findings', generate_vpat_html(self.summary, [other]))

    def test_hostile_identifiers_escaped_in_html_and_safe_yaml_scalars(self):
        self.manual.id = 'kbd:<script>alert(1)</script>"\nchapters: injected'
        doc = self.openacr([self.manual])
        self.assertIn('kbd:', self.criterion_notes(doc, '2.1.1'))
        self.assertEqual(doc['product']['name'], 'Synthetic client')
        text = generate_vpat_html(self.summary, [self.manual])
        self.assertNotIn('<script>alert(1)</script>', text)
        self.assertIn('&lt;script&gt;', text)

    def test_unmapped_stays_unmapped_and_zero_findings_not_supports(self):
        self.manual.wcag_scs = ['9.9.9']
        doc = self.openacr([self.manual])
        self.assertIn('9.9.9', doc['notes'])
        self.assertTrue(doc['chapters']['success_criteria_level_a']['disabled'])
        text = generate_vpat_html(self.summary, [])
        self.assertIn('Not Evaluated', text)
        self.assertNotIn('automated pass', text)

    def test_schema_and_full_bundle_preserve_manual_source_semantics(self):
        artifacts = build_artifacts({
            'scanner_input': {'violations': [], 'testEngine': {'version': '4.11.0'}},
            'manual_findings': [{'id': 'keyboard-modal', 'description': 'Focus trap',
                                 'wcag_scs': ['2.1.1']}],
            'include_vpat': True, 'audit_date': '2026-10-02'})
        doc = yaml.safe_load(artifacts.openacr_yaml)
        schema = json.loads((Path(__file__).parents[1] / 'schemas/openacr-0.1.0.json').read_text())
        jsonschema.Draft7Validator(schema).validate(doc)
        self.assertTrue(validate_bundle(build_bundle(artifacts))['valid'])
        receipt = json.loads(artifacts.receipt_json)
        self.assertEqual(receipt['violations'][0]['source'], 'manual')
        self.assertIn('Supplied manual findings', self.criterion_notes(doc, '2.1.1'))
        self.assertIn('Supplied manual findings', artifacts.vpat_html)


class EaaSourceFidelityTests(unittest.TestCase):
    def setUp(self):
        self.summary = AuditSummary(engine_version='4.11.0')
        self.manual = AuditViolation('keyboard-modal', 'serious', 'Supplied keyboard finding',
                                    '', ['2.1.1'], source=SOURCE_MANUAL)
        self.auto = AuditViolation('image-alt', 'serious', 'Automated image observation',
                                  '', ['1.1.1'])

    def test_manual_clause_never_recast_as_automated(self):
        text = generate_eaa_pack(self.summary, [self.manual])
        self.assertIn('Supplied manual findings (unreviewed): keyboard-modal', text)
        self.assertIn('supplied manual observations', text)
        self.assertNotIn('Does Not Support (automated)', text)
        self.assertNotIn('Detected by (axe rules)', text)
        self.assertNotIn('clause assessment (automated)', text)
        self.assertNotIn('AccessDoc automated evidence.', text)

    def test_source_counts_do_not_count_manual_as_automated(self):
        for findings, auto_count, manual_count in (([self.manual], 0, 1),
                ([self.auto, self.manual], 1, 1), ([self.auto], 1, 0), ([], 0, 0)):
            with self.subTest(sources=[v.source for v in findings]):
                text = generate_eaa_pack(self.summary, findings)
                self.assertIn(f'**Total supplied findings:** {len(findings)}', text)
                self.assertIn(f'**Automated findings:** {auto_count}', text)
                self.assertIn(f'**Supplied manual findings:** {manual_count}', text)

    def test_same_identifier_keeps_both_source_buckets(self):
        manual = AuditViolation('image-alt', 'minor', 'Meaning checked manually', '',
                                ['1.1.1'], source=SOURCE_MANUAL)
        for findings in ([self.auto, manual], [manual, self.auto]):
            with self.subTest(first_source=findings[0].source):
                text = generate_eaa_pack(self.summary, findings)
                self.assertIn('Automated axe-core rules: image-alt', text)
                self.assertIn('Supplied manual findings (unreviewed): image-alt', text)

    def test_all_pack_shapes_explicitly_unreviewed_and_not_conformity(self):
        for findings in ([], [self.auto], [self.manual], [self.auto, self.manual]):
            with self.subTest(sources=[v.source for v in findings]):
                text = generate_eaa_pack(self.summary, findings)
                self.assertIn('DRAFT - UNREVIEWED', text)
                self.assertIn('No reviewer approval is recorded', text)
                self.assertIn('not a declaration of conformity', text)
                self.assertIn('source labels do not authenticate', text)
                self.assertNotIn('**Date of statement / last review:** 20', text)

    def test_other_supplied_source_is_not_automated_or_verified(self):
        other = AuditViolation('vendor-claim', 'minor', 'Supplied, unverified', '',
                               ['2.1.1'], source='vendor-declaration')
        text = generate_eaa_pack(self.summary, [other])
        self.assertIn('Other supplied findings (unreviewed): vendor-claim', text)
        self.assertIn('**Other supplied findings:** 1', text)
        self.assertIn('**Automated findings:** 0', text)
        self.assertIn('other supplied observations', text)

    def test_zero_findings_is_not_evidence_of_conformance(self):
        text = generate_eaa_pack(self.summary, [])
        self.assertIn('No automated failures detected', text)
        self.assertIn('not evaluated', text)
        self.assertIn('absence of supplied findings is not evidence of conformance', text)

    def test_source_notes_are_safe_markdown(self):
        self.manual.id = '<script>x</script>|\n# forged'
        text = generate_eaa_pack(self.summary, [self.manual])
        self.assertNotIn('<script>', text)
        self.assertNotIn('\n# forged', text)
        self.assertIn('&lt;script&gt;', text)
        self.assertIn('\\|', text)

    def test_actual_optional_bundle_eaa_agrees_with_receipt_and_acr(self):
        artifacts = build_artifacts({'scanner_input': {'violations': []},
            'manual_findings': [{'id': 'keyboard-modal', 'description': 'Focus trap',
                                 'wcag_scs': ['2.1.1']}],
            'include_eaa': True, 'include_vpat': True, 'audit_date': '2026-10-02'})
        self.assertTrue(validate_bundle(build_bundle(artifacts))['valid'])
        self.assertEqual(json.loads(artifacts.receipt_json)['violations'][0]['source'], 'manual')
        for text in (artifacts.eaa_markdown, artifacts.openacr_yaml, artifacts.vpat_html):
            self.assertIn('Supplied manual findings', text)
            self.assertIn('No reviewer approval is recorded', text)


if __name__ == '__main__':
    unittest.main()
