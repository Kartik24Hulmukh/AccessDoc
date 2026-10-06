import json,sys,time,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
from app.gateway import ModelGateway,CANONICAL_CHAIN,GatewayError
import requests
rows={}
for status in (429,402):
 samples=[]
 for _ in range(3):
  stop=threading.Event();body=json.dumps({'error':{'code':'insufficient_quota'}}).encode()
  class H(BaseHTTPRequestHandler):
   def log_message(self,*a):pass
   def do_POST(self):
    self.rfile.read(int(self.headers['Content-Length']));self.send_response(status);self.send_header('Content-Length',str(len(body)));self.end_headers()
    try:
     for byte in body:
      self.wfile.write(bytes([byte]));self.wfile.flush()
      if stop.wait(.02):break
    except OSError:pass
  s=ThreadingHTTPServer(('127.0.0.1',0),H);s.daemon_threads=True
  t=threading.Thread(target=lambda:s.serve_forever(poll_interval=.01),daemon=True);t.start()
  g=ModelGateway(api_key='local-test-only',chain=(CANONICAL_CHAIN[0],))
  try:
   with patch('app.gateway.MELIOUS_BASE_URL','http://127.0.0.1:%d'%s.server_port):
    start=time.monotonic()
    try:r=g._post(CANONICAL_CHAIN[0],[],remaining=.1);outcome='http-'+str(r[0])
    except (requests.Timeout,GatewayError) as e:outcome=type(e).__name__
    elapsed=(time.monotonic()-start)*1000
   samples.append({'elapsed_ms':round(elapsed,3),'outcome':outcome})
  finally:
   stop.set();g._session.close();s.shutdown();s.server_close();t.join(2)
 vals=sorted(x['elapsed_ms'] for x in samples)
 rows[str(status)]={'budget_ms':100,'samples':samples,'p50_ms':vals[1],'p95_ms':vals[-1],'p99_ms':vals[-1]}
print(json.dumps({'scope':'real loopback sockets; 3 samples/status; descriptive order statistics, not provider SLO','rows':rows},indent=2))
