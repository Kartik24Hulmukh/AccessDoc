import sys,json,os,threading,http.client,time
from http.server import ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import app.main as main
from app.store import TTLReportStore
main.STORE=TTLReportStore()
server=main.Server(('127.0.0.1',0),main.Handler)
os.environ.update({'ALLOWED_HOSTS':'127.0.0.1:'+str(server.server_port),'ACCESSDOC_REQUIRE_AUTH':'false','ACCESSDOC_API_KEY':'','ACCESSDOC_API_KEYS':'','RATE_LIMIT_PER_MINUTE':'100000'})
runner=threading.Thread(target=lambda:server.serve_forever(poll_interval=.01));runner.start();rows=[]
def req(method,path,data=None):
 c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=15)
 try:
  c.request(method,path,data,{'Content-Type':'application/json'} if data else {});r=c.getresponse();return r.status,r.read()
 finally:c.close()
try:
 for count in (500,1000):
  source={'violations':[{'id':'manual-rule-'+str(i),'impact':'serious','description':'Observed issue '+str(i),'nodes':[]} for i in range(count)]}
  body=json.dumps({'scanner_input':json.dumps(source),'client_name':'Storage benchmark'}).encode();samples=[]
  for _ in range(3):
   t=time.monotonic();status,response=req('POST','/api/generate',body);elapsed=(time.monotonic()-t)*1000;out=json.loads(response);downloads={}
   if status==201:
    for key,prefix in (('download_url',b'%PDF'),('html_companion_url',b'<!'),('receipt_url',b'{')):
     s,data=req('GET',out[key]);downloads[key]={'status':s,'bytes':len(data),'valid_prefix':data.lstrip().startswith(prefix)}
     if key=='receipt_url':downloads[key]['finding_count']=json.loads(data)['summary']['total_violations']
   samples.append({'status':status,'post_ms':round(elapsed,3),'downloads':downloads})
  lat=sorted(s['post_ms'] for s in samples);rows.append({'findings':count,'http_input_bytes':len(body),'samples':samples,'p50_ms':lat[1],'p95_ms':lat[-1],'p99_ms':lat[-1]})
 print(json.dumps({'scope':'loopback only; 3 samples per input; status change is acceptance improvement, not speedup; identical fixture','rows':rows,'retained_store':main.STORE.stats},indent=2))
finally:
 server.shutdown();server.server_close();runner.join(2)
