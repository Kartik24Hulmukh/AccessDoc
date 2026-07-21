import http.client,io,json,threading,unittest,zipfile
from http.server import HTTPServer
from pathlib import Path
from api.bundle import handler
ROOT=Path(__file__).resolve().parents[1]
class VercelHandlerTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.server=HTTPServer(('127.0.0.1',0),handler);cls.port=cls.server.server_port;cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
 @classmethod
 def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.thread.join(timeout=3)
 def send(self,body=b'',headers=None,method='POST'):
  c=http.client.HTTPConnection('127.0.0.1',self.port,timeout=20);h=headers or {};c.request(method,'/api/bundle',body=body,headers=h);r=c.getresponse();data=r.read();out=(r.status,{k.lower():v for k,v in r.getheaders()},data);c.close();return out
 def valid(self):return json.dumps({'client_name':'Vercel','audit_date':'2026-07-21','format_hint':'axe','scanner_input':(ROOT/'fixtures/axe-sample.json').read_text()}).encode()
 def test_success_contract(self):
  raw=self.valid();status,h,data=self.send(raw,{'Content-Type':'application/json','Origin':f'http://127.0.0.1:{self.port}'})
  self.assertEqual(status,200);self.assertEqual(h['content-type'],'application/zip');self.assertIn('no-store',h['cache-control']);self.assertEqual(h['cdn-cache-control'],'no-store');self.assertEqual(h['vercel-cdn-cache-control'],'no-store');self.assertEqual(h['content-disposition'],'attachment; filename="accessdoc-report-bundle.zip"')
  with zipfile.ZipFile(io.BytesIO(data)) as z:self.assertEqual(z.namelist(),['report.pdf','report.html','receipt.json','manifest.json'])
 def test_wrong_method(self):self.assertEqual(self.send(method='GET')[0],405)
 def test_cross_site_rejected(self):
  raw=self.valid();status,_,body=self.send(raw,{'Content-Type':'application/json','Origin':'https://evil.invalid'});self.assertEqual(status,403);self.assertNotIn(b'Vercel',body)
 def test_malformed_and_media_type(self):
  self.assertEqual(self.send(b'{bad',{'Content-Type':'application/json'})[0],400);self.assertEqual(self.send(b'{}',{'Content-Type':'text/plain'})[0],415)
 def test_oversize_rejected_before_read(self):
  c=http.client.HTTPConnection('127.0.0.1',self.port,timeout=5);c.putrequest('POST','/api/bundle');c.putheader('Content-Type','application/json');c.putheader('Content-Length','2700001');c.endheaders();r=c.getresponse();self.assertEqual(r.status,413);r.read();c.close()
if __name__=='__main__':unittest.main()
