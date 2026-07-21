from __future__ import annotations
import argparse,hashlib,json,zipfile
from pathlib import Path
EXPECTED=['report.pdf','report.html','receipt.json','manifest.json']
def verify(path:Path):
 data=path.read_bytes();assert len(data)<=4_000_000
 with zipfile.ZipFile(path) as z:
  assert z.namelist()==EXPECTED and z.testzip() is None
  m=json.loads(z.read('manifest.json'))
  for item in m['files']:
   b=z.read(item['path']);assert len(b)==item['bytes'];assert hashlib.sha256(b).hexdigest()==item['sha256']
  assert z.read('report.pdf').startswith(b'%PDF-')
 print(json.dumps({'status':'PASS','file':path.name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'members':EXPECTED}))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('bundle',type=Path);verify(p.parse_args().bundle)
