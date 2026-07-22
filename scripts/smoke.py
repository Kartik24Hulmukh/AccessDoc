from __future__ import annotations
import json,sys,time,urllib.request
from pathlib import Path
base=(sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8000').rstrip('/')
for _ in range(50):
 try:
  if urllib.request.urlopen(base+'/readyz',timeout=2).status==200:break
 except Exception:time.sleep(.2)
else:raise SystemExit('readiness failed')
payload={'client_name':'Smoke Client','audit_date':'2026-07-23','scanner_input':Path('fixtures/axe-sample.json').read_text()}
req=urllib.request.Request(base+'/api/bundle',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Origin':base})
with urllib.request.urlopen(req,timeout=20) as r:
 bundle=r.read();assert r.headers.get_content_type()=='application/zip'
import io,zipfile
with zipfile.ZipFile(io.BytesIO(bundle)) as z:
 members=z.namelist()
 assert set(members)=={'report.pdf','report.html','receipt.json','openacr.yaml','attestation.intoto.json','manifest.json'},f'unexpected members: {members}'
 receipt=json.loads(z.read('receipt.json'))
 assert receipt['schema_version']=='1.1'
 assert 'coverage_note' in receipt
print(json.dumps({'status':'PASS','bundle_bytes':len(bundle),'bundle_members':len(members),'members':members}))
