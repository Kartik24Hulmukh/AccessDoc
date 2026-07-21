from __future__ import annotations
import json,sys,time,urllib.request
from pathlib import Path
base=(sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8000').rstrip('/')
for _ in range(50):
 try:
  if urllib.request.urlopen(base+'/readyz',timeout=2).status==200:break
 except Exception:time.sleep(.2)
else:raise SystemExit('readiness failed')
payload={'client_name':'Smoke Client','audit_date':'2026-07-18','agency_name':'AccessDoc QA','primary_color':'#185ABD','format_hint':'axe','scanner_input':Path('fixtures/axe-sample.json').read_text(),'manual_findings':'Keyboard review required.'}
req=urllib.request.Request(base+'/api/generate',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Origin':base})
with urllib.request.urlopen(req,timeout=20) as r:data=json.load(r)
assert data['finding_count']==4 and data['catalog_review_required']==1
with urllib.request.urlopen(base+data['download_url'],timeout=10) as r:pdf=r.read()
with urllib.request.urlopen(base+data['html_companion_url'],timeout=10) as r:html=r.read()
with urllib.request.urlopen(base+data['receipt_url'],timeout=10) as r:receipt=json.load(r)
assert pdf.startswith(b'%PDF-') and len(pdf)>5000
assert b'Input evidence receipt' in html and b'finding-' in html
assert receipt['pdf_sha256']==__import__('hashlib').sha256(pdf).hexdigest() and 'did not rescan' in receipt['scope_statement']
print(json.dumps({'status':'PASS','findings':data['finding_count'],'pdf_bytes':len(pdf),'html_bytes':len(html),'receipt_fields':len(receipt),'download':data['download_url']}))

req=urllib.request.Request(base+'/api/bundle',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Origin':base})
with urllib.request.urlopen(req,timeout=20) as r:
 bundle=r.read();assert r.headers.get_content_type()=='application/zip'
import io,zipfile
with zipfile.ZipFile(io.BytesIO(bundle)) as z:assert z.namelist()==['report.pdf','report.html','receipt.json','manifest.json']
print(json.dumps({'status':'PASS','bundle_bytes':len(bundle),'bundle_members':4}))
