#!/usr/bin/env python3
"""Fixed, serial native wait diagnostics. Stdlib-only, no network/CPU load.
Run once on each frozen runner. No thresholds changed; no retry-until-green.
"""
import argparse, concurrent.futures, json, pathlib, platform, sys, threading, time
P=argparse.ArgumentParser();P.add_argument('--output',default='native-primitives.json');P.add_argument('--samples',type=int,default=3);a=P.parse_args()
if not 1<=a.samples<=10:raise ValueError('fixed samples must be within1..10')
rows=[]
for case in ['lock','rlock','event','future','sleep','poll_nonblocking_sleep']:
 for sample in range(a.samples):
  lock=threading.RLock() if case=='rlock' else threading.Lock()
  event=threading.Event();future=concurrent.futures.Future();entered=threading.Event();done=threading.Event()
  row={'case':case,'sample':sample,'requested_ms':30};lock.acquire()
  def run():
   row['worker_ident']=threading.get_ident();row['native_id']=threading.get_native_id()
   before=time.monotonic_ns();perf=time.perf_counter_ns();cpu=time.thread_time_ns();entered.set()
   try:
    if case in ('lock','rlock'):row['acquired']=lock.acquire(timeout=.03)
    elif case=='event':row['completed']=event.wait(.03)
    elif case=='future':future.result(timeout=.03)
    elif case=='sleep':time.sleep(.03)
    else:
     deadline=time.monotonic()+.03
     while not lock.acquire(blocking=False):
      remaining=deadline-time.monotonic()
      if remaining<=0:break
      time.sleep(min(.001,remaining))
   except concurrent.futures.TimeoutError:row['exception']='TimeoutError'
   finally:
    row['wall_ms']=(time.monotonic_ns()-before)/1e6;row['perf_ms']=(time.perf_counter_ns()-perf)/1e6;row['thread_cpu_ms']=(time.thread_time_ns()-cpu)/1e6;done.set()
  worker=threading.Thread(target=run,name='native-primitive-proof');worker.start()
  assert entered.wait(1)
  row['returned_while_holder_kept_lock']=done.wait(.30)
  lock.release();worker.join(1)
  if not done.is_set():raise AssertionError('primitive failed to terminate')
  rows.append(row)
result={'mode':'fixed sample primitive diagnostic, one worker at a time, idle event gates, no network','platform':platform.platform(),'python':sys.version,'implementation':platform.python_implementation(),'switch_interval':sys.getswitchinterval(),'clocks':{k:vars(time.get_clock_info(k)) for k in ['monotonic','perf_counter','time','thread_time']},'rows':rows,'scope':'wall and thread CPU do not separately identify syscall expiration, GIL reacquisition or OS scheduling; use hosted tracing for causality'}
pathlib.Path(a.output).write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'platform':result['platform'],'python':sys.version.split()[0],'rows':[{'case':r['case'],'sample':r['sample'],'wall_ms':round(r['wall_ms'],3),'cpu_ms':round(r['thread_cpu_ms'],3),'returned_while_held':r['returned_while_holder_kept_lock']} for r in rows]},indent=2))
