import json,sys,tracemalloc,time
sys.path.insert(0,sys.argv[1])
from app.manual import parse_manual_findings
from app.limits import LimitExceeded
rows={}
for kind in ('csv','markdown'):
 header=['id']+['c%d'%i for i in range(999)]
 text=','.join(header)+'\n'+'x\n'*5001 if kind=='csv' else '| '+' | '.join(header)+' |\n|---|\n'+'|x|\n'*5001
 tracemalloc.start();start=time.monotonic()
 try:parse_manual_findings(text);outcome='accepted'
 except LimitExceeded:outcome='LimitExceeded'
 elapsed=time.monotonic()-start;_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
 rows[kind]={'input_bytes':len(text.encode()),'peak_traced_bytes':peak,'elapsed_ms':round(elapsed*1000,3),'outcome':outcome}
print(json.dumps({'scope':'shared parser; one sample/format; tracemalloc, not process RSS or hosted capacity','rows':rows},indent=2))
