"""Synthetic loopback-only native gateway review; does not write repository."""
import sys, os, json, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0, '/data/AccessDoc')
from app.gateway import ModelGateway, CANONICAL_CHAIN

ENV = {'HTTP_PROXY':'', 'HTTPS_PROXY':'', 'ALL_PROXY':'', 'http_proxy':'', 'https_proxy':'', 'all_proxy':'', 'NO_PROXY':'*', 'no_proxy':'*'}
observations = []
# A circuit-open lane exits without setting ready; launch still waits whole hedge.
gw = ModelGateway(api_key='synthetic-only', chain=CANONICAL_CHAIN[:1], budget_seconds=.03, max_retries=0)
gw.breakers[CANONICAL_CHAIN[0]].trip()
with patch.dict(os.environ, dict(ENV, GATEWAY_HEDGE_DELAY_MS='500')), patch.object(gw, '_log'):
    started = time.monotonic()
    result = gw.chat('fix contrast')
    observations.append({'case':'open_circuit_hedge_wait', 'budget_seconds':.03, 'elapsed_seconds':round(time.monotonic()-started, 4), 'fallback':result.fallback, 'transport':gw._session.snapshot()})
gw._session.close()

received = []
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        received.append((data['model'], time.monotonic()))
        if data['model'] == CANONICAL_CHAIN[0]:
            self.send_response(408)
            self.send_header('Retry-After', '2')
            self.send_header('Content-Length', '0')
            self.end_headers()
        else:
            body = json.dumps({'choices':[{'message':{'content':'synthetic ok'}}], 'usage':{'total_tokens':20}}).encode()
            self.send_response(200)
            self.send_header('Content-Length',str(len(body)))
            self.end_headers()
            self.wfile.write(body)
server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
server.daemon_threads = True
runner = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01))
runner.start()
try:
    for budget in (3.0, .2):
        received.clear()
        gw = ModelGateway(api_key='synthetic-only', chain=CANONICAL_CHAIN[:2], budget_seconds=budget, base_backoff=0, max_sleep=2, max_retries=1)
        with patch.dict(os.environ, dict(ENV, GATEWAY_HEDGE_DELAY_MS='30')), patch('app.gateway.MELIOUS_BASE_URL','http://127.0.0.1:%d' % server.server_port), patch.object(gw,'_log'):
            started = time.monotonic()
            result = gw.chat('fix contrast')
            elapsed = time.monotonic()-started
            observations.append({'case':'408_backoff_winner_cancellation', 'budget_seconds':budget, 'elapsed_seconds':round(elapsed,4), 'returned_model':result.model, 'arrivals':[(model,round(ts-started,4)) for model,ts in received], 'hedge_threads_at_return':sum(t.name=='gateway-hedge' for t in threading.enumerate()), 'transport':gw._session.snapshot()})
            time.sleep(.08)
            observations[-1]['hedge_threads_80ms_later']=sum(t.name=='gateway-hedge' for t in threading.enumerate())
        gw._session.close()
finally:
    server.shutdown(); server.server_close(); runner.join()
print(json.dumps(observations, indent=2))
