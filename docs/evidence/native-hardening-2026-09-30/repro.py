import os, sys, socket, ipaddress, json, time, threading, http.client
sys.dont_write_bytecode = True
sys.path.insert(0, '/data/AccessDoc')
# Audit denies external network operations even if an unexpected code path tries one.
def audit(event, args):
    if event in ('socket.connect', 'socket.bind'):
        address = args[1]
        if isinstance(address, tuple) and not ipaddress.ip_address(address[0]).is_loopback:
            raise RuntimeError('Non-loopback network denied by audit harness')
sys.addaudithook(audit)
from app import main
from api.handler import handler
from app.store import TTLReportStore
from app.service import build_artifacts
from http.server import HTTPServer
results = {}
def start(cls):
    server = (main.Server if cls is main.Handler else HTTPServer)(('127.0.0.1', 0), cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
def req(server, method, path, body=None, auth=None):
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=30)
    headers = {'Content-Type': 'application/json'}
    if auth: headers['Authorization'] = 'Bearer ' + auth
    raw = None if body is None else json.dumps(body).encode()
    conn.request(method, path, body=raw, headers=headers)
    response = conn.getresponse(); data = response.read(); status=response.status
    conn.close()
    try: data=json.loads(data)
    except (ValueError, UnicodeDecodeError): data={'length':len(data)}
    return status, data
servers=[]
try:
    server, thread=start(main.Handler); servers.append((server,thread))
    os.environ['ALLOWED_HOSTS']=f'127.0.0.1:{server.server_port}'
    os.environ['ACCESSDOC_API_KEY']='synthetic-council-only'
    body={'client_name':'SYNTHETIC NOT HUMAN', 'scanner_input':{'url':'https://synthetic.invalid', 'testEngine':{'version':'4.10.3'}, 'violations':[{'id':'color-contrast','impact':'serious','description':'Synthetic evidence only.', 'nodes':[{'target':[f'#synthetic-{i}']} for i in range(500)]}]}}
    arts=build_artifacts(body)
    results['storage']={'request_bytes':len(json.dumps(body).encode()),'artifact_bytes':{'pdf':len(arts.pdf_bytes),'html':len(arts.html_bytes),'receipt':len(arts.receipt_json.encode())},'store_before':main.STORE.stats}
    try:
        TTLReportStore().put(arts.pdf_bytes, arts.html_bytes, arts.receipt_json.encode(), 'synthetic.pdf')
        results['storage']['direct_put']='unexpected success'
    except ValueError as exc: results['storage']['direct_put']={'type':type(exc).__name__,'message':str(exc)}
    results['storage']['http_generate']=req(server,'POST','/api/generate',body,'synthetic-council-only')
    results['storage']['store_after']=main.STORE.stats
    results['storage']['http_bundle']=req(server,'POST','/api/bundle',body,'synthetic-council-only')
    # Control: real generation + store succeeds for a small artifact.
    body['scanner_input']['violations'][0]['nodes']=[{'target':['#synthetic-0']}]
    status, generated=req(server,'POST','/api/generate',body,'synthetic-council-only')
    results['download_control']={'generate_status':status}
    if status==201:
        results['download_control']['unauthenticated_downloads']={k:req(server,'GET',generated[k])[0] for k in ('download_url','html_companion_url','receipt_url')}
    results['boundary_controls'] = {
        'traversal_self_hosted': req(server, 'GET', '/static/../../app/main.py')[0],
        'invalid_scanner_self_hosted': req(server, 'POST', '/api/generate', {'scanner_input': {'violations': [{'id': {'SYNTHETIC_PRIVATE_MARKER': 'not-real-evidence'}}]}}, 'synthetic-council-only'),
        'active_generation_count_after_requests': main.ACTIVE_GENERATIONS,
    }
    with main.ACTIVE_CONDITION:
        cleanup_completed = main.ACTIVE_CONDITION.wait_for(lambda: main.ACTIVE_GENERATIONS == 0, timeout=2)
    results['boundary_controls']['cleanup_completed_within_2s'] = cleanup_completed
    results['boundary_controls']['active_generation_count_after_cleanup'] = main.ACTIVE_GENERATIONS
    # Readiness with a hard-invalid auth configuration, not optional model degradation.
    os.environ.pop('ACCESSDOC_API_KEY', None)
    os.environ['ACCESSDOC_REQUIRE_AUTH']='true'
    results['readiness']={'self_hosted_ready':req(server,'GET','/readyz'),'self_hosted_core':req(server,'POST','/api/bundle',body)}
    hosted,ht=start(handler); servers.append((hosted,ht))
    results['readiness']['hosted_ready']=req(hosted,'GET','/readyz')
    results['readiness']['hosted_core']=req(hosted,'POST','/api/bundle',body)
    # Inspect backing objects WITHOUT invoking get/stats (both would trigger lazy purge).
    store=TTLReportStore(ttl_seconds=1)
    token=store.put(b'SYNTHETIC_PDF',b'SYNTHETIC_HTML',b'SYNTHETIC_RECEIPT','synthetic.pdf')
    time.sleep(2.2)
    retained=store._items.get(token)
    results['idle_ttl']={'ttl_seconds':1,'age_seconds':round(time.monotonic()-retained.created_at,3),'retained_before_touch':retained is not None,'backing_bytes_before_touch':store._bytes,'payload_present_before_touch':retained.pdf==b'SYNTHETIC_PDF','get_after_ttl':store.get(token),'backing_bytes_after_touch':store._bytes}
finally:
    for s,t in servers: s.shutdown(); s.server_close(); t.join(3)
with open('/data/accessdoc-turn5-results.json','w') as f: json.dump(results,f,indent=2)
print(json.dumps({k: v for k,v in results.items() if k!='readiness'},indent=2))
print('READINESS',json.dumps({k: {'http_status':v[0], 'status':v[1].get('status'), 'error':v[1].get('error')} for k,v in results['readiness'].items()}))
