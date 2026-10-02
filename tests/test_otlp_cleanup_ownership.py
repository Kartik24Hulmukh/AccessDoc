"""Global caller-budget cleanup and truthful retained native ownership.

All original deadline/race tests stay byte-identical. Synthetic loopback only;
controlled callback delays/gates are test fixtures, not production grace.
"""
import threading
import time
import unittest
from unittest.mock import patch
from app import gateway_transport as gt
import tests.test_otlp_deadlines as deadline_fixture


class CleanupOwnershipTests(unittest.TestCase):
    def setUp(self):
        gt.shutdown_transport()
        self.fixture = deadline_fixture.ExportDeadlineTests('test_many_batches_share_one_flush_budget')
        self.fixture.setUp()
        self.addCleanup(gt.shutdown_transport)
        self.addCleanup(self.fixture.tearDown)

    def test_global_reserve_drains_late_final_batch_retirement(self):
        self.fixture.srv.mode = 'multi'
        ex = self.fixture.exporter(timeout=.5)
        self.fixture.record(ex, 10)
        ex.max_batch = 1
        finish = gt._Engine._finish
        delayed = threading.Event()
        def delayed_finish(engine, call, task):
            if task.cancelled() or task.exception() is not None:
                delayed.set()
                engine.loop.call_later(.03, finish, engine, call, task)
            else:
                finish(engine, call, task)
        with patch.object(gt._Engine, '_finish', delayed_finish):
            before = time.monotonic()
            self.assertFalse(ex.flush(.14))
            elapsed = time.monotonic()-before
            self.assertLess(elapsed, .24)
            self.assertTrue(delayed.is_set())
            self.assertEqual(ex._session.snapshot()['active_calls'], 0)
            self.assertEqual(ex.stats().get('cleanup_pending'), 0)
        self.assertGreater(ex.stats()['queued'], 0)
        self.assertGreater(ex.stats()['exported'], 0, 'must preserve useful exports')
        self.assertLess(self.fixture.srv.received, 10)

    def test_expired_drain_remains_visible_and_next_flush_is_not_false_success(self):
        self.fixture.srv.mode = 'hold'
        ex = self.fixture.exporter(timeout=.5)
        self.fixture.record(ex)
        finish = gt._Engine._finish
        entered = threading.Event(); pending=[]
        def gated_finish(engine, call, task):
            if task.cancelled() or task.exception() is not None:
                pending.append((engine,call,task)); entered.set()
            else:
                finish(engine,call,task)
        try:
            with patch.object(gt._Engine, '_finish', gated_finish):
                before = time.monotonic()
                self.assertFalse(ex.flush(.08))
                self.assertLess(time.monotonic()-before, .16)
                self.assertTrue(entered.wait(.2))
                self.assertEqual(ex._session.snapshot()['active_calls'], 1)
                self.assertEqual(ex.stats().get('cleanup_pending'), 1)
                self.assertEqual(ex.stats()['inflight'], 0)
                self.assertFalse(ex.flush(.03), 'empty queue cannot hide pending native cleanup')
                self.assertEqual(self.fixture.srv.received, 1)
                self.assertEqual(ex.stats().get('cleanup_pending'), 1)
        finally:
            for engine,call,task in pending:
                engine.loop.call_soon_threadsafe(finish,engine,call,task)
            for engine,call,task in pending:
                self.assertTrue(call.done.wait(.5))
        self.assertEqual(ex.stats().get('cleanup_pending'), 0)
        self.assertEqual(ex._session.snapshot()['active_calls'], 0)
        self.assertTrue(ex.flush(.1), 'completed old failure is not historical loss acknowledgement')
        self.assertEqual(ex.stats()['failed_spans'], 1)

    def test_failed_drain_does_not_dequeue_or_send_more_spans(self):
        self.fixture.srv.mode = 'hold'
        ex = self.fixture.exporter(timeout=.5)
        self.fixture.record(ex)
        finish = gt._Engine._finish
        pending=[]; entered=threading.Event()
        def gated_finish(engine,call,task):
            pending.append((engine,call,task));entered.set()
        try:
            with patch.object(gt._Engine,'_finish',gated_finish):
                self.assertFalse(ex.flush(.06));self.assertTrue(entered.wait(.2))
                self.fixture.record(ex,2)
                self.assertFalse(ex.flush(.03))
                self.assertEqual(ex.stats()['queued'],2)
                self.assertEqual(ex.stats().get('cleanup_pending'),1)
                self.assertEqual(self.fixture.srv.received,1)
        finally:
            for engine,call,task in pending:
                engine.loop.call_soon_threadsafe(finish,engine,call,task)
            for engine,call,task in pending:self.assertTrue(call.done.wait(.5))
        self.fixture.srv.release.set()
        self.assertTrue(ex.flush(.5))
        self.assertEqual(ex.stats()['exported'],2)
        self.assertEqual(ex.stats()['failed_spans'],1)

    def test_native_finalizer_is_not_recancelled_by_retirement_drains(self):
        import asyncio
        ex = self.fixture.exporter(timeout=.5)
        engine = ex._session._attach()
        self.assertTrue(engine.ready.wait(1))
        self.fixture.record(ex)
        cancelling = threading.Event(); recancelled = threading.Event(); gate=[]
        async def perform(call):
            release=asyncio.Event();gate.append(release)
            try:
                await asyncio.Event().wait()
            finally:
                cancelling.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    recancelled.set()
                    raise
        try:
            with patch.object(engine,'_perform',perform):
                self.assertFalse(ex.flush(.08))
                self.assertTrue(cancelling.wait(.2))
                self.assertFalse(recancelled.is_set(), 'must not interrupt an owned native finalizer')
                self.assertEqual(ex.stats()['cleanup_pending'],1)
                self.assertEqual(engine.snapshot()['inflight'],1)
                self.assertFalse(ex.flush(.03))
                self.assertFalse(recancelled.is_set())
        finally:
            if gate:engine.loop.call_soon_threadsafe(gate[0].set)
            if ex._retirement is not None:ex._retirement.drain(time.monotonic()+.5)
        self.assertEqual(ex.stats()['cleanup_pending'],0)

    def test_group_drain_and_shutdown_do_not_repeat_native_cancellation(self):
        import asyncio
        ex = self.fixture.exporter(timeout=1)
        engine = ex._session._attach()
        self.assertTrue(engine.ready.wait(1))
        group = ex._retirement
        entered=threading.Event();cancelling=threading.Event();recancelled=threading.Event();gate=[]
        async def perform(call):
            release=asyncio.Event();gate.append(release);entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelling.set()
                try:await release.wait()
                except asyncio.CancelledError:
                    recancelled.set();raise
        call=gt._Call(ex._session,time.monotonic()+1,None,{})
        stopping=threading.Event();close_all=engine._close_all
        async def observed_close_all():
            stopping.set();await close_all()
        try:
            with patch.object(engine,'_perform',perform), patch.object(engine,'_close_all',observed_close_all):
                engine.acquire(call);group.add(engine,call);engine.submit(call)
                self.assertTrue(entered.wait(.2));engine.cancel_call(call)
                self.assertTrue(cancelling.wait(.2))
                self.assertFalse(group.drain(time.monotonic()+.02))
                self.assertFalse(ex.shutdown(.03))
                self.assertTrue(stopping.wait(.2))
                self.assertFalse(recancelled.wait(.05))
                self.assertEqual(group.pending,1)
                self.assertEqual(engine.snapshot()['inflight'],1)
        finally:
            if gate and not engine.loop.is_closed():engine.loop.call_soon_threadsafe(gate[0].set)
            engine.thread.join(.5)
        self.assertFalse(engine.thread.is_alive())
        self.assertTrue(call.done.is_set())
        self.assertEqual(group.pending,0)

    def test_call_groups_are_owner_scoped_and_timeout_reports_pending(self):
        import requests
        session = gt.PooledSession(1024);other = gt.PooledSession(1024)
        self.addCleanup(session.close);self.addCleanup(other.close)
        foreign = other.call_group()
        with self.assertRaises(ValueError):
            session.post(self.fixture.endpoint,headers={},json={},timeout=(1,1),
                         deadline=time.monotonic()+.03,call_group=foreign)
        self.assertIsNone(session._engine)
        group=session.call_group();pending=[];entered=threading.Event();finish=gt._Engine._finish
        self.fixture.srv.mode='hold'
        def gate(engine,call,task):pending.append((engine,call,task));entered.set()
        try:
            with patch.object(gt._Engine,'_finish',gate):
                before=time.monotonic()
                with self.assertRaises(requests.Timeout) as caught:
                    session.post(self.fixture.endpoint,headers={},json={},timeout=(1,1),
                                 deadline=time.monotonic()+.04,call_group=group)
                self.assertLess(time.monotonic()-before,.12)
                self.assertTrue(entered.wait(.2))
                self.assertTrue(caught.exception.cleanup_pending)
                self.assertEqual(group.pending,1)
                self.assertFalse(group.drain(time.monotonic()+.03))
                self.assertEqual(session.snapshot()['inflight'],1)
        finally:
            for engine,call,task in pending:engine.loop.call_soon_threadsafe(finish,engine,call,task)
            for engine,call,task in pending:self.assertTrue(call.done.wait(.5))
        self.assertTrue(group.drain(time.monotonic()))
        self.assertEqual(group.pending,0)

    def test_cleanup_pending_includes_owned_pool_close_after_calls_retire(self):
        import asyncio
        entered=threading.Event();gate=[]
        class Resolver:
            async def resolve(self,host,port=0,family=0):
                return [{'hostname':host,'host':'127.0.0.1','port':port,'family':2,'proto':0,'flags':0}]
            async def close(self):
                release=asyncio.Event();gate.append(release);entered.set();await release.wait()
        ex = self.fixture.exporter(endpoint='http://synthetic.invalid:%d/v1/traces' % self.fixture.srv.server_port)
        ex._session.resolver_factory=lambda loop:Resolver()
        self.fixture.record(ex)
        self.assertTrue(ex.flush(.5))
        try:
            self.assertFalse(ex.shutdown(.03))
            self.assertTrue(entered.wait(.2))
            self.assertEqual(ex._retirement.pending,0)
            self.assertEqual(ex.stats()['cleanup_pending'],1)
        finally:
            if gate:ex._session._engine.loop.call_soon_threadsafe(gate[0].set)
            ex._session._engine.thread.join(.5)
        self.assertFalse(ex._session._engine.thread.is_alive())
        self.assertEqual(ex.stats()['cleanup_pending'],0)

    def test_deadline_timer_cannot_recancel_an_earlier_native_finalizer(self):
        import asyncio
        session=gt.PooledSession(1024);self.addCleanup(session.close)
        engine=session._attach();self.assertTrue(engine.ready.wait(1));group=session.call_group()
        started=threading.Event();cleanup_entered=threading.Event();recancelled=threading.Event();gate=[]
        async def perform(call):
            release=asyncio.Event();gate.append(release);started.set()
            try:await asyncio.Event().wait()
            finally:
                cleanup_entered.set()
                try:await release.wait()
                except asyncio.CancelledError:recancelled.set();raise
        call=gt._Call(session,time.monotonic()+.08,None,{})
        try:
            with patch.object(engine,'_perform',perform):
                engine.acquire(call);group.add(engine,call);engine.submit(call)
                self.assertTrue(started.wait(.2));engine.cancel_call(call)
                self.assertTrue(cleanup_entered.wait(.2))
                self.assertFalse(recancelled.wait(.15))
                self.assertFalse(call.done.is_set())
                self.assertEqual(engine.snapshot()['inflight'],1)
                self.assertEqual(engine.snapshot()['active_calls'],1)
                self.assertEqual(group.pending,1)
        finally:
            if gate:engine.loop.call_soon_threadsafe(gate[0].set)
            self.assertTrue(call.done.wait(.5))
        self.assertEqual(engine.snapshot()['inflight'],0)
        self.assertTrue(group.drain(time.monotonic()))

    def test_aiohttp_connect_timer_cannot_recancel_an_owned_finalizer(self):
        import asyncio
        import aiohttp
        session=gt.PooledSession(1024);self.addCleanup(session.close)
        engine=session._attach();self.assertTrue(engine.ready.wait(1));group=session.call_group()
        started=threading.Event();finalizing=threading.Event();recancelled=threading.Event();gate=[]
        async def stalled_connection(connector,*args,**kwargs):
            release=asyncio.Event();gate.append(release);started.set()
            try:await asyncio.Event().wait()
            finally:
                finalizing.set()
                try:await release.wait()
                except asyncio.CancelledError:recancelled.set();raise
        call=gt._Call(session,time.monotonic()+.5,None,
                      {'url':'http://127.0.0.1:9/','headers':{},'json':{},'timeout':(.08,.4)})
        try:
            with patch.object(aiohttp.TCPConnector,'_create_connection',stalled_connection):
                engine.acquire(call);group.add(engine,call);engine.submit(call)
                self.assertTrue(started.wait(.2));engine.cancel_call(call)
                self.assertTrue(finalizing.wait(.2))
                self.assertFalse(recancelled.wait(.18))
                self.assertFalse(call.done.is_set())
                self.assertEqual(engine.snapshot()['inflight'],1)
                self.assertEqual(group.pending,1)
        finally:
            if gate:engine.loop.call_soon_threadsafe(gate[0].set)
            self.assertTrue(call.done.wait(.5))
        self.assertIsInstance(call.result.exception(),gt.CancelledAttempt,
                              'a rejected connect-timer cancellation must not relabel owner cancellation')
        self.assertTrue(group.drain(time.monotonic()))

    def test_genuine_connect_expiry_preserves_cap_and_retains_finalization(self):
        import asyncio
        import aiohttp
        import requests
        session=gt.PooledSession(1024);self.addCleanup(session.close)
        engine=session._attach();self.assertTrue(engine.ready.wait(1));group=session.call_group()
        started=threading.Event();finalizing=threading.Event();recancelled=threading.Event();gate=[]
        async def stalled_connection(connector,*args,**kwargs):
            release=asyncio.Event();gate.append(release);started.set()
            try:await asyncio.Event().wait()
            finally:
                finalizing.set()
                try:await release.wait()
                except asyncio.CancelledError:recancelled.set();raise
        call=gt._Call(session,time.monotonic()+.5,None,
                      {'url':'http://127.0.0.1:9/','headers':{},'json':{},'timeout':(.08,.4)})
        before=time.monotonic()
        try:
            with patch.object(aiohttp.TCPConnector,'_create_connection',stalled_connection):
                engine.acquire(call);group.add(engine,call);engine.submit(call)
                self.assertTrue(started.wait(.2));self.assertTrue(finalizing.wait(.2))
                self.assertLess(time.monotonic()-before,.2,'connect cap must initiate cancellation before total deadline')
                self.assertFalse(recancelled.wait(.18))
                self.assertFalse(call.done.is_set());self.assertEqual(group.pending,1)
                self.assertEqual(engine.snapshot()['inflight'],1)
        finally:
            if gate:engine.loop.call_soon_threadsafe(gate[0].set)
            self.assertTrue(call.done.wait(.5))
        self.assertIsInstance(call.result.exception(),requests.Timeout)
        self.assertTrue(group.drain(time.monotonic()))

    def test_actual_nested_sock_connect_timers_preserve_cancel_provenance(self):
        import asyncio
        import aiohappyeyeballs
        import requests
        cancel=gt._NativeRequestTask.cancel
        for manual in (True,False):
            session=gt.PooledSession(1024)
            engine=session._attach();self.assertTrue(engine.ready.wait(1));group=session.call_group()
            started=threading.Event();finalizing=threading.Event();recancelled=threading.Event();gate=[];attempts=[]
            async def stalled_socket(*args,**kwargs):
                release=asyncio.Event();gate.append(release);started.set()
                try:await asyncio.Event().wait()
                finally:
                    finalizing.set()
                    try:await release.wait()
                    except asyncio.CancelledError:recancelled.set();raise
            def observed_cancel(task,msg=None):
                result=cancel(task,msg);attempts.append(result);return result
            call=gt._Call(session,time.monotonic()+.5,None,
                          {'url':'http://127.0.0.1:9/','headers':{},'json':{},'timeout':(.08,.4)})
            before=time.monotonic()
            try:
                with patch.object(aiohappyeyeballs,'start_connection',stalled_socket), patch.object(gt._NativeRequestTask,'cancel',observed_cancel):
                    engine.acquire(call);group.add(engine,call);engine.submit(call)
                    self.assertTrue(started.wait(.2))
                    if manual:engine.cancel_call(call)
                    self.assertTrue(finalizing.wait(.2))
                    if not manual:self.assertLess(time.monotonic()-before,.2)
                    self.assertFalse(recancelled.wait(.18))
                    self.assertFalse(call.done.is_set());self.assertEqual(group.pending,1)
                    self.assertEqual(engine.snapshot()['active_calls'],1)
                    self.assertEqual(attempts.count(True),1)
                    self.assertIn(False,attempts,'real nested timeout must be rejected, not disabled')
            finally:
                if gate:engine.loop.call_soon_threadsafe(gate[0].set)
                self.assertTrue(call.done.wait(.5));session.close(.5)
            expected=gt.CancelledAttempt if manual else requests.Timeout
            self.assertIsInstance(call.result.exception(),expected)
            self.assertTrue(group.drain(time.monotonic()))

    def test_uncancel_does_not_rearm_cancellation_during_outer_finalizer(self):
        import asyncio
        session=gt.PooledSession(1024);self.addCleanup(session.close)
        engine=session._attach();self.assertTrue(engine.ready.wait(1));group=session.call_group()
        started=threading.Event();inner_ready=threading.Event();outer_ready=threading.Event();recancelled=threading.Event()
        gates=[];attempt=[]
        async def perform(call):
            inner=asyncio.Event();outer=asyncio.Event();gates.extend((inner,outer));started.set()
            try:
                async with asyncio.timeout(.03):
                    try:await asyncio.Event().wait()
                    finally:inner_ready.set();await inner.wait()
            finally:
                outer_ready.set()
                try:await outer.wait()
                except asyncio.CancelledError:recancelled.set();raise
        call=gt._Call(session,time.monotonic()+.5,None,{})
        try:
            with patch.object(engine,'_perform',perform):
                engine.acquire(call);group.add(engine,call);engine.submit(call)
                self.assertTrue(started.wait(.2));engine.cancel_call(call);self.assertTrue(inner_ready.wait(.2))
                self.assertFalse(recancelled.wait(.06));engine.loop.call_soon_threadsafe(gates[0].set)
                self.assertTrue(outer_ready.wait(.2));self.assertEqual(call.task.cancelling(),0)
                def late_phase_cancel():attempt.append(call.task.cancel())
                engine.loop.call_soon_threadsafe(late_phase_cancel)
                self.assertFalse(recancelled.wait(.05));self.assertEqual(attempt,[False])
                self.assertFalse(call.done.is_set());self.assertEqual(group.pending,1)
        finally:
            for gate in gates:engine.loop.call_soon_threadsafe(gate.set)
            self.assertTrue(call.done.wait(.5))
        self.assertIsInstance(call.result.exception(),gt.CancelledAttempt)
        self.assertTrue(group.drain(time.monotonic()))

    def test_real_sock_read_cap_is_not_replaced_by_total_deadline(self):
        import requests
        self.fixture.srv.mode='hold'
        session=gt.PooledSession(1024);self.addCleanup(session.close);group=session.call_group()
        before=time.monotonic()
        with self.assertRaises(requests.Timeout):
            session.post(self.fixture.endpoint,headers={},json={},timeout=(.4,.04),
                         deadline=time.monotonic()+.5,call_group=group)
        self.assertLess(time.monotonic()-before,.2)
        self.assertTrue(self.fixture.srv.started.is_set())
        self.assertTrue(group.drain(time.monotonic()+.1))
        self.assertEqual(session.snapshot()['active_calls'],0)
