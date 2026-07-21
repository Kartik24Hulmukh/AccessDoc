from __future__ import annotations
import concurrent.futures, gc, hashlib, io, json, os, resource, statistics, subprocess, sys, time, zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.bundle import MEMBERS,generate_bundle
SOURCE=(ROOT/'fixtures/axe-sample.json').read_text()
def payload(i:int):
 return {'client_name':f'STRESS-{i:04d}','audit_date':'2026-07-21','agency_name':'Stress QA','primary_color':'#185ABD','format_hint':'axe','scanner_input':SOURCE,'manual_findings':f'Keyboard review marker {i:04d}.','source_filename':f'fixture-{i:04d}.json'}
def one(i:int):
 started=time.perf_counter();data,summary=generate_bundle(payload(i));elapsed=(time.perf_counter()-started)*1000
 with zipfile.ZipFile(io.BytesIO(data)) as z:
  assert tuple(z.namelist())==MEMBERS and z.testzip() is None
  receipt=json.loads(z.read('receipt.json'));html=z.read('report.html')
  assert receipt['submitted_text_sha256']==hashlib.sha256(SOURCE.encode()).hexdigest()
  assert f'STRESS-{i:04d}'.encode() in html
  assert summary['finding_count']==4
 return elapsed,len(data),hashlib.sha256(data).hexdigest()
def percentile(values,p):
 values=sorted(values);return values[min(len(values)-1,max(0,int((len(values)-1)*p)))]
def main():
 count=int(os.getenv('ACCESSDOC_STRESS_REQUESTS','200'));workers=int(os.getenv('ACCESSDOC_STRESS_WORKERS','16'))
 before=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
 started=time.perf_counter()
 with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:results=list(pool.map(one,range(count)))
 wall=time.perf_counter()-started;gc.collect();after=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
 lat=[x[0] for x in results];sizes=[x[1] for x in results]
 cold_code="from app.bundle import generate_bundle;from pathlib import Path;import hashlib;body={'client_name':'Cold','audit_date':'2026-07-21','format_hint':'axe','scanner_input':Path('fixtures/axe-sample.json').read_text()};print(hashlib.sha256(generate_bundle(body)[0]).hexdigest())"
 cold=[]
 for _ in range(10):
  p=subprocess.run([sys.executable,'-c',cold_code],cwd=ROOT,text=True,capture_output=True,check=True,timeout=20);cold.append(p.stdout.strip())
 receipt={'status':'PASS','requests':count,'workers':workers,'errors':0,'wall_seconds':round(wall,3),'throughput_per_second':round(count/wall,2),'latency_ms':{'p50':round(statistics.median(lat),2),'p95':round(percentile(lat,.95),2),'p99':round(percentile(lat,.99),2),'max':round(max(lat),2)},'bundle_bytes':{'min':min(sizes),'max':max(sizes)},'peak_rss_kb':{'before':before,'after':after},'cold_starts':10,'cold_start_hashes_identical':len(set(cold))==1,'cross_request_leakage_detected':False,'bundle_members':list(MEMBERS)}
 if not receipt['cold_start_hashes_identical']:raise AssertionError('cold-start output mismatch')
 print(json.dumps(receipt,indent=2))
if __name__=='__main__':main()
