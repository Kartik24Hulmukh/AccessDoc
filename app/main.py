from __future__ import annotations
# Version: 0.7.0-beta.5
import base64,hashlib,json,mimetypes,os,re,secrets,signal,struct,sys,threading,time
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
from .models import VERSION
from .service import build_artifacts, Artifacts
from .bundle import build_bundle, validate_bundle, MEMBERS
from .limits import limits_summary
try:
    from .store import TTLReportStore
    _STORE_AVAILABLE = True
except Exception:
    _STORE_AVAILABLE = False
    class TTLReportStore:
        def __init__(self,*a,**kw):pass
        def put(self,*a,**kw):return 'disabled'
        def get(self,*a,**kw):return None
        @property
        def stats(self):return {'items':0,'bytes':0}

ROOT=Path(__file__).resolve().parent.parent
STORE=TTLReportStore(ttl_seconds=int(os.getenv('REPORT_TTL_SECONDS','1800')),max_items=int(os.getenv('REPORT_MAX_ITEMS','100')),max_bytes=int(os.getenv('REPORT_MAX_BYTES','50000000')))
MAX_BODY=2_700_000
GENERATION_CAPACITY=threading.BoundedSemaphore(int(os.getenv('MAX_CONCURRENT_REQUESTS','2')))
CONNECTION_CAPACITY=threading.BoundedSemaphore(int(os.getenv('MAX_CONNECTIONS','64')))
RATE={};RATE_LOCK=threading.Lock();METRICS={'requests_total':0,'errors_total':0,'reports_total':0,'overload_rejections_total':0,'client_disconnects_total':0};METRICS_LOCK=threading.Lock()
ACTIVE_GENERATIONS=0;ACTIVE_CONDITION=threading.Condition()
READY=True

def slug(s):
 x=re.sub(r'[^a-zA-Z0-9._-]+','-',str(s)).strip('-')[:80];return x or 'accessibility-assessment'

def allowed_hosts():return {x.strip().lower() for x in os.getenv('ALLOWED_HOSTS','127.0.0.1:8000,localhost:8000').split(',') if x.strip()}
def allowed_origins():return {x.strip().rstrip('/') for x in os.getenv('ALLOWED_ORIGINS','http://127.0.0.1:8000,http://localhost:8000').split(',') if x.strip()}
def safe_external(v,limit=160):return re.sub(r'[\x00-\x1f\x7f\x1b]','',str(v or ''))[:limit]
def metric(name,n=1):
 with METRICS_LOCK:METRICS[name]=METRICS.get(name,0)+n

def allowed(ip):
 now=time.monotonic();window=60;limit=int(os.getenv('RATE_LIMIT_PER_MINUTE','30'))
 with RATE_LOCK:
  entries=[x for x in RATE.get(ip,[]) if now-x<window]
  if len(entries)>=limit:RATE[ip]=entries;return False
  entries.append(now);RATE[ip]=entries
  if len(RATE)>10000:
   for k in list(RATE)[:1000]:
    if not RATE[k] or now-RATE[k][-1]>=window:RATE.pop(k,None)
  return True

def api_keys():
 raw=os.getenv('ACCESSDOC_API_KEYS','')
 return {k.strip() for k in raw.split(',') if k.strip()}

def api_key_ok(provided):
 keys=api_keys()
 if not keys:return True
 if not provided:return False
 return any(secrets.compare_digest(provided,k) for k in keys)

class Server(ThreadingHTTPServer):
 daemon_threads=True;allow_reuse_address=True;request_queue_size=int(os.getenv('LISTEN_BACKLOG','128'))
 def process_request(self,request,client_address):
  if not CONNECTION_CAPACITY.acquire(blocking=False):
   metric('overload_rejections_total')
   try:
    body=b'{"error":{"code":"BUSY","message":"Server is at capacity"}}'
    head=('HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json\r\nContent-Length: '+str(len(body))+'\r\nRetry-After: 1\r\nConnection: close\r\nCache-Control: no-store\r\n\r\n').encode()
    request.sendall(head+body)
   except OSError:pass
   self.shutdown_request(request);return
  try:super().process_request(request,client_address)
  except Exception:
   CONNECTION_CAPACITY.release();raise
 def process_request_thread(self,request,client_address):
  try:super().process_request_thread(request,client_address)
  finally:CONNECTION_CAPACITY.release()

def _commit_sha():
 for k in ('ACCESSDOC_COMMIT_SHA','VERCEL_GIT_COMMIT_SHA','RENDER_GIT_COMMIT','RAILWAY_GIT_COMMIT_SHA','FLY_IMAGE_REF','GIT_COMMIT_SHA','SOURCE_VERSION'):
  v=os.getenv(k)
  if v:return v
 try:
  head=(ROOT/'.git'/'HEAD').read_text().strip()
  if head.startswith('ref:'):
   ref=head.split(' ',1)[1].strip()
   return (ROOT/'.git'/ref).read_text().strip()
  return head
 except Exception:return 'unknown'

class Handler(BaseHTTPRequestHandler):
 server_version=f'AccessDoc/{VERSION}';sys_version='';protocol_version='HTTP/1.1'

 def setup(self):super().setup();self.connection.settimeout(float(os.getenv('SOCKET_TIMEOUT_SECONDS','15')))
 def log_message(self,fmt,*args):pass
 def _log(self,status,start):
  print(json.dumps({'ts':time.time(),'request_id':self.request_id,'ip':safe_external(self.client_address[0]),'method':self.command,'route':safe_external(urlparse(self.path).path),'status':status,'duration_ms':round((time.monotonic()-start)*1000,2)},separators=(',',':')),flush=True)
 def _security(self,ctype):
  self.send_header('Content-Type',ctype);self.send_header('X-Content-Type-Options','nosniff');self.send_header('X-Frame-Options','DENY');self.send_header('Referrer-Policy','no-referrer');self.send_header('Permissions-Policy','camera=(), microphone=(), geolocation=()');self.send_header('Cross-Origin-Resource-Policy','same-origin');self.send_header('Cross-Origin-Opener-Policy','same-origin');self.send_header('Cache-Control','no-store');self.send_header('Pragma','no-cache');self.send_header('X-Request-ID',self.request_id);self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
 def _send(self,status,body=b'',ctype='application/json; charset=utf-8',extra=None):
  self.send_response(status);self._security(ctype)
  for k,v in (extra or {}).items():self.send_header(k,safe_external(v,300))
  self.send_header('Content-Length',str(len(body)));self.end_headers()
  if self.command!='HEAD':self.wfile.write(body)
  self._status=status
 def _json(self,status,obj):
  if isinstance(obj,dict) and 'error' in obj:obj['error']['requestId']=self.request_id
  self._send(status,json.dumps(obj,ensure_ascii=False).encode(),'application/json; charset=utf-8')
 def _validate_host(self):
  hosts=self.headers.get_all('Host') or []
  return len(hosts)==1 and safe_external(hosts[0]).lower() in allowed_hosts()
 def _validate_origin(self):
  origin=self.headers.get('Origin');fetch=self.headers.get('Sec-Fetch-Site','')
  if origin and origin.rstrip('/') not in allowed_origins():return False
  if fetch and fetch not in ('same-origin','same-site','none'):return False
  return True
 def _read(self,limit):
  if self.headers.get('Transfer-Encoding'):raise ValueError('Transfer-Encoding is not supported')
  if self.headers.get('Content-Encoding'):raise ValueError('Content-Encoding is not supported')
  vals=self.headers.get_all('Content-Length') or []
  if len(vals)!=1:raise ValueError('A single Content-Length is required')
  try:n=int(vals[0])
  except:raise ValueError('Invalid Content-Length')
  if n<=0 or n>limit:raise ValueError('Request body exceeds limit')
  raw=self.rfile.read(n)
  if len(raw)!=n:raise ValueError('Truncated request body')
  return raw
 def _read_json(self):
  if self.headers.get_content_type()!='application/json':raise ValueError('Content-Type must be application/json')
  raw=self._read(MAX_BODY)
  try:return json.loads(raw,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('Non-finite JSON number')))
  except json.JSONDecodeError:raise ValueError('Invalid JSON request')
 def handle_one_request(self):
  self.request_id=secrets.token_hex(16);self._status=500;start=time.monotonic()
  try:
   super().handle_one_request()
  except (TimeoutError,ConnectionError,BrokenPipeError,OSError):self.close_connection=True;metric('client_disconnects_total')
  except Exception:
   self.close_connection=True;metric('errors_total');
   try:self._json(500,{'error':{'code':'INTERNAL_ERROR','message':'Unexpected server error'}})
   except:pass
  finally:
   if getattr(self,'raw_requestline',b''):
    metric('requests_total')
    try:self._log(self._status,start)
    except:pass
 def _preflight(self):
  if not self._validate_host():self._json(421,{'error':{'code':'INVALID_HOST','message':'Request host is not allowed'}});return False
  return True
 def do_GET(self):
  if not self._preflight():return
  p=urlparse(self.path);path=p.path
  if path in ('/health','/livez','/health/live'):return self._json(200,{'status':'ok','service':'accessdoc','version':os.getenv('ACCESSDOC_VERSION',VERSION),'commit':_commit_sha()})
  if path=='/version':return self._json(200,{'service':'accessdoc','version':os.getenv('ACCESSDOC_VERSION',VERSION),'catalog':'wcag-2.2-accessdoc-2026-01','commit':_commit_sha()})
  if path in ('/readyz','/health/ready'):return self._json(200 if READY else 503,{'status':'ready' if READY else 'not_ready','commit':_commit_sha()})
  if path=='/metrics':
   lines=[]
   with METRICS_LOCK:
    for k,v in METRICS.items():lines.append(f'accessdoc_{k} {v}')
   for k,v in STORE.stats.items():lines.append(f'accessdoc_store_{k} {v}')
   return self._send(200,('\n'.join(lines)+'\n').encode(),'text/plain; version=0.0.4; charset=utf-8')
  if path=='/api/sample':return self._send(200,(ROOT/'public/sample/axe-sample.json').read_bytes(),'application/json; charset=utf-8')
  if path=='/limits':return self._json(200,dict(limits_summary(),api_key_required=bool(api_keys()),rate_limit_per_minute=int(os.getenv('RATE_LIMIT_PER_MINUTE','30'))))
  match=re.fullmatch(r'/(download|download-html|download-receipt)/([A-Za-z0-9_-]{32})',path)
  if match:
   kind,token=match.groups();item=STORE.get(token)
   if not item:return self._json(404,{'error':{'code':'REPORT_EXPIRED','message':'Report not found or expired. Generate it again.'}})
   base=slug(item.filename.removesuffix('.pdf'))
   if kind=='download-html':return self._send(200,item.html,'text/html; charset=utf-8',{'Content-Disposition':f'inline; filename="{base}.html"'})
   if kind=='download-receipt':return self._send(200,item.receipt,'application/json; charset=utf-8',{'Content-Disposition':f'attachment; filename="{base}-receipt.json"'})
   return self._send(200,item.pdf,'application/pdf',{'Content-Disposition':f'attachment; filename="{slug(item.filename)}"'})
  file_path=None
  if path=='/':file_path=ROOT/'public'/'index.html'
  elif path.startswith('/static/') or path.startswith('/sample/'):
   candidate=(ROOT/'public'/path.lstrip('/')).resolve()
   if str(candidate).startswith(str((ROOT/'public').resolve())) and candidate.is_file():file_path=candidate
  if file_path and file_path.is_file():
   data=file_path.read_bytes();ctype=mimetypes.guess_type(str(file_path))[0] or 'application/octet-stream'
   if ctype.startswith('text/') or ctype in ('application/javascript','application/json'):ctype+='; charset=utf-8'
   return self._send(200,data,ctype)
  self._json(404,{'error':{'code':'NOT_FOUND','message':'Not found'}})
 def do_POST(self):
  if not self._preflight():return
  path=urlparse(self.path).path
  if path not in ('/api/generate','/api/v1/generate','/api/bundle'):return self._json(404,{'error':{'code':'NOT_FOUND','message':'Not found'}})
  if not self._validate_origin():return self._json(403,{'error':{'code':'CROSS_SITE_REQUEST','message':'Cross-site requests are not allowed'}})
  if not api_key_ok(self.headers.get('X-API-Key')):return self._json(401,{'error':{'code':'UNAUTHORIZED','message':'A valid X-API-Key header is required'}})
  if not READY:return self._json(503,{'error':{'code':'DRAINING','message':'Server is shutting down. Try again shortly.'}})
  if not allowed(self.client_address[0]):return self._json(429,{'error':{'code':'RATE_LIMITED','message':'Too many requests. Try again shortly.'}})
  if not GENERATION_CAPACITY.acquire(timeout=float(os.getenv('GENERATION_QUEUE_TIMEOUT_SECONDS','0.05'))):
   metric('overload_rejections_total');return self._send(503,b'{"error":{"code":"BUSY","message":"Report generation is at capacity"}}','application/json; charset=utf-8',{'Retry-After':'1'})
  global ACTIVE_GENERATIONS
  with ACTIVE_CONDITION:ACTIVE_GENERATIONS+=1
  try:
   body=self._read_json()
   if path=='/api/bundle':
    artifacts=build_artifacts(body);bundle=build_bundle(artifacts);metric('reports_total');return self._send(200,bundle,'application/zip',{'Content-Disposition':'attachment; filename="accessdoc-report-bundle.zip"','CDN-Cache-Control':'no-store','Vercel-CDN-Cache-Control':'no-store'})
   # /api/generate and /api/v1/generate: single-file PDF+receipt flow backed
   # by the same canonical pipeline as /api/bundle (build_artifacts), stored
   # behind short-lived tokens. Previously this branch referenced Branding/
   # AuditRequest/parse_input/generate_pdf/generate_html, none of which exist
   # in this codebase any more after the evidence-bundle refactor -- every
   # call unconditionally raised NameError, caught by the generic handler
   # below and returned as an opaque 500 GENERATION_FAILED. That made the
   # documented API_V1.md contract 100% non-functional. Fixed by routing
   # through build_artifacts(), the same tested/hardened path as /api/bundle.
   artifacts=build_artifacts(body);receipt=json.loads(artifacts.receipt_json)
   summary=receipt['summary'];filename=slug(receipt.get('client_name','Client'))+'-accessibility-evidence-report.pdf'
   if not READY:return self._json(503,{'error':{'code':'DRAINING','message':'Server is shutting down; report was not stored'}})
   token=STORE.put(artifacts.pdf_bytes,artifacts.html_bytes,artifacts.receipt_json.encode(),filename)
   metric('reports_total')
   self._json(201,{'report_token':token,'download_url':f'/download/{token}','html_companion_url':f'/download-html/{token}','receipt_url':f'/download-receipt/{token}','finding_count':summary['total_violations'],'severity_counts':{'critical':summary['critical'],'serious':summary['serious'],'moderate':summary['moderate'],'minor':summary['minor'],'unknown':summary['unknown']},'catalog_review_required':summary['unknown'],'expires_in_seconds':STORE.ttl_seconds,'input_evidence_receipt':receipt})
  except ValueError as e:self._json(422,{'error':{'code':'INVALID_INPUT','message':str(e)}})
  except (TimeoutError,ConnectionError,BrokenPipeError,OSError):
   self.close_connection=True;metric('client_disconnects_total')
  except Exception:
   metric('errors_total');self._json(500,{'error':{'code':'GENERATION_FAILED','message':'The report could not be generated. No scanner contents were logged.'}})
  finally:
   with ACTIVE_CONDITION:
    ACTIVE_GENERATIONS-=1;ACTIVE_CONDITION.notify_all()
   GENERATION_CAPACITY.release()

def validate_env(host):
 if host not in ('127.0.0.1','::1','localhost') and os.getenv('ALLOW_NETWORK_EXPOSURE','false').lower()!='true':raise SystemExit('Refusing network exposure without ALLOW_NETWORK_EXPOSURE=true')

def run(host='127.0.0.1',port=8000):
 global READY
 validate_env(host);server=Server((host,port),Handler)
 def stop(sig,frame):
  global READY;READY=False;threading.Thread(target=server.shutdown,daemon=True).start()
 signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
 print(json.dumps({'event':'startup','host':host,'port':port,'version':os.getenv('ACCESSDOC_VERSION',VERSION)}),flush=True)
 try:server.serve_forever(poll_interval=.2)
 finally:
  READY=False;deadline=time.monotonic()+float(os.getenv('SHUTDOWN_GRACE_SECONDS','15'))
  with ACTIVE_CONDITION:
   while ACTIVE_GENERATIONS and time.monotonic()<deadline:ACTIVE_CONDITION.wait(timeout=min(.2,max(0,deadline-time.monotonic())))
  server.server_close();print(json.dumps({'event':'shutdown','status':'complete'}),flush=True)
if __name__=='__main__':run(os.getenv('HOST','127.0.0.1'),int(os.getenv('PORT','8000')))
