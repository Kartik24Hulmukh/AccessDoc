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

# F1: first resolver of each chat stalls before a socket exists; fallback wins.
up=Upstream(lambda h,r,i:reply(h))
release=threading.Event(); count=[0]; lock=threading.Lock(); original=socket.getaddrinfo
returns=[]; outcomes=[]
def resolving(host,*a,**kw):
    assert host=='127.0.0.1', 'loopback only'
    with lock: count[0]+=1; number=count[0]
    if number%2: release.wait(3)
    return original(host,*a,**kw)
gw=gateway.ModelGateway(api_key='offline-synthetic',chain=(P,F),budget_seconds=.3)
try:
    with patch.object(gateway,'MELIOUS_BASE_URL',up.url), patch.object(gateway.ModelGateway,'_log'), patch('socket.getaddrinfo',side_effect=resolving), patch.dict(os.environ,{'GATEWAY_HEDGE_DELAY_MS':'30'}):
        for _ in range(4):
            t=time.monotonic(); r=gw.chat('fix'); returns.append(time.monotonic()); outcomes.append({'model':r.model,'elapsed_ms':round((returns[-1]-t)*1000,2)})
        time.sleep(.4)
        before=[r['model'] for r,t in up.arrivals]
        orphaned=len(workers())
        release.set(); wait_clean()
        late=[{'model':r['model'],'after_last_return_ms':round((t-returns[-1])*1000,2)} for r,t in up.arrivals if r['model']==P]
        measurements['F1']={'chats':outcomes,'arrivals_before_release':before,'hedge_threads_after_deadlines':orphaned,'late_primary_arrivals':late,'threads_after_cleanup':len(workers()),'pool_maxsize':gw._session.get_adapter(up.url)._pool_maxsize,'pool_block':gw._session.get_adapter(up.url)._pool_block}
finally:
    release.set(); wait_clean(); gw._session.close(); up.close()

# F2: socket inactivity timeouts do not bound HTTP status/header parsing.
def drip(h,r,i):
    h.connection.sendall(b'HTTP/1.1 200 OK\r\nX-Drip: ')
    for _ in range(30): h.connection.sendall(b'x'); time.sleep(.02)
    body=b'{"choices":[{"message":{"content":"ok"}}]}'
    h.connection.sendall(b'\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body)
up=Upstream(drip)
rows=[]
try:
    for mode in ('-1','30'):
        gw=gateway.ModelGateway(api_key='offline-synthetic',chain=(P,),budget_seconds=.15)
        with patch.object(gateway,'MELIOUS_BASE_URL',up.url),patch.object(gateway.ModelGateway,'_log'),patch.dict(os.environ,{'GATEWAY_HEDGE_DELAY_MS':mode}):
            t=time.monotonic(); r=gw.chat('fix'); elapsed=time.monotonic()-t
            row={'mode':'serial' if mode=='-1' else 'hedged','budget_ms':150,'elapsed_ms':round(elapsed*1000,2),'fallback':r.fallback,'threads_at_return':len(workers())}
            wait_clean(); row['threads_after_cleanup']=len(workers()); rows.append(row)
        gw._session.close()
    measurements['F2']=rows
finally: up.close()

# F3a: two empty 200s without usage each get the entire ceiling (serial mode).
up=Upstream(lambda h,r,i:reply(h, '' if i==1 else 'ok'))
gw=gateway.ModelGateway(api_key='offline-synthetic',chain=(P,F),token_budget=100,budget_seconds=1)
try:
    with patch.object(gateway,'MELIOUS_BASE_URL',up.url),patch.object(gateway.ModelGateway,'_log'),patch.dict(os.environ,{'GATEWAY_HEDGE_DELAY_MS':'-1','GATEWAY_MAX_TOKENS':'100'}):
        r=gw.chat('fix')
    measurements['F3_missing_usage']={'token_budget':100,'dispatched_max_tokens':[x['max_tokens'] for x,t in up.arrivals],'sum_completion_authorizations':sum(x['max_tokens'] for x,t in up.arrivals),'success':not r.fallback,'reported_tokens':r.tokens}
finally: gw._session.close(); up.close()

# F3b: valid provider total usage includes input; success ignores ceiling.
up=Upstream(lambda h,r,i:reply(h,'ok',{'prompt_tokens':100,'completion_tokens':1,'total_tokens':101}))
gw=gateway.ModelGateway(api_key='offline-synthetic',chain=(P,),token_budget=100,budget_seconds=1)
try:
    with patch.object(gateway,'MELIOUS_BASE_URL',up.url),patch.object(gateway.ModelGateway,'_log'),patch.dict(os.environ,{'GATEWAY_HEDGE_DELAY_MS':'30','GATEWAY_MAX_TOKENS':'100'}):
        r=gw.chat('word '*1000)
    wait_clean()
    measurements['F3_total_usage']={'token_budget':100,'max_tokens':up.arrivals[0][0]['max_tokens'],'provider_total_tokens':r.tokens,'success':not r.fallback,'model':r.model}
finally: gw._session.close(); up.close()

# Passive readiness does not use effective instance credentials/transport.
old=remediate._GATEWAY
gw=gateway.ModelGateway(api_key='offline-synthetic',transport=lambda m,msg:(200,{}, {'choices':[{'message':{'content':'ok'}}]}))
try:
    with patch.dict(os.environ,{'MELIOUS_API_KEY':''}),patch.object(gateway.ModelGateway,'_log'):
        remediate.reset_gateway(gw); health=remediate.health(); r=gw.chat('fix')
        measurements['readiness_observation']={'configured':health['configured'],'status':health['status'],'reasons':health['degraded_reasons'],'injected_transport_success':not r.fallback}
finally: remediate.reset_gateway(old); gw._session.close()
assert not workers(), 'all local injected workers must be reaped'
print(json.dumps(measurements,indent=2))
with open('/data/accessdoc-turn5-measurements.json','w') as f: json.dump(measurements,f,indent=2)
