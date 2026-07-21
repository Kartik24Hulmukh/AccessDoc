import concurrent.futures,hashlib,io,json,subprocess,sys,tempfile,unittest,zipfile
from pathlib import Path
from app.bundle import MEMBERS,generate_bundle,validate_bundle
ROOT=Path(__file__).resolve().parents[1]
def payload(marker='Northstar'):
 return {'client_name':marker,'audit_date':'2026-07-21','agency_name':'Inclusive Studio','primary_color':'#185ABD','format_hint':'axe','scanner_input':(ROOT/'fixtures/axe-sample.json').read_text(),'manual_findings':'Keyboard order requires review.','source_filename':'../synthetic-axe.json'}
class BundleTests(unittest.TestCase):
 def test_bundle_integrity_and_receipt(self):
  body=payload();data,summary=generate_bundle(body);manifest=validate_bundle(data);self.assertLessEqual(len(data),4_000_000);self.assertEqual(summary['finding_count'],4)
  with zipfile.ZipFile(io.BytesIO(data)) as z:
   self.assertEqual(tuple(z.namelist()),MEMBERS);self.assertTrue(z.read('report.pdf').startswith(b'%PDF-'));self.assertIn(b'<style>',z.read('report.html'));self.assertNotIn(b'/static/report.css',z.read('report.html'));receipt=json.loads(z.read('receipt.json'));self.assertEqual(receipt['source_filename'],'synthetic-axe.json');self.assertEqual(receipt['submitted_text_sha256'],hashlib.sha256(body['scanner_input'].encode()).hexdigest());self.assertEqual(receipt['pdf_sha256'],hashlib.sha256(z.read('report.pdf')).hexdigest())
  self.assertEqual([x['path'] for x in manifest['files']],list(MEMBERS[:-1]))
 def test_hostile_text_is_inert(self):
  body=payload('<script>alert(1)</script>');body['manual_findings']='<img src=x onerror=alert(1)>';data,_=generate_bundle(body)
  with zipfile.ZipFile(io.BytesIO(data)) as z:
   html=z.read('report.html');self.assertNotIn(b'<script>alert',html);self.assertNotIn(b'<img src=x',html);self.assertIn(b'&lt;script&gt;',html);self.assertNotIn(b'<script',html.lower())
 def test_concurrent_isolation(self):
  def one(i):
   marker=f'CLIENT-{i:03d}';data,_=generate_bundle(payload(marker))
   with zipfile.ZipFile(io.BytesIO(data)) as z:return marker,z.read('report.html')
  with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:results=list(ex.map(one,range(32)))
  for i,(marker,html) in enumerate(results):
   self.assertIn(marker.encode(),html)
   self.assertNotIn(f'CLIENT-{(i+1)%32:03d}'.encode(),html)
 def test_request_order_has_no_effect_on_semantics(self):
  a1,_=generate_bundle(payload('ALPHA'));generate_bundle(payload('BETA'));a2,_=generate_bundle(payload('ALPHA'))
  def hashes(data):
   with zipfile.ZipFile(io.BytesIO(data)) as z:return {n:hashlib.sha256(z.read(n)).hexdigest() for n in MEMBERS}
  self.assertEqual(hashes(a1),hashes(a2))
 def test_cold_start_subprocesses(self):
  code="from app.bundle import generate_bundle;from pathlib import Path;import json,hashlib;body={'client_name':'Cold','audit_date':'2026-07-21','format_hint':'axe','scanner_input':Path('fixtures/axe-sample.json').read_text()};print(hashlib.sha256(generate_bundle(body)[0]).hexdigest())"
  hashes=[]
  for _ in range(5):
   p=subprocess.run([sys.executable,'-c',code],cwd=ROOT,text=True,capture_output=True,check=True,timeout=20);hashes.append(p.stdout.strip())
  self.assertEqual(len(set(hashes)),1)
if __name__=='__main__':unittest.main()
