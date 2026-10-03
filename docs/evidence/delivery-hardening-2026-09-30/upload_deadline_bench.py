import sys,os,json,threading,socket,time,http.client
from http.server import ThreadingHTTPServer
sys.path.insert(0,sys.argv[1])
import api.handler as hosted
import app.main as local
rows={}
for module,handler in ((hosted,hosted.handler),(local,local.Handler)):
 samples=[]
 for sample in range(3):
  os.environ.update({'BODY_TIMEOUT_SECONDS':'.2','SOCKET_TIMEOUT_SECONDS':'.15','ACCESSDOC_REQUIRE_AUTH':'false','ACCESSDOC_API_KEY':'','ACCESSDOC_API_KEYS':'','RATE_LIMIT_PER_MINUTE':'100000'})
  server=ThreadingHTTPServer(('127.0.0.1',0),handler);server.daemon_threads=True
  os.environ['ALLOWED_HOSTS']='127.0.0.1:'+str(server.server_port)
  runner=threading.Thread(target=lambda:server.serve_forever(poll_interval=.01));runner.start()
  pool=threading.BoundedSemaphore(2);original=module.GENERATION_CAPACITY;module.GENERATION_CAPACITY=pool
  stop=threading.Event();sockets=[];writers=[]
  try:
   for _ in range(2):
    conn=socket.create_connection(('127.0.0.1',server.server_port),timeout=.05);sockets.append(conn)
    conn.sendall(('POST /api/bundle HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nContent-Type: application/json\r\nContent-Length: 1000\r\nConnection: close\r\n\r\n'%server.server_port).encode())
    def drip(sock=conn):
     try:
      while not stop.is_set():
       sock.sendall(b' ')
       if stop.wait(.02):break
     except OSError:pass
    w=threading.Thread(target=drip);w.start();writers.append(w)
   stop.wait(.35) # fixed observation window; continuous drip, not a production sleep
   c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=1)
   t=time.monotonic()
   try:
    c.request('POST','/api/bundle',b'{}',{'Content-Type':'application/json'});r=c.getresponse();status=r.status;r.read();ms=(time.monotonic()-t)*1000
   finally:c.close()
   statuses=[]
   for conn in sockets:
    try:
     with http.client.HTTPResponse(conn) as response:response.begin();statuses.append(response.status);response.read()
    except (OSError,http.client.HTTPException):statuses.append(None)
   samples.append({'observation_ms':350,'probe_status':status,'probe_ms':round(ms,3),'slow_upload_statuses':statuses,'clients_voluntarily_stopped':stop.is_set()})
  finally:
   stop.set()
   for c in sockets:c.close()
   for w in writers:w.join(1)
   server.shutdown();server.server_close();runner.join(1);module.GENERATION_CAPACITY=original
 vals=sorted(s['probe_ms'] for s in samples)
 rows[module.__name__]={'samples':samples,'probe_p50_ms':vals[1],'probe_p95_ms':vals[-1],'probe_p99_ms':vals[-1]}
print(json.dumps({'scope':'loopback only; 3 samples/adapter; two continuously dripping clients; 200ms configured absolute budget; fixed 350ms observation','rows':rows},indent=2))
