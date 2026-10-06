from pathlib import Path
import os, sys, time, json, socket, threading
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, '/data/AccessDoc')
from app import gateway, remediate
P,F=gateway.CANONICAL_CHAIN[:2]
measurements={}

def workers():
    return [t for t in threading.enumerate() if t.name=='gateway-hedge']
def wait_clean(timeout=2):
    end=time.monotonic()+timeout
    while workers() and time.monotonic()<end: time.sleep(.01)

class Upstream:
    def __init__(self, fn):
        self.arrivals=[]; self.lock=threading.Lock(); outer=self
        class H(BaseHTTPRequestHandler):
            protocol_version='HTTP/1.1'
            def log_message(self,*a): pass
            def do_POST(self):
                req=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                with outer.lock:
                    outer.arrivals.append((req,time.monotonic()))
                    idx=len(outer.arrivals)
                try: fn(self,req,idx)
                except (OSError,ValueError): pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0), H)
        self.server.daemon_threads=True
        self.thread=threading.Thread(target=lambda:self.server.serve_forever(poll_interval=.01), daemon=True)
        self.thread.start()
        self.url='http://127.0.0.1:%d/v1'%self.server.server_port
    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)

def reply(h, text='ok', usage=None):
    obj={'choices':[{'message':{'content':text}}]}
    if usage is not None: obj['usage']=usage
    b=json.dumps(obj).encode()
    h.close_connection=True
    h.send_response(200); h.send_header('Connection','close'); h.send_header('Content-Length',str(len(b))); h.end_headers(); h.wfile.write(b); h.wfile.flush()


import asyncio
from app.gateway_budget import prompt_token_bound
from app.gateway_transport import shutdown_transport
# Equivalent stalled-resolver boundary using the new async resolver test seam.
up=Upstream(lambda h,r,i:reply(h))
futures=[]; cancelled=[]
class Resolver:
    calls=0
    async def resolve(self,host,port=0,family=socket.AF_INET):
        Resolver.calls+=1
        if Resolver.calls%2:
            future=asyncio.get_running_loop().create_future();futures.append(future)
            try:await future
            except asyncio.CancelledError:cancelled.append(True);raise
        return [{'hostname':host,'host':'127.0.0.1','port':port,'family':socket.AF_INET,'proto':0,'flags':0}]
    async def close(self):pass
gw=gateway.ModelGateway(api_key='offline-synthetic',chain=(P,F),budget_seconds=.3)
gw._session.resolver_factory=lambda loop:Resolver()
outcomes=[]
try:
    with patch.object(gateway,'MELIOUS_BASE_URL',up.url.replace('127.0.0.1','bounded.invalid')),patch.object(gateway.ModelGateway,'_log'),patch.dict(os.environ,{'GATEWAY_HEDGE_DELAY_MS':'30','GATEWAY_PROXY_URL':''}):
        for _ in range(4):
            t=time.monotonic();r=gw.chat('fix');outcomes.append({'model':r.model,'elapsed_ms':round((time.monotonic()-t)*1000,2)})
        time.sleep(.4)
        measurements['F1']={'scope':'equivalent async DNS await; synthetic resolver, not real DNS-network fault certification','chats':outcomes,'arrivals_before_release':[r['model'] for r,t in up.arrivals],'hedge_threads_after_deadlines':len(workers()),'cancelled_resolver_futures':sum(f.cancelled() for f in futures),'late_primary_arrivals':[r['model'] for r,t in up.arrivals if r['model']==P],'transport':gw._session.snapshot()}
finally:gw._session.close();up.close()
def drip(h,r,i):
    h.connection.sendall(b'HTTP/1.1 200 OK\r\nX-Drip: ')
    for _ in range(30):h.connection.sendall(b'x');time.sleep(.02)
    body=b'{"choices":[{"message":{"content":"ok"}}]}'
    h.connection.sendall(b'\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body)
up=Upstream(drip);rows=[]
try:
    for mode in ('-1','30'):
        gw=gateway.ModelGateway(api_key='offline-synthetic',chain=(P,),budget_seconds=.15)
        with patch.object(gateway,'MELIOUS_BASE_URL',up.url),patch.object(gateway.ModelGateway,'_log'),patch.dict(os.environ,{'GATEWAY_HEDGE_DELAY_MS':mode}):
            t=time.monotonic();r=gw.chat('fix');rows.append({'mode':'serial' if mode=='-1' else 'hedged','budget_ms':150,'elapsed_ms':round((time.monotonic()-t)*1000,2),'fallback':r.fallback,'threads_at_return':len(workers()),'transport':gw._session.snapshot()})
        gw._session.close()
    measurements['F2']=rows
finally:up.close()
for extended in (False,True):
    prompt='fix'; ceiling=100
    if extended:ceiling+=prompt_token_bound([{'role':'system','content':'You are an accessibility remediation engineer.'},{'role':'user','content':prompt}])
    up=Upstream(lambda h,r,i:reply(h,'' if i==1 else 'ok'))
    gw=gateway.ModelGateway(api_key='offline-synthetic',chain=(P,F),token_budget=ceiling,budget_seconds=1)
    try:
        with patch.object(gateway,'MELIOUS_BASE_URL',up.url),patch.object(gateway.ModelGateway,'_log'),patch.dict(os.environ,{'GATEWAY_HEDGE_DELAY_MS':'-1','GATEWAY_MAX_TOKENS':'100'}):r=gw.chat(prompt)
        measurements['F3_missing_usage'+('_prompt_inclusive' if extended else '')]={'token_budget':ceiling,'dispatched_max_tokens':[x['max_tokens'] for x,t in up.arrivals],'sum_completion_authorizations':sum(x['max_tokens'] for x,t in up.arrivals),'success':not r.fallback,'committed_upper_tokens':r.tokens,'token_budget_metadata':r.token_budget}
    finally:gw._session.close();up.close()
shutdown_transport()
assert not workers()
import subprocess
measurements["measured_source_commit"]=subprocess.check_output(["git","-C","/data/AccessDoc","rev-parse","HEAD"],text=True).strip()
print(json.dumps(measurements,indent=2))
Path('/data/accessdoc-turn5-native-faults-final.json').write_text(json.dumps(measurements,indent=2)+'\n')
