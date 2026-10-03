"""Synthetic provider metadata; no real tokens or external network calls."""
import contextlib
import copy
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
PROJECT = {'name': 'access-doc', 'id': 'prj_' + 'b' * 20, 'accountId': 'team_' + 'e' * 20, 'gitRepository': {
    'type': 'github', 'org': 'Kartik24Hulmukh', 'repo': 'AccessDoc', 'repoId': 123}}

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
            {'id': 'dpl_' + 'c' * 20, 'projectId': PROJECT['id'],
             'ownerId': PROJECT['accountId'], 'readyState': 'READY',
             'gitSource': {'type': 'github', 'repoId': 123, 'sha': SHA},
             'meta': {'githubCommitSha': SHA},
             'url': 'PRIVATE-CANARY', 'secret': 'PRIVATE-CANARY'},
            {'state': 'ERROR', 'meta': {'githubCommitSha': 'd' * 40},
             'secret': 'PRIVATE-CANARY'},
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

# Offline schemas from official Vercel v9 project / v6 list / v13 detail docs.
SHA='a'*40; OTHER='d'*40; PID='prj_'+'b'*20; ACCOUNT='team_'+'e'*20; DID='dpl_'+'c'*20
DOC_PROJECT={'name':'access-doc','id':PID,'accountId':ACCOUNT,'link':{'type':'github','org':'Kartik24Hulmukh','repo':'AccessDoc','repoId':123}}
SOURCE={'type':'github','repoId':123,'sha':SHA}
FULL={'id':DID,'projectId':PID,'ownerId':ACCOUNT,'readyState':'READY','gitSource':SOURCE,'meta':{'githubCommitSha':SHA}}
LIST={'uid':DID,'state':'READY','meta':{'githubCommitSha':SHA}}
class OpsRegressions(unittest.TestCase):
 def client(self,listing,detail=FULL,project=DOC_PROJECT):
  c=Mock();c.get.side_effect=[copy.deepcopy(project),{'deployments':copy.deepcopy(listing)},copy.deepcopy(detail)];return c
 def test_documented_project_link_and_owned_detail(self):
  c=self.client([LIST]);r=module.verify(c,SHA);self.assertTrue(r['exact_candidate_ready_metadata']);self.assertEqual(c.get.call_count,3)
  self.assertIn('/v13/deployments/'+DID+'?',c.get.call_args.args[0]);self.assertIn('withGitRepoInfo=true',c.get.call_args.args[0]);self.assertIn('teamId='+ACCOUNT,c.get.call_args.args[0])
  for k in ('token_scope_independently_verified','functional_smoke_verified','production_configuration_verified','production_changes_performed'):self.assertIs(r[k],False)
 def test_bound_listing_avoids_detail(self):
  c=self.client([FULL]);self.assertTrue(module.verify(c,SHA)['exact_candidate_ready_metadata']);self.assertEqual(c.get.call_count,2)
 def test_documented_named_source_variant(self):
  d=copy.deepcopy(FULL);d['gitSource']={'type':'github','org':'Kartik24Hulmukh','repo':'AccessDoc','sha':SHA};self.assertTrue(module.verify(self.client([d]),SHA)['exact_candidate_ready_metadata'])
 def test_missing_identity_never_certifies_sha(self):
  p=copy.deepcopy(DOC_PROJECT);p['gitRepository']=p.pop('link')
  with self.assertRaises(module.VerificationError):module.verify(self.client([{'state':'READY','gitSource':{'sha':SHA}}],project=p),SHA)
 def test_adversarial_record_bindings(self):
  changes=[('projectId','prj_'+'f'*20),('ownerId','team_other'),('project',{'id':'prj_'+'f'*20}),('team',{'id':'team_other'}),('gitSource',{'type':'gitlab','repoId':123,'sha':SHA}),('gitSource',{'type':'github','repoId':999,'sha':SHA}),('gitSource',{'type':'github','repoId':True,'sha':SHA}),('gitSource',{'type':'github','repoId':123,'org':'attacker','repo':'unrelated','sha':SHA}),('gitRepo',{'type':'github','repoId':999,'org':'Kartik24Hulmukh','repo':'AccessDoc'}),('meta',{'githubCommitSha':SHA,'githubCommitOrg':'attacker','githubCommitRepo':'unrelated'}),('meta',{'githubCommitSha':OTHER}),('state','ERROR'),('status','ERROR'),('gitSource',[]),('meta',[])]
  for k,v in changes:
   with self.subTest(field=k,value=v):
    d=copy.deepcopy(FULL);d[k]=v
    with self.assertRaises(module.VerificationError):module.verify(self.client([d]),SHA)
 def test_detail_conflicts_fail(self):
  for k,v in [('id','dpl_'+'f'*20),('projectId','prj_'+'f'*20),('ownerId','team_other'),('readyState','ERROR'),('gitSource',{'type':'github','repoId':123,'sha':OTHER})]:
   with self.subTest(field=k):
    d=copy.deepcopy(FULL);d[k]=v
    with self.assertRaises(module.VerificationError):module.verify(self.client([LIST],d),SHA)
 def test_reduced_detail_missing_identity_does_not_certify(self):
  for key in ('projectId','ownerId','gitSource'):
   with self.subTest(key=key):
    d=copy.deepcopy(FULL);d.pop(key)
    with self.assertRaises(module.VerificationError):module.verify(self.client([LIST],d),SHA)
 def test_bad_deployment_ids_never_request_detail(self):
  for did in ('../private','https://other.invalid',DID+'?x=1',DID+'\\x'):
   with self.subTest(did=did):
    d=copy.deepcopy(LIST);d['uid']=did;c=self.client([d])
    with self.assertRaises(module.VerificationError):module.verify(c,SHA)
    self.assertEqual(c.get.call_count,2)
 def test_project_link_legacy_conflict(self):
  p=copy.deepcopy(DOC_PROJECT);p['gitRepository']={'type':'github','org':'attacker','repo':'unrelated','repoId':123}
  with self.assertRaises(module.VerificationError):module.verify(self.client([],project=p),SHA)
 def test_matching_record_without_id_holds_candidate(self):
  d=copy.deepcopy(FULL);d.pop('id');c=self.client([d])
  r=module.verify(c,SHA);self.assertTrue(r['pass']);self.assertFalse(r['exact_candidate_ready_metadata']);self.assertEqual(c.get.call_count,2)
 def test_unknown_project_account_holds_candidate(self):
  p=copy.deepcopy(DOC_PROJECT);p.pop('accountId');d=copy.deepcopy(LIST)
  c=self.client([d],project=p);r=module.verify(c,SHA)
  self.assertTrue(r['pass']);self.assertFalse(r['exact_candidate_ready_metadata']);self.assertEqual(c.get.call_count,2)
 def test_uppercase_sha_and_string_repository_id(self):
  d=copy.deepcopy(FULL);d['gitSource']['repoId']='123';d['gitSource']['sha']=SHA.upper()
  self.assertTrue(module.verify(self.client([d]),SHA)['exact_candidate_ready_metadata'])
 def test_personal_owner_is_not_a_team_query(self):
  p=copy.deepcopy(DOC_PROJECT);p['accountId']='personalAccount1234567890';d=copy.deepcopy(FULL);d['ownerId']=p['accountId']
  c=self.client([LIST],d,p);self.assertTrue(module.verify(c,SHA)['exact_candidate_ready_metadata'])
  self.assertTrue(all('teamId=' not in call.args[0] for call in c.get.call_args_list))
 def test_metadata_alone_cannot_bind_repository(self):
  d=copy.deepcopy(FULL);d.pop('gitSource')
  with self.assertRaises(module.VerificationError):module.verify(self.client([LIST],d),SHA)
 def test_deployment_id_alias_and_project_id_alias_conflicts(self):
  for field,value in [('uid','dpl_'+'f'*20),('project',{'id':'prj_'+'f'*20}),('team',{'id':'team_'+'f'*20})]:
   with self.subTest(field=field):
    d=copy.deepcopy(FULL);d[field]=value
    with self.assertRaises(module.VerificationError):module.verify(self.client([d]),SHA)
 def test_project_repo_id_conflicts_and_types_fail(self):
  for value in (True,123.0,'../123','0123',None):
   with self.subTest(value=value):
    p=copy.deepcopy(DOC_PROJECT);p['link']['repoId']=value
    with self.assertRaises(module.VerificationError):module.verify(self.client([],project=p),SHA)
  p=copy.deepcopy(DOC_PROJECT);p['gitRepository']=dict(p['link'],repoId=999)
  with self.assertRaises(module.VerificationError):module.verify(self.client([],project=p),SHA)
 def test_connected_repository_and_user_metadata_are_not_git_source(self):
  d=copy.deepcopy(FULL);d.pop('gitSource');d['gitRepo']={'type':'github','org':'Kartik24Hulmukh','repo':'AccessDoc','repoId':123}
  with self.assertRaises(module.VerificationError):module.verify(self.client([LIST],d),SHA)
 def test_sha_less_source_cannot_use_meta_sha_as_provenance(self):
  d=copy.deepcopy(FULL);d['gitSource'].pop('sha')
  with self.assertRaises(module.VerificationError):module.verify(self.client([LIST],d),SHA)
 def test_source_without_required_repository_shape_fails(self):
  d=copy.deepcopy(FULL);d['gitSource']={'type':'github','sha':SHA}
  with self.assertRaises(module.VerificationError):module.verify(self.client([d]),SHA)
 def test_documented_nullable_git_repo_does_not_replace_source(self):
  d=copy.deepcopy(FULL);d['gitRepo']=None
  self.assertTrue(module.verify(self.client([d]),SHA)['exact_candidate_ready_metadata'])
  d['gitSource']=None
  with self.assertRaises(module.VerificationError):module.verify(self.client([d]),SHA)
 def test_json_duplicate_keys_fail(self):
  class Response(io.BytesIO):
   status=200
   def __init__(self,body,url):
    from email.message import Message
    super().__init__(body);self.url=url;self.headers=Message();self.headers['Content-Type']='application/json'
   def geturl(self):return self.url
  for body in (b'{"id":"foreign","id":"expected"}',b'{"gitSource":{"sha":"foreign","sha":"expected"}}',b'{"x":NaN}'):
   with self.subTest(body=body):
    op=Mock();url=module.API_ORIGIN+'/v9/projects/access-doc';op.open.return_value=Response(body,url)
    c=module.VercelClient('synthetic-token',module.time.monotonic()+1,op)
    with self.assertRaises(module.VerificationError):c.get('/v9/projects/access-doc')

if __name__=='__main__':unittest.main()
