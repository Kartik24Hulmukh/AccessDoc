"""Five-sample local injected-transport delta; not a live-provider SLO."""
import sys, types, subprocess, time, json, statistics
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import gateway
source=subprocess.check_output(['git','-C',str(Path(__file__).resolve().parents[1]),'show','8c86058611cadf0bf953b809158740798cecc70e:app/gateway.py'],text=True)
old=types.ModuleType('app.gateway_baseline');old.__package__='app';exec(compile(source,'baseline_gateway.py','exec'),old.__dict__)
results={}
for name,module in [('before',old),('after',gateway)]:
 rows={}
 for status in (429,500,503,504):
  lat=[];counts=[]
  for _ in range(5):
   calls=[]
   def transport(model,messages):
    calls.append(model)
    if model==module.CANONICAL_CHAIN[0]:return status,{},{}
    return 200,{}, {'choices':[{'message':{'content':'ok'}}]}
   gw=module.ModelGateway(transport=transport);gw._log=lambda **kw:None
   start=time.monotonic();r=gw.chat('fix contrast');lat.append(round((time.monotonic()-start)*1000,3));counts.append(len(calls));gw._session.close()
  lat.sort();rows[str(status)]={'n':5,'p50_ms':lat[2],'p95_ms':lat[-1],'p99_ms':lat[-1],'provider_calls':counts,'samples_ms':lat}
 results[name]=rows
Path('routing-delta.json').write_text(json.dumps(results,indent=2));print(json.dumps(results,indent=2))
