"""Synthetic provider metadata; no real tokens or external network calls."""
import contextlib
import importlib.util
import io
import json
from email.message import Message
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('vercel_access', ROOT / 'scripts/verify_vercel_access.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
SHA = 'a' * 40
PROJECT = {'name': 'access-doc', 'id': 'prj_' + 'b' * 20, 'gitRepository': {
    'type': 'github', 'org': 'Kartik24Hulmukh', 'repo': 'AccessDoc'}}

class Response(io.BytesIO):
    status = 200
    def __init__(self, body, url):
        super().__init__(body); self.url = url; self.headers = Message()
        self.headers['Content-Type'] = 'application/json'
    def geturl(self):return self.url

class VercelAccessTests(unittest.TestCase):
    def test_project_binding_and_only_trusted_output(self):
        client = Mock()
        client.get.side_effect = [PROJECT, {'deployments': [
            {'readyState': 'READY', 'meta': {'githubCommitSha': SHA},
             'url': 'PRIVATE-CANARY', 'secret': 'PRIVATE-CANARY'},
            {'state': 'ERROR', 'gitSource': {'sha': 'PRIVATE-CANARY'}},
        ]}]
        report = module.verify(client, SHA)
        self.assertTrue(report['pass']);self.assertTrue(report['exact_candidate_ready_metadata'])
        self.assertEqual(report['ready_deployment_count'], 1)
        self.assertFalse(report['token_scope_independently_verified'])
        self.assertFalse(report['functional_smoke_verified'])
        self.assertNotIn('PRIVATE-CANARY', json.dumps(report))
        self.assertEqual(len(client.get.call_args_list), 2)

    def test_wrong_project_repository_or_id_fails_closed(self):
        variants = [dict(PROJECT,name='other'),dict(PROJECT,gitRepository={'type':'github','org':'other','repo':'AccessDoc'}),dict(PROJECT,id='../private')]
        for obj in variants:
            with self.subTest(obj=obj):
                client=Mock();client.get.return_value=obj
                with self.assertRaises(module.VerificationError):module.verify(client,SHA)
                self.assertEqual(client.get.call_count,1)

    def test_get_only_fixed_api_and_bounded_body(self):
        opener=Mock();url=module.API_ORIGIN+'/v9/projects/access-doc'
        opener.open.return_value=Response(json.dumps(PROJECT).encode(),url)
        client=module.VercelClient('synthetic-private-token',module.time.monotonic()+1,opener)
        self.assertEqual(client.get('/v9/projects/access-doc'),PROJECT)
        req=opener.open.call_args.args[0]
        self.assertEqual(req.get_method(),'GET');self.assertEqual(req.full_url,url)
        opener.open.return_value=Response(b'x'*(module.MAX_RESPONSE_BYTES+1),url)
        with self.assertRaises(module.VerificationError) as error:client.get('/v9/projects/access-doc')
        self.assertEqual(error.exception.code,'RESPONSE_TOO_LARGE')

    def test_redirect_never_followed_or_token_repeated(self):
        self.assertIsNone(module.NoRedirect().redirect_request(None,None,302,None,None,'https://other.invalid'))
        opener=Mock();error=urllib.error.HTTPError('https://api.vercel.com',302,'secret',{},io.BytesIO(b'PRIVATE-CANARY'))
        opener.open.side_effect=error
        client=module.VercelClient('synthetic-private-token',module.time.monotonic()+1,opener)
        with self.assertRaises(module.VerificationError) as caught:client.get('/v9/projects/access-doc')
        self.assertEqual(caught.exception.code,'REDIRECT_REJECTED');self.assertEqual(opener.open.call_count,1)

    def test_error_and_exception_messages_never_persist(self):
        for status,expected in ((401,'TOKEN_REJECTED'),(403,'TOKEN_REJECTED'),(404,'PROJECT_NOT_FOUND'),(500,'UPSTREAM_HTTP_FAILED')):
            with self.subTest(status=status):
                opener=Mock();opener.open.side_effect=urllib.error.HTTPError('https://api.vercel.com',status,'PRIVATE-CANARY',{},io.BytesIO(b'PRIVATE-CANARY'))
                client=module.VercelClient('synthetic-private-token',module.time.monotonic()+1,opener)
                with self.assertRaises(module.VerificationError) as e:client.get('/v9/projects/access-doc')
                self.assertEqual(e.exception.code,expected);self.assertNotIn('PRIVATE',str(e.exception))

    def test_reflected_substring_uppercase_or_encoded_secret_omits_report(self):
        for report in ({'pass':True,'sha':'a'*4+'CREDENTIAL'*2+'b'*4},{'pass':True,'value':'private%2Fsecret'}):
            token='credential'*2 if 'sha' in report else 'private/secret'
            safe,ok=module.report_without_credential(report,token)
            self.assertEqual(safe,{});self.assertFalse(ok)

    def test_main_missing_key_no_network(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{'VERCEL_TOKEN':'','TARGET_COMMIT':SHA}),patch.object(module,'VercelClient') as client,contextlib.redirect_stdout(io.StringIO()):
            p=Path(td)/'receipt.json';self.assertEqual(module.main(['--output',str(p)]),1)
            self.assertEqual(json.loads(p.read_text())['error_code'],'TOKEN_MISSING');client.assert_not_called()

    def test_main_does_not_claim_access_without_guard(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{'VERCEL_TOKEN':'synthetic-token','TARGET_COMMIT':SHA}),patch.object(module,'deadline_guard',side_effect=module.VerificationError('TIMEOUT_GUARD_UNAVAILABLE')),patch.object(module,'VercelClient') as client,contextlib.redirect_stdout(io.StringIO()):
            p=Path(td)/'receipt.json';self.assertEqual(module.main(['--output',str(p)]),1)
            self.assertEqual(json.loads(p.read_text())['error_code'],'TIMEOUT_GUARD_UNAVAILABLE');client.assert_not_called()

    def test_main_omits_raw_provider_data_and_only_prints_sanitized_json(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{'VERCEL_TOKEN':'synthetic-token','TARGET_COMMIT':SHA}),patch.object(module,'deadline_guard',return_value=contextlib.nullcontext()),patch.object(module,'verify',side_effect=ValueError('PRIVATE-CANARY')),contextlib.redirect_stdout(io.StringIO()) as output:
            p=Path(td)/'receipt.json';self.assertEqual(module.main(['--output',str(p)]),1)
            self.assertNotIn('PRIVATE-CANARY',output.getvalue()+p.read_text())

    def test_invalid_deployment_list_fails(self):
        for deployments in (None,{},[None],[{}]*21):
            with self.subTest(deployments=deployments):
                client=Mock();client.get.side_effect=[PROJECT,{'deployments':deployments}]
                with self.assertRaises(module.VerificationError):module.verify(client,SHA)

    def test_workflow_protection_boundary(self):
        source=(ROOT/'.github/workflows/vercel-access-verify.yml').read_text()
        self.assertIn('environment: accessdoc-pilot-verification',source)
        self.assertIn('contents: read',source);self.assertIn("github.repository == 'Kartik24Hulmukh/AccessDoc'",source)
        self.assertNotIn('pull_request_target',source);self.assertNotIn('contents: write',source)
        self.assertIn('persist-credentials: false',source)
        self.assertEqual(source.count('${{ secrets.VERCEL_TOKEN }}'),1)
        self.assertNotIn('workflow_dispatch:\n    inputs:',source)

if __name__=='__main__':unittest.main()
