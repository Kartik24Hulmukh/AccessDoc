from __future__ import annotations
import argparse,json,statistics,time,urllib.request,urllib.error
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path

def main()->int:
 p=argparse.ArgumentParser();p.add_argument('--base',default='http://127.0.0.1:8000');p.add_argument('--workers',type=int,default=2);p.add_argument('--requests',type=int,default=200);p.add_argument('--fixture',type=Path,default=Path('fixtures/axe-sample.json'));a=p.parse_args();payload={'client_name':'Local Stress','audit_date':'2026-07-21','format_hint':'axe','scanner_input':a.fixture.read_text()}
 def one():
  started=time.perf_counter();req=urllib.request.Request(a.base+'/api/v1/generate',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Origin':a.base})
  try:
   with urllib.request.urlopen(req,timeout=30) as r:r.read();return r.status,(time.perf_counter()-started)*1000,None
  except urllib.error.HTTPError as e:e.read();return e.code,(time.perf_counter()-started)*1000,None
  except Exception as e:return 0,(time.perf_counter()-started)*1000,type(e).__name__
 with ThreadPoolExecutor(max_workers=a.workers) as ex:results=[f.result() for f in as_completed([ex.submit(one) for _ in range(a.requests)])]
 codes={str(c):sum(x[0]==c for x in results) for c in sorted(set(x[0] for x in results))};lat=[x[1] for x in results if x[0]==201];report={'workers':a.workers,'requests':a.requests,'status_codes':codes,'transport_errors':[x[2] for x in results if x[2]],'success_latency_ms':{'p50':statistics.median(lat) if lat else None,'p95':sorted(lat)[max(0,int(len(lat)*.95)-1)] if lat else None,'max':max(lat) if lat else None}};print(json.dumps(report,indent=2));return 0 if not report['transport_errors'] and all(x in ('201','503') for x in codes) else 1
if __name__=='__main__':raise SystemExit(main())
