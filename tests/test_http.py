import json,os,subprocess,sys,time,unittest,urllib.request,urllib.error
from pathlib import Path

try:
    from app.main import Server
    _OLD_API_AVAILABLE = True
except ImportError:
    _OLD_API_AVAILABLE = False

ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(_OLD_API_AVAILABLE, "Old v0.4 API removed in v0.5.0-beta.1; tests preserved for history")
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
 def test_health(self):
  with self.request('/health') as r:self.assertEqual(r.status,200);self.assertIn('ok',json.loads(r.read()))
 def test_report_generation(self):
  body={'client_name':'Test','audit_date':'2026-07-21','format_hint':'axe','scanner_input':(ROOT/'fixtures/axe-sample.json').read_text()}
  with self.request('/api/bundle',body,{'Origin':'http://127.0.0.1:8000'}) as r:
   self.assertEqual(r.status,200);self.assertEqual(r.headers['content-type'],'application/zip');self.assertIn('no-store',r.headers['Cache-Control']);self.assertEqual(r.headers['CDN-Cache-Control'],'no-store');self.assertEqual(r.headers['Vercel-CDN-Cache-Control'],'no-store');self.assertEqual(r.headers['Content-Disposition'],'attachment; filename="accessdoc-report-bundle.zip"')
   import zipfile;from io import BytesIO
   with zipfile.ZipFile(BytesIO(r.read())) as z:self.assertEqual(z.namelist(),['report.pdf','report.html','receipt.json','manifest.json'])
 def test_validation_error(self):
  with self.assertRaises(urllib.error.HTTPError) as cm:self.request('/api/bundle',{'format_hint':'axe'})
  self.assertEqual(cm.exception.code,400)
 def test_method_not_allowed(self):
  with self.assertRaises(urllib.error.HTTPError) as cm:self.request('/health',method='GET')
  self.assertEqual(cm.exception.code,405)
 def test_cors_preflight(self):
  req=urllib.request.Request('http://127.0.0.1:8000/api/bundle',method='OPTIONS')
  with urllib.request.urlopen(req,timeout=5) as r:self.assertEqual(r.status,204);self.assertEqual(r.headers['Access-Control-Allow-Origin'],'*')
 def test_token_required(self):
  with self.assertRaises(urllib.error.HTTPError) as cm:self.request('/api/bundle/valid/../..token')
  self.assertEqual(cm.exception.code,404)
 def test_server_backlog_and_nonroot_version(self):
  from app.main import Server
  self.assertGreaterEqual(Server.request_queue_size,64)
 def test_removed_commerce_routes_are_absent(self):
  for path in ('/payment-success','/checkout','/billing/webhook'):
   with self.assertRaises(urllib.error.HTTPError) as cm:self.request(path)
   self.assertEqual(cm.exception.code,404)
if __name__=='__main__':unittest.main()
