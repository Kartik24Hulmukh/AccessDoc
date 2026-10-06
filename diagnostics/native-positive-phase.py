#!/usr/bin/env python3
"""One outside-repo, isolated-process observation of the unchanged positive case.

No retry, policy change, altered assertion, timeout, switch interval or QoS.
In-memory forwarding observers restore originals after fixture cleanup. These
observers add overhead; this is diagnostic evidence, never acceptance evidence.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import asyncio
import collections
import contextlib
import hashlib
import itertools
import json
import os
from pathlib import Path
import platform
import subprocess
import threading
import time
import unittest
from unittest.mock import patch

EXPECTED = {
    'app/gateway_transport.py': 'e45c6c2a7ad15e94d402c4e82e32d35d5b8fc0292739861ba5b6cd5e7c40c126',
    'app/otlp_export.py': 'bb239429b02622faa5aa8b4d0ebf8bc4aecfe9982cd0707a94f9cb3d72b90da2',
    'tests/test_otlp_cleanup_ownership.py': 'f5bbebd291ecfc962cf17973a7dc468c85cc4a2dd1147edc32af94fdf710894b',
    'tests/test_native_deadline_races.py': '9c17afc5131fe26c15fe761d8e0903ff9af6b666135ee1e6dda424a5ee6e0fab',
    'tests/test_otlp_deadlines.py': '228fc572b4b977abbbf94d60018fe7ef6e9d36ae4ecc85a19225f8c115038e9a',
}
CASE = 'test_global_reserve_drains_late_final_batch_retirement'
LIMIT = 2048
WATCHDOG_SECONDS = 20


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='/data/AccessDoc')
    parser.add_argument('--output', default=str(Path(__file__).with_suffix('.json')))
    args = parser.parse_args()
    root, output = Path(args.repo).resolve(), Path(args.output).resolve()
    if output.is_relative_to(root):
        parser.error('output must be outside the repository')
    if Path(__file__).resolve().is_relative_to(root):
        parser.error('the diagnostic script itself must be outside the repository')
    output.parent.mkdir(parents=True, exist_ok=True)
    def hashes():
        return {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in EXPECTED}
    before_hashes = hashes()
    if before_hashes != EXPECTED:
        output.write_text(json.dumps({'status':'source_mismatch_no_case_executed',
                                     'expected':EXPECTED,'observed':before_hashes}, indent=2)+'\n', encoding='utf-8')
        return 2
    sys.path.insert(0, str(root))
    import aiohttp
    from app import gateway_transport as gt, otlp_export as ot
    from tests import test_otlp_cleanup_ownership as ownership
    from tests import test_otlp_deadlines as fixture_module

    origin_ns = time.monotonic_ns()
    origin = origin_ns / 1e9
    trace = collections.deque(maxlen=LIMIT)
    sequence = itertools.count()
    state = {'phase':'setup','engines':[],'exporters':[],'calls':[],
             'fixture':None,'latest_stats':{},'latest_native':{},
             'first_cancel':{},'before_positive_assert':None,'before_teardown':None}
    finished = threading.Event()
    def emit(kind, **fields):
        trace.append({'seq':next(sequence),'kind':kind,'phase':state['phase'],
                      'monotonic_ns':time.monotonic_ns(),
                      'thread':threading.current_thread().name,
                      'native_thread_id':threading.get_native_id(), **fields})
    def err(exc):
        return {'error_type':type(exc).__name__}  # never stringify URLs, headers or credentials
    def call_fields(call):
        return {'call_id':id(call),'owner_id':id(call.owner),
                'call_deadline':call.deadline,'deadline_expired':call.deadline_expired,
                'cancel_requested':call.cancel_requested}
    def current_call():
        task = asyncio.current_task()
        return getattr(task, '_native_call', None)
    def role(event):
        f = state['fixture']
        if f is not None:
            if event is f.srv.release: return 'collector_release_wait', id(f.srv)
            if event is f.srv.started: return 'collector_body_read_and_counted', id(f.srv)
        for engine in tuple(state['engines']):
            if event is getattr(engine,'ready',None): return 'engine_ready', id(engine)
        for call in tuple(state['calls']):
            if event is call.done: return 'registered_call_done', id(call)
        return None

    # Additional snapshots never call stats/_apply_pending or wait for a mutex.
    # The exact original stats/snapshot method returns are cached separately.
    def counters():
        ex = state['exporters'][-1] if state['exporters'] else None
        data = {'captured_ns':time.monotonic_ns(),
                'latest_original_stats':state['latest_stats'].get(id(ex)),
                'latest_original_native':state['latest_native'].get(id(ex._session)) if ex else None}
        if ex is not None:
            locked = ex._lock.acquire(blocking=False)
            try:
                if locked:
                    data['exporter'] = {'exported':ex.exported,'failed_batches':ex.failed_batches,
                        'failed_spans':ex.failed_spans,'rejected_spans':ex.rejected_spans,
                        'dropped':ex.dropped,'shutdown_dropped':ex.shutdown_dropped,
                        'queued':len(ex._q),'inflight':ex._inflight,'last_error':ex.last_error,
                        'handle_pending':ex._retirement.pending if ex._retirement else 0,
                        'owner_cleanup_pending':bool(ex._session and ex._session.cleanup_pending),
                        'accounting_mailbox_empty_observed':ex._pending.empty()}
                else: data['exporter'] = {'unavailable_without_waiting':True}
            finally:
                if locked: ex._lock.release()
            engine = ex._session._engine if ex._session else None
            if engine is not None:
                locked = engine.condition.acquire(blocking=False)
                try:
                    data['native'] = ({'active_calls':len(engine.calls),'inflight':engine.used,
                        'peak_inflight':engine.peak,'closed':engine.closed,
                        'loop_alive':engine.thread.is_alive()} if locked else
                        {'unavailable_without_waiting':True})
                finally:
                    if locked: engine.condition.release()
        f = state['fixture']
        if f is not None:
            locked = f.srv.guard.acquire(blocking=False)
            try:
                data['collector'] = ({'received':f.srv.received,'active':f.srv.active,
                    'peak':f.srv.peak,'release_set':f.srv.release.is_set()} if locked else
                    {'unavailable_without_waiting':True})
            finally:
                if locked: f.srv.guard.release()
        return data

    def metadata():
        events = list(trace.copy())
        events.sort(key=lambda row:(row['monotonic_ns'],row['seq']))
        seen_max = max((row['seq'] for row in events), default=-1)
        return {'diagnostic_only':True,'case':CASE,'fixed_executions':1,
            'repo':str(root),'source_hashes_before':before_hashes,
            'platform':platform.platform(),'python':sys.version,'aiohttp_version':aiohttp.__version__,
            'switch_interval_unmodified':sys.getswitchinterval(),
            'clocks':{key:vars(time.get_clock_info(key)) for key in ('monotonic','perf_counter','thread_time')},
            'trace_origin_monotonic_ns':origin_ns,'event_limit':LIMIT,'events_retained':len(events),
            'events_truncated':seen_max+1>len(events),'highest_sequence_seen':seen_max,
            'first_cancellations':state['first_cancel'],
            'before_positive_assert':state['before_positive_assert'],
            'before_teardown':state['before_teardown'],'events':events,
            'scope':'isolated forwarding observers add overhead; no runtime wait-policy/test-source/bounds changes; no hosted or OS-causality conclusion'}
    def write(data):
        output.write_text(json.dumps(data,indent=2)+'\n', encoding='utf-8')
    def watchdog():
        if not finished.wait(WATCHDOG_SECONDS):
            data=metadata();data.update(status='diagnostic_watchdog_timeout',
                watchdog_seconds=WATCHDOG_SECONDS,partial_snapshot=counters())
            write(data)
            os._exit(124)
    monitor = threading.Thread(target=watchdog,name='idle-diagnostic-watchdog',daemon=True)

    original_init = ot.OTLPExporter.__init__
    def exporter_init(self,*a,**kw):
        original_init(self,*a,**kw)
        state['exporters'].append(self)
        emit('exporter_created',exporter_id=id(self),session_id=id(self._session),
             configured_timeout=self.timeout,flush_interval=self.flush_interval)
    original_engine_init = gt._Engine.__init__
    def engine_init(self,*a,**kw):
        state['engines'].append(self);start=time.monotonic_ns();emit('engine_construct_begin',engine_id=id(self))
        try: return original_engine_init(self,*a,**kw)
        finally: emit('engine_construct_end',engine_id=id(self),wall_ns=time.monotonic_ns()-start,
                      ready=getattr(self,'ready',None).is_set() if hasattr(self,'ready') else None)
    original_run = gt._Engine._run
    def engine_run(self):
        emit('engine_thread_begin',engine_id=id(self))
        try: return original_run(self)
        finally: emit('engine_thread_end',engine_id=id(self))
    original_attach = gt.PooledSession._attach
    def attach(self,*a,**kw):
        start=time.monotonic_ns();emit('attach_begin',session_id=id(self),
            deadline=kw.get('deadline',a[0] if a else None),previous_engine_id=id(self._engine) if self._engine else None)
        try:
            engine=original_attach(self,*a,**kw)
            emit('attach_return',session_id=id(self),engine_id=id(engine),ready=engine.ready.is_set())
            return engine
        except BaseException as exc:
            emit('attach_error',session_id=id(self),**err(exc));raise
        finally: emit('attach_end',session_id=id(self),wall_ns=time.monotonic_ns()-start)
    original_acquire = gt._Engine.acquire
    def acquire(self,call):
        if len(state['calls'])<32: state['calls'].append(call)
        emit('admission_begin',engine_id=id(self),**call_fields(call))
        try: return original_acquire(self,call)
        except BaseException as exc: emit('admission_error',**call_fields(call),**err(exc));raise
        finally: emit('admission_end',registered=call.registered,retired=call.retired,
                      engine_used_observed=self.used,**call_fields(call))
    original_task_init = gt._NativeRequestTask.__init__
    def task_init(self,coro,*,call,loop):
        emit('native_task_construct_begin',**call_fields(call))
        original_task_init(self,coro,call=call,loop=loop)
        emit('native_task_construct_end',task_id=id(self),**call_fields(call))
        def observe_done(task):
            fields=call_fields(call)
            fields.update(task_id=id(task),task_cancelled=task.cancelled(),cancel_origin=task.cancel_origin)
            if not task.cancelled():
                exception=task.exception()
                fields['error_type']=type(exception).__name__ if exception is not None else None
            emit('native_task_done_observer',**fields)
        self.add_done_callback(observe_done)
    original_request = gt._Engine._request
    async def request(self,call):
        emit('native_request_coroutine_begin',**call_fields(call))
        try: return await original_request(self,call)
        except BaseException as exc: emit('native_request_coroutine_error',cancel_origin=call.task.cancel_origin,**call_fields(call),**err(exc));raise
        finally: emit('native_request_coroutine_end',cancel_origin=call.task.cancel_origin,**call_fields(call))
    original_cancel = gt._NativeRequestTask.cancel
    def cancel(self,msg=None):
        call=self._native_call;start=time.monotonic_ns()
        accepted=original_cancel(self,msg)
        row={'start_ns':start,'accepted':accepted,'origin':self.cancel_origin,**call_fields(call)}
        if accepted and str(id(call)) not in state['first_cancel']: state['first_cancel'][str(id(call))]=dict(row)
        emit('task_cancel_attempt',**row)
        return accepted
    original_finish = gt._Engine._finish
    def finish(self,call,task):
        emit('retirement_dispatch_begin',task_done=task.done(),**call_fields(call))
        try: return original_finish(self,call,task)
        finally: emit('retirement_dispatch_end',call_done=call.done.is_set(),engine_used_observed=self.used,**call_fields(call))
    original_post = gt.PooledSession.post
    def post(self,*a,**kw):
        start=time.monotonic_ns();emit('post_begin',session_id=id(self),work_deadline=kw.get('deadline'))
        try: return original_post(self,*a,**kw)
        except BaseException as exc: emit('post_error',session_id=id(self),cleanup_pending=getattr(exc,'cleanup_pending',None),**err(exc));raise
        finally: emit('post_end',session_id=id(self),wall_ns=time.monotonic_ns()-start)
    original_cutoff = ot.OTLPExporter._work_cutoff
    def cutoff(deadline):
        start=time.monotonic();value=original_cutoff(deadline)
        emit('flush_exact_cutoff',caller_deadline=deadline,work_cutoff=value,
             reserve_seconds=deadline-value,entry_remaining_seconds=deadline-start,
             caller_deadline_from_origin_ms=(deadline-origin)*1000,
             work_cutoff_from_origin_ms=(value-origin)*1000)
        return value
    original_flush = ot.OTLPExporter.flush
    def flush(self,*a,**kw):
        start=time.monotonic_ns();emit('flush_begin',exporter_id=id(self),timeout=kw.get('timeout',a[0] if a else None))
        try:
            value=original_flush(self,*a,**kw);emit('flush_return',exporter_id=id(self),result=value);return value
        finally: emit('flush_end',exporter_id=id(self),wall_ns=time.monotonic_ns()-start)
    original_send = ot.OTLPExporter._send
    def send(self,batch,deadline):
        emit('send_begin',exporter_id=id(self),batch_size=len(batch),work_deadline=deadline)
        try:
            value=original_send(self,batch,deadline);emit('send_return',exporter_id=id(self),result=value);return value
        finally: emit('send_end',exporter_id=id(self),last_error_observed=self.last_error,
                      exported_observed=self.exported,failed_spans_observed=self.failed_spans,
                      inflight_observed=self._inflight)
    original_stats = ot.OTLPExporter.stats
    def stats(self):
        value=original_stats(self);stamp=time.monotonic_ns()
        state['latest_stats'][id(self)]={'captured_ns':stamp,'value':dict(value)}
        emit('original_stats_return',exporter_id=id(self),value=dict(value));return value
    original_snapshot = gt.PooledSession.snapshot
    def snapshot(self):
        value=original_snapshot(self)
        state['latest_native'][id(self)]={'captured_ns':time.monotonic_ns(),'value':dict(value)}
        emit('original_native_snapshot_return',session_id=id(self),value=dict(value));return value
    original_wait = threading.Event.wait
    def wait(self,*a,**kw):
        label=role(self)
        if label is None: return original_wait(self,*a,**kw)
        start=time.monotonic_ns();cpu=time.thread_time_ns()
        emit('event_wait_begin',role=label[0],object_id=label[1],timeout=kw.get('timeout',a[0] if a else None))
        try:
            value=original_wait(self,*a,**kw);emit('event_wait_return',role=label[0],object_id=label[1],result=value);return value
        finally: emit('event_wait_end',role=label[0],object_id=label[1],wall_ns=time.monotonic_ns()-start,thread_cpu_ns=time.thread_time_ns()-cpu)
    original_set = threading.Event.set
    def set_event(self):
        label=role(self)
        if label is not None: emit('event_set_begin',role=label[0],object_id=label[1])
        try: return original_set(self)
        finally:
            if label is not None: emit('event_set_end',role=label[0],object_id=label[1])
    original_collector = fixture_module.Collector.do_POST
    def collector(self):
        emit('collector_parsed_request_headers',server_id=id(self.server))
        try: return original_collector(self)
        except BaseException as exc: emit('collector_handler_error',**err(exc));raise
        finally: emit('collector_handler_end',server_id=id(self.server))
    original_headers = aiohttp.ClientSession._request
    async def headers(self,*a,**kw):
        call=current_call();fields=call_fields(call) if call is not None else {}
        emit('aiohttp_headers_request_begin',**fields)
        try:
            value=await original_headers(self,*a,**kw)
            emit('aiohttp_response_headers_available',status=value.status,**fields);return value
        except BaseException as exc: emit('aiohttp_headers_error',**fields,**err(exc));raise
    original_connect = aiohttp.TCPConnector._create_connection
    async def connect(self,*a,**kw):
        call=current_call();fields=call_fields(call) if call is not None else {}
        emit('tcp_connection_begin',**fields)
        try:
            value=await original_connect(self,*a,**kw);emit('tcp_connection_return',**fields);return value
        except BaseException as exc: emit('tcp_connection_error',**fields,**err(exc));raise
    original_body = gt._Engine._read_body
    async def body(response,limit,prefix=False):
        call=current_call();fields=call_fields(call) if call is not None else {}
        emit('response_body_begin',status=response.status,limit=limit,**fields)
        try:
            value=await original_body(response,limit,prefix=prefix)
            emit('response_body_return',decoded_bytes=len(value),**fields);return value
        except BaseException as exc: emit('response_body_error',**fields,**err(exc));raise

    class DiagnosticCase(ownership.CleanupOwnershipTests):
        # Inherit the exact source method; do not copy/edit its body or bounds.
        def setUp(self):
            super().setUp();state['fixture']=self.fixture;state['phase']='test'
            emit('unchanged_case_begin')
        def assertGreater(self,a,b,msg=None):
            if msg == 'must preserve useful exports':
                receipt=counters();receipt.update(assertion_observed_a=a,assertion_observed_b=b)
                state['before_positive_assert']=receipt
                emit('before_positive_assert',observed_a=a,observed_b=b)
            return super().assertGreater(a,b,msg)
        def tearDown(self):
            state['before_teardown']=counters();emit('before_fixture_teardown')
            state['phase']='teardown';return super().tearDown()

    hooks=[(ot.OTLPExporter,'__init__',exporter_init),(gt._Engine,'__init__',engine_init),
        (gt._Engine,'_run',engine_run),(gt.PooledSession,'_attach',attach),(gt._Engine,'acquire',acquire),
        (gt._NativeRequestTask,'__init__',task_init),(gt._Engine,'_request',request),
        (gt._NativeRequestTask,'cancel',cancel),(gt._Engine,'_finish',finish),(gt.PooledSession,'post',post),
        (ot.OTLPExporter,'_work_cutoff',staticmethod(cutoff)),(ot.OTLPExporter,'flush',flush),
        (ot.OTLPExporter,'_send',send),(ot.OTLPExporter,'stats',stats),(gt.PooledSession,'snapshot',snapshot),
        (threading.Event,'wait',wait),(threading.Event,'set',set_event),
        (fixture_module.Collector,'do_POST',collector),(aiohttp.ClientSession,'_request',headers),
        (aiohttp.TCPConnector,'_create_connection',connect),(gt._Engine,'_read_body',staticmethod(body))]
    monitor.start()
    try:
        with contextlib.ExitStack() as stack:
            for owner,name,fn in hooks: stack.enter_context(patch.object(owner,name,fn))
            # Exactly one test instance and one run, including original cleanups.
            result=unittest.TextTestRunner(verbosity=2).run(DiagnosticCase(CASE))
        data=metadata();data.update(status='case_passed' if result.wasSuccessful() else 'case_failed',
            tests_run=result.testsRun,failures=[{'case':t.id(),'traceback':msg} for t,msg in result.failures],
            errors=[{'case':t.id(),'traceback':msg} for t,msg in result.errors],
            skips=[{'case':t.id(),'reason':msg} for t,msg in result.skipped],
            source_hashes_after=hashes(),watchdog_seconds=WATCHDOG_SECONDS,
            hooks_restored=True,all_original_assertions_retained=True)
        data['hashes_unchanged']=data['source_hashes_after']==before_hashes
        if not data['hashes_unchanged']:data['status']='source_changed_diagnostic_invalid'
        write(data)
        print(json.dumps({'status':data['status'],'tests_run':result.testsRun,
            'events_retained':data['events_retained'],'events_truncated':data['events_truncated'],
            'before_positive_assert':data['before_positive_assert'],'hashes_unchanged':data['hashes_unchanged']}))
        return 0 if result.wasSuccessful() and data['hashes_unchanged'] else 1
    except BaseException as exc:
        data=metadata();data.update(status='harness_error',**err(exc),source_hashes_after=hashes())
        write(data);raise
    finally:
        finished.set()

if __name__=='__main__':
    raise SystemExit(main())
