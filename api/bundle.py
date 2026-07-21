from __future__ import annotations
import json, os, secrets, time
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse
from app.bundle import BundleTooLarge, generate_bundle
from app.parser import ParseError
from app.service import MAX_BODY

ADAPTER_VERSION='0.4.0-beta.4'

NO_STORE={'Cache-Control':'private, no-store, max-age=0','CDN-Cache-Control':'no-store','Vercel-CDN-Cache-Control':'no-store','Pragma':'no-cache','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Permissions-Policy':'camera=(), microphone=(), geolocation=()','X-Frame-Options':'DENY'}

class RequestProblem(ValueError):
    def __init__(self,status:int,code:str,message:str):super().__init__(message);self.status=status;self.code=code;self.message=message

class handler(BaseHTTPRequestHandler):
    server_version='AccessDoc/0.4';sys_version='';protocol_version='HTTP/1.1'
    def log_message(self,fmt,*args):pass
    def _send(self,status:int,body:bytes,ctype:str,extra:dict|None=None):
        self.send_response(status)
        self.send_header('Content-Type',ctype)
        for k,v in NO_STORE.items():self.send_header(k,v)
        self.send_header('Content-Security-Policy',"default-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        self.send_header('X-Request-ID',self.request_id)
        for k,v in (extra or {}).items():self.send_header(k,str(v).replace('\r','').replace('\n','')[:300])
        self.send_header('Content-Length',str(len(body)));self.end_headers()
        if self.command!='HEAD':self.wfile.write(body)
        self.status=status
    def _problem(self,status:int,code:str,message:str):
        body=json.dumps({'type':'https://accessdoc.invalid/problems/'+code.lower(),'title':message,'status':status,'code':code,'request_id':self.request_id},separators=(',',':')).encode()
        self._send(status,body,'application/problem+json; charset=utf-8')
    def _same_origin(self)->bool:
        origin=self.headers.get('Origin');fetch=self.headers.get('Sec-Fetch-Site','')
        if fetch and fetch not in ('same-origin','same-site','none'):return False
        if not origin:return True
        allowed={x.strip().rstrip('/') for x in os.getenv('ACCESSDOC_ALLOWED_ORIGINS','').split(',') if x.strip()}
        if origin.rstrip('/') in allowed:return True
        host=(self.headers.get('X-Forwarded-Host') or self.headers.get('Host') or '').split(',')[0].strip().lower()
        parsed=urlparse(origin)
        return parsed.scheme in ('https','http') and parsed.netloc.lower()==host
    def _read(self)->bytes:
        if self.headers.get('Transfer-Encoding'):raise RequestProblem(400,'INVALID_REQUEST','Transfer-Encoding is not supported')
        if self.headers.get('Content-Encoding'):raise RequestProblem(415,'UNSUPPORTED_ENCODING','Content-Encoding is not supported')
        if self.headers.get_content_type()!='application/json':raise RequestProblem(415,'UNSUPPORTED_MEDIA_TYPE','Content-Type must be application/json')
        vals=self.headers.get_all('Content-Length') or []
        if not vals:raise RequestProblem(411,'LENGTH_REQUIRED','Content-Length is required')
        if len(vals)!=1:raise RequestProblem(400,'INVALID_REQUEST','A single Content-Length is required')
        try:n=int(vals[0])
        except ValueError:raise RequestProblem(400,'INVALID_REQUEST','Content-Length is invalid')
        if n<=0:raise RequestProblem(400,'INVALID_REQUEST','Request body is empty')
        if n>MAX_BODY:raise RequestProblem(413,'INPUT_TOO_LARGE','Request exceeds the 2.7 MB transport limit')
        raw=self.rfile.read(n)
        if len(raw)!=n:raise RequestProblem(400,'INVALID_REQUEST','Request body is truncated')
        return raw
    def do_POST(self):
        self.request_id=secrets.token_hex(16);self.status=500;start=time.monotonic()
        try:
            if not self._same_origin():raise RequestProblem(403,'CROSS_SITE_REQUEST','Cross-site requests are not allowed')
            raw=self._read()
            try:body=json.loads(raw,parse_constant=lambda x:(_ for _ in ()).throw(ValueError()))
            except Exception:raise RequestProblem(400,'INVALID_JSON','Request body must be valid JSON')
            bundle,summary=generate_bundle(body)
            self._send(200,bundle,'application/zip',{'Content-Disposition':'attachment; filename="accessdoc-report-bundle.zip"','X-AccessDoc-Finding-Count':summary['finding_count'],'X-AccessDoc-Instance-Count':summary['instance_count'],'X-AccessDoc-Unmapped-Count':summary['catalog_review_required']})
        except RequestProblem as exc:self._problem(exc.status,exc.code,exc.message)
        except BundleTooLarge as exc:self._problem(413,'REPORT_TOO_LARGE',str(exc))
        except (ParseError,ValueError) as exc:self._problem(422,'INVALID_INPUT',str(exc))
        except (BrokenPipeError,ConnectionError,OSError):pass
        except Exception:self._problem(500,'GENERATION_FAILED','The report could not be generated. No scanner contents were logged.')
        finally:
            print(json.dumps({'event':'request','route':'/api/bundle','status':self.status,'duration_ms':round((time.monotonic()-start)*1000,2)},separators=(',',':')),flush=True)
    def do_GET(self):
        self.request_id=secrets.token_hex(16);self._problem(405,'METHOD_NOT_ALLOWED','Use POST for report generation')
    do_PUT=do_GET;do_DELETE=do_GET;do_PATCH=do_GET
