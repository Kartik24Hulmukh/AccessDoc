import subprocess,json,pathlib,os,threading,tempfile,hashlib
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
root=pathlib.Path('/data/AccessDoc');out=pathlib.Path('/data/accessdoc-turn6-evidence')
class Handler(BaseHTTPRequestHandler):
 metadata={}
 def do_GET(self):
  b=json.dumps(type(self).metadata).encode();self.send_response(200);self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
 def log_message(self,*args):pass
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);t=threading.Thread(target=lambda:server.serve_forever(poll_interval=.01));t.start()
results=[]
try:
 with tempfile.TemporaryDirectory() as directory:
  old=pathlib.Path(directory)/'old.py';old.write_bytes(subprocess.check_output(['git','show','69b2b8a:scripts/production_smoke.py'],cwd=root))
  for label,source in [('before',old),('after',root/'scripts/production_smoke.py')]:
   for shape,key,commit in [('substring','deadbeef'*4,'deadbeef'*4+'12345678'),('uppercase','abcdef12'*5,('abcdef12'*5).upper())]:
    Handler.metadata={'status':'ok','adapter_version':'test','commit':commit}
    report=out/f'variant-{shape}-{label}.json'
    env={**os.environ,'PRODUCTION_URL':f'http://127.0.0.1:{server.server_port}','TARGET_COMMIT':'a'*40,'EXPECTED_VERSION':'test','SMOKE_API_KEY':key,'SMOKE_REQUIRE_AUTH':'true','VERCEL_AUTOMATION_BYPASS_SECRET':'','SMOKE_MAX_WAIT_SECONDS':'.05','SMOKE_POLL_INTERVAL_SECONDS':'.02'}
    p=subprocess.run(['/data/accessdoc-venv/bin/python',str(source),'--output',str(report)],cwd=root,env=env,capture_output=True,text=True,timeout=5)
    (out/f'variant-{shape}-{label}.log').write_text(p.stdout+p.stderr)
    results.append({'phase':label,'case':shape,'exit':p.returncode,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'artifact_credential_present':key.casefold() in report.read_text().casefold(),'stdout_credential_present':key.casefold() in p.stdout.casefold(),'checks':len(json.loads(report.read_text())['checks'])})
finally:server.shutdown();server.server_close();t.join(2)
(out/'reflected-variants-before-after.json').write_text(json.dumps(results,indent=2));print(json.dumps(results,indent=2))
