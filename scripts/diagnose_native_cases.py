#!/usr/bin/env python3
"""Run the five unchanged hosted-failing cases once with bounded wait tracing.
Diagnostic instrumentation is not release validation. No CPU load or retries.
"""
import argparse,collections,concurrent.futures,hashlib,json,pathlib,platform,sys,threading,time,unittest
P=argparse.ArgumentParser();P.add_argument('--repo',default='.');P.add_argument('--output',default='native-cases.json');a=P.parse_args();sys.path.insert(0,a.repo)
from app import gateway_transport as gt,otlp_export as ot
from tests.test_native_deadline_races import NativeDeadlineRaces
from tests.test_otlp_deadlines import ExportDeadlineTests
records=collections.deque(maxlen=4000);total=0;case='bootstrap';origin=time.monotonic_ns()
def record(kind,before,cpu,**fields):
 global total
 total+=1;records.append(dict(kind=kind,case=case,thread=threading.current_thread().name,begin_ms=(before-origin)/1e6,wall_ms=(time.monotonic_ns()-before)/1e6,cpu_ms=(time.thread_time_ns()-cpu)/1e6,**fields))
real_take=gt._take
def take(lock,deadline):
 before=time.monotonic_ns();cpu=time.thread_time_ns();remaining=(deadline-time.monotonic())*1000
 try:return real_take(lock,deadline)
 finally:record('take',before,cpu,lock_type=type(lock).__name__,remaining_ms=remaining)
gt._take=ot._take=take
real_wait=threading.Event.wait
def wait(self,timeout=None):
 before=time.monotonic_ns();cpu=time.thread_time_ns()
 try:return real_wait(self,timeout)
 finally:record('event_wait',before,cpu,event_id=id(self),timeout_ms=None if timeout is None else timeout*1000)
threading.Event.wait=wait
real_result=concurrent.futures.Future.result
def result(self,timeout=None):
 before=time.monotonic_ns();cpu=time.thread_time_ns()
 try:return real_result(self,timeout)
 finally:record('future_result',before,cpu,future_id=id(self),timeout_ms=None if timeout is None else timeout*1000,done=self.done())
concurrent.futures.Future.result=result
class SenderProbe:
 def __init__(self,lock):self.lock=lock
 def acquire(self,*args,**kwargs):
  before=time.monotonic_ns();cpu=time.thread_time_ns()
  try:return self.lock.acquire(*args,**kwargs)
  finally:record('sender_acquire',before,cpu,timeout_ms=kwargs.get('timeout',-1)*1000)
 def release(self):return self.lock.release()
 def __enter__(self):self.acquire();return self
 def __exit__(self,*args):self.release()
real_init=ot.OTLPExporter.__init__
def init(self,*args,**kwargs):
 real_init(self,*args,**kwargs);self._sender=SenderProbe(self._sender)
ot.OTLPExporter.__init__=init
real_finish=gt._Engine._finish
def finish(self,call,task):
 before=time.monotonic_ns();cpu=time.thread_time_ns()
 record('finish_enter',before,cpu,call_id=id(call),task_done=task.done(),call_done=call.done.is_set(),deadline_delta_ms=(call.deadline-time.monotonic())*1000)
 try:return real_finish(self,call,task)
 finally:record('finish_exit',before,cpu,call_id=id(call),call_done=call.done.is_set(),registry_size=len(self.calls))
gt._Engine._finish=finish
real_cancel=gt._Engine.cancel_call
def cancel(self,call):
 before=time.monotonic_ns();cpu=time.thread_time_ns();record('cancel_call',before,cpu,call_id=id(call),call_done=call.done.is_set());return real_cancel(self,call)
gt._Engine.cancel_call=cancel
real_post=gt.PooledSession.post
def post(self,*args,**kwargs):
 before=time.monotonic_ns();cpu=time.thread_time_ns()
 try:return real_post(self,*args,**kwargs)
 finally:
  engine=self._engine;record('post_exit',before,cpu,session_id=id(self),registry_size=0 if engine is None else len(engine.calls),deadline_delta_ms=None if kwargs.get('deadline') is None else (kwargs['deadline']-time.monotonic())*1000)
gt.PooledSession.post=post
class Runner(unittest.TextTestResult):
 def startTest(self,test):
  global case
  case=test.id();super().startTest(test)
selected=[NativeDeadlineRaces('test_admission_wake_reacquire_uses_original_deadline'),NativeDeadlineRaces('test_owner_close_with_global_and_condition_contention_is_bounded'),NativeDeadlineRaces('test_session_close_and_post_attach_locks'),ExportDeadlineTests('test_flush_waits_for_background_sender_and_never_sends_concurrently'),ExportDeadlineTests('test_many_batches_share_one_flush_budget')]
out=unittest.TextTestRunner(verbosity=2,resultclass=Runner).run(unittest.TestSuite(selected));gt.shutdown_transport()
root=pathlib.Path(a.repo);obj={'mode':'single fixed execution of five unchanged cases, lightweight wait instrumentation; not acceptance validation','platform':platform.platform(),'python':sys.version,'source_sha256':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [root/'app/gateway_transport.py',root/'app/otlp_export.py',root/'tests/test_native_deadline_races.py',root/'tests/test_otlp_deadlines.py']},'tests_run':out.testsRun,'failures':[(t.id(),msg) for t,msg in out.failures],'errors':[(t.id(),msg) for t,msg in out.errors],'events_total':total,'events_retained':len(records),'events_truncated':total>len(records),'events':list(records)}
pathlib.Path(a.output).write_text(json.dumps(obj,indent=2)+'\n');print(json.dumps({'tests_run':out.testsRun,'failures':len(out.failures),'errors':len(out.errors),'events_total':total,'events_truncated':obj['events_truncated']}));sys.exit(0 if out.wasSuccessful() else 1)
