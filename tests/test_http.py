import json,os,subprocess,sys,time,unittest,urllib.request,urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class HttpTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.proc=subprocess.Popen([sys.executable,'-m','app.main'],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={**os.environ})
  for _ in range(50):
   try:
    with urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=.3) as r:
     if r.status==200:return
   except:time.sleep(.1)
  raise RuntimeError('server did not start')
 @classmethod
 def tearDownClass(cls):
  cls.proc.terminate();cls.proc.wait(timeout=5)
  if cls.proc.stdout:cls.proc.stdout.close()
  if cls.proc.stderr:cls.proc.stderr.close()
 def request(self,path,body=None,headers=None):
  data=json.dumps(body).encode() if body is not None else None
  h={'Content-Type':'application/json'} if data else {}
  h.update(headers or {})
  return urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000'+path,data=data,headers=h),timeout=10)
 def test_full_journey(self):
  payload={'client_name':'Northstar','audit_date':'2026-07-18','agency_name':'Inclusive Studio','primary_color':'#185ABD','format_hint':'axe','scanner_input':(ROOT/'fixtures/axe-sample.json').read_text(),'manual_findings':'Keyboard order requires review.','source_filename':'synthetic-axe.json'}
  with self.request('/api/v1/generate',payload) as r:
   self.assertEqual(r.status,201);self.assertEqual(r.headers['X-Frame-Options'],'DENY');data=json.load(r)
  self.assertEqual(data['finding_count'],4);self.assertEqual(data['catalog_review_required'],1)
  self.assertEqual(data['input_evidence_receipt']['source_filename'],'synthetic-axe.json');self.assertEqual(len(data['input_evidence_receipt']['submitted_text_sha256']),64)
  self.assertEqual(data['input_evidence_receipt']['mapped_findings'],3);self.assertEqual(data['input_evidence_receipt']['unmapped_findings'],1)
  with self.request(data['download_url']) as r:
   pdf=r.read();self.assertEqual(r.headers.get_content_type(),'application/pdf');self.assertTrue(pdf.startswith(b'%PDF-'))
  with self.request(data['html_companion_url']) as r:
   html=r.read();self.assertEqual(r.headers.get_content_type(),'text/html');self.assertIn(b'Input evidence receipt',html);self.assertIn(b'finding-',html)
  with self.request(data['receipt_url']) as r:
   receipt=json.load(r);self.assertEqual(receipt['pdf_sha256'],__import__('hashlib').sha256(pdf).hexdigest());self.assertIn('did not rescan',receipt['scope_statement'])
 def test_malformed(self):
  with self.assertRaises(urllib.error.HTTPError) as cm:self.request('/api/generate',{'scanner_input':'{bad','format_hint':'axe'})
  self.assertEqual(cm.exception.code,422);self.assertEqual(json.load(cm.exception)['error']['code'],'INVALID_INPUT')
 def test_static_headers(self):
  with self.request('/') as r:
   self.assertIn("frame-ancestors 'none'",r.headers['Content-Security-Policy']);self.assertTrue(r.headers['X-Request-ID']);self.assertIn(b'AccessDoc',r.read())
 def test_cross_origin_rejected(self):
  payload={'scanner_input':(ROOT/'fixtures/axe-sample.json').read_text(),'format_hint':'axe'}
  with self.assertRaises(urllib.error.HTTPError) as cm:self.request('/api/generate',payload,{'Origin':'https://evil.invalid'})
  self.assertEqual(cm.exception.code,403)
 def test_metrics_and_version(self):
  with self.request('/metrics') as r:
   text=r.read().decode();self.assertIn('accessdoc_requests_total',text);self.assertIn('accessdoc_store_items',text)
  with self.request('/version') as r:
   data=json.load(r);self.assertEqual(data['version'],'0.4.0-beta.4');self.assertIn('catalog',data)
 def test_oversized_png_dimensions_rejected(self):
  import base64,struct
  fake=b'\x89PNG\r\n\x1a\n'+struct.pack('>I',13)+b'IHDR'+struct.pack('>II',100000,100000)+b'\x08\x02\x00\x00\x00'
  payload={'scanner_input':(ROOT/'fixtures/axe-sample.json').read_text(),'format_hint':'axe','logo_data_url':'data:image/png;base64,'+base64.b64encode(fake).decode()}
  with self.assertRaises(urllib.error.HTTPError) as cm:self.request('/api/generate',payload)
  self.assertEqual(cm.exception.code,422)
 def test_cross_report_isolation(self):
  base={'audit_date':'2026-07-21','agency_name':'QA','primary_color':'#185ABD','format_hint':'axe','scanner_input':(ROOT/'fixtures/axe-sample.json').read_text()}
  with self.request('/api/generate',{**base,'client_name':'Alpha Client'}) as r:a=json.load(r)
  with self.request('/api/generate',{**base,'client_name':'Beta Client'}) as r:b=json.load(r)
  self.assertNotEqual(a['report_token'],b['report_token'])
  with self.request(a['html_companion_url']) as r:ah=r.read()
  with self.request(b['html_companion_url']) as r:bh=r.read()
  self.assertIn(b'Alpha Client',ah);self.assertNotIn(b'Beta Client',ah);self.assertIn(b'Beta Client',bh);self.assertNotIn(b'Alpha Client',bh)
 def test_content_encoding_rejected(self):
  payload={'scanner_input':(ROOT/'fixtures/axe-sample.json').read_text(),'format_hint':'axe'}
  with self.assertRaises(urllib.error.HTTPError) as cm:self.request('/api/generate',payload,{'Content-Encoding':'gzip'})
  self.assertEqual(cm.exception.code,422)
 def test_malformed_download_route_is_not_token_lookup(self):
  with self.assertRaises(urllib.error.HTTPError) as cm:self.request('/download/not-valid/../../token')
  self.assertEqual(cm.exception.code,404)
 def test_server_backlog_and_nonroot_version(self):
  from app.main import Server
  self.assertGreaterEqual(Server.request_queue_size,64)
 def test_removed_commerce_routes_are_absent(self):
  for path in ('/payment-success','/checkout','/billing/webhook'):
   with self.assertRaises(urllib.error.HTTPError) as cm:self.request(path)
   self.assertEqual(cm.exception.code,404)
if __name__=='__main__':unittest.main()
