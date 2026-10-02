"""Event-gated caller-lock, admission and retirement regressions; no network."""
import asyncio
import threading
import time
import unittest
from unittest.mock import patch
import requests
from app import gateway_transport as gt, otlp_export as ot


class ProbeLock:
    def __init__(self, lock):
        self.lock, self.entered = lock, threading.Event()
    def acquire(self, *a, **kw):
        self.entered.set()
        return self.lock.acquire(*a, **kw)
    def release(self):
        self.lock.release()
    def __enter__(self):
        self.acquire()
        return self
    def __exit__(self, *a):
        self.release()


class NativeDeadlineRaces(unittest.TestCase):
    def setUp(self):
        gt.shutdown_transport()
        self.addCleanup(gt.shutdown_transport)

    def held(self, lock, install, fn):
        probe = ProbeLock(lock)
        install(probe)
        row, done = {}, threading.Event()
        lock.acquire()
        def run():
            started = time.monotonic()
            try:
                row['result'] = fn()
            except Exception as exc:
                row['exception'] = exc
            finally:
                row['elapsed'] = time.monotonic() - started
                done.set()
        worker = threading.Thread(target=run)
        worker.start()
        try:
            self.assertTrue(probe.entered.wait(1))
            completed = done.wait(.15)
        finally:
            lock.release()
            worker.join(1)
        self.assertTrue(completed, row)
        self.assertLess(row['elapsed'], .10, row)
        return row

    def test_exporter_flush_and_shutdown_state_locks(self):
        for method in ('flush', 'shutdown'):
            ex = ot.OTLPExporter(endpoint='')
            row = self.held(ex._lock, lambda p: setattr(ex, '_lock', p),
                            lambda: getattr(ex, method)(.03))
            self.assertIs(row.get('result'), False)

    def test_session_close_and_post_attach_locks(self):
        for method in ('close', 'post'):
            session = gt.PooledSession(1024)
            fn = (lambda: session.close(.03)) if method == 'close' else (
                lambda: session.post('http://unused.invalid', headers={}, json={},
                                     timeout=(1, 1), deadline=time.monotonic()+.03))
            row = self.held(session._lock, lambda p: setattr(session, '_lock', p), fn)
            if method == 'close':
                self.assertIs(row.get('result'), False)
                self.assertTrue(session.closed)
            else:
                self.assertIsInstance(row.get('exception'), requests.Timeout)
            session.close(.2)

    def test_process_attach_lock(self):
        session = gt.PooledSession(1024)
        original = gt._ENGINE_LOCK
        try:
            row = self.held(original, lambda p: setattr(gt, '_ENGINE_LOCK', p),
                lambda: session.post('http://unused.invalid', headers={}, json={},
                                     timeout=(1, 1), deadline=time.monotonic()+.03))
            self.assertIsInstance(row.get('exception'), requests.Timeout)
        finally:
            gt._ENGINE_LOCK = original
            session.close(.2)

    def test_condition_admission_lock(self):
        session = gt.PooledSession(1024)
        engine = session._attach()
        self.assertTrue(engine.ready.wait(1))
        lock = threading.RLock()
        condition = threading.Condition(lock)
        engine.condition = condition
        # Signal exactly when acquire attempts the actual admission mutex.
        original = condition.acquire
        entered = threading.Event()
        def acquire(*a, **kw):
            entered.set()
            return original(*a, **kw)
        condition.acquire = acquire
        # Condition.__enter__ bypasses instance acquire in the old implementation.
        class ObservedCondition(threading.Condition):
            def __enter__(self):
                entered.set()
                return super().__enter__()
        engine.condition = ObservedCondition(lock)
        engine.condition.acquire = acquire
        row, done = {}, threading.Event()
        lock.acquire()
        def run():
            before = time.monotonic()
            try:
                session.post('http://unused.invalid', headers={}, json={}, timeout=(1,1),
                             deadline=time.monotonic()+.03)
            except Exception as exc:
                row['exception'] = exc
            row['elapsed'] = time.monotonic()-before
            done.set()
        worker = threading.Thread(target=run); worker.start()
        try:
            self.assertTrue(entered.wait(1))
            completed = done.wait(.15)
        finally:
            lock.release(); worker.join(1); session.close(.3)
        self.assertTrue(completed, row)
        self.assertLess(row['elapsed'], .10)
        self.assertIsInstance(row.get('exception'), requests.Timeout)

    def test_registered_paused_submit_retired_before_loop_close(self):
        session = gt.PooledSession(1024)
        engine = session._attach()
        self.assertTrue(engine.ready.wait(1))
        entered, release = threading.Event(), threading.Event()
        original = engine.submit
        calls, errors = [], []
        def submit(call):
            calls.append(call); entered.set(); release.wait(1); original(call)
        def post():
            try:
                session.post('http://unused.invalid', headers={}, json={}, timeout=(1,1),
                             deadline=time.monotonic()+.5)
            except Exception as exc:
                errors.append(exc)
        with patch.object(engine, 'submit', submit):
            worker = threading.Thread(target=post); worker.start()
            try:
                self.assertTrue(entered.wait(1))
                engine.stop(deadline=time.monotonic()+.3)
                self.assertFalse(engine.thread.is_alive())
                self.assertTrue(calls[0].done.is_set())
                self.assertEqual(engine.snapshot()['inflight'], 0)
            finally:
                release.set(); worker.join(1)
        self.assertIsNone(calls[0].task)
        self.assertEqual(engine.snapshot()['active_calls'], 0)
        self.assertTrue(errors)

    def test_retiring_engine_blocks_replacement_until_actual_exit(self):
        session = gt.PooledSession(1024)
        engine = session._attach()
        self.assertTrue(engine.ready.wait(1))
        entered, release = threading.Event(), threading.Event()
        close = engine.loop.close
        def gated_close():
            entered.set(); release.wait(1); close()
        engine.loop.close = gated_close
        other = gt.PooledSession(1024)
        try:
            self.assertFalse(session.close(.03))
            self.assertTrue(entered.wait(1))
            before = time.monotonic()
            with self.assertRaises(requests.Timeout):
                other.post('http://unused.invalid', headers={}, json={}, timeout=(1,1),
                           deadline=time.monotonic()+.03)
            self.assertLess(time.monotonic()-before, .10)
            self.assertIs(gt._ENGINE, engine)
            self.assertIsNone(other._engine)
        finally:
            release.set(); engine.thread.join(1); other.close(.3)

    def test_queued_start_guards_cancel_close_deadline_before_task_creation(self):
        for reason in ('cancel', 'close', 'deadline'):
            session = gt.PooledSession(1024)
            engine = session._attach()
            self.assertTrue(engine.ready.wait(1))
            entered, release = threading.Event(), threading.Event()
            def gate():
                entered.set(); release.wait(1)
            engine.loop.call_soon_threadsafe(gate)
            self.assertTrue(entered.wait(1))
            cancel = threading.Event()
            call = gt._Call(session, time.monotonic()+.4, cancel, {})
            engine.acquire(call); engine.submit(call)
            if reason == 'cancel':
                cancel.set()
            elif reason == 'close':
                session.close(0)
            else:
                call.deadline = time.monotonic()
            release.set()
            self.assertTrue(call.done.wait(.5))
            self.assertIsNone(call.task)
            self.assertEqual(engine.snapshot()['inflight'], 0)
            session.close(.5)

    def test_active_slot_retained_until_native_task_cancellation_finishes(self):
        session = gt.PooledSession(1024)
        engine = session._attach()
        self.assertTrue(engine.ready.wait(1))
        entered, cancelling = threading.Event(), threading.Event()
        gate = []
        async def perform(call):
            event = asyncio.Event(); gate.append(event); entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelling.set()
                await event.wait()
        call = gt._Call(session, time.monotonic()+1, None, {})
        with patch.object(engine, '_perform', perform):
            engine.acquire(call); engine.submit(call)
            self.assertTrue(entered.wait(.5))
            before = time.monotonic()
            self.assertFalse(session.close(.03))
            self.assertLess(time.monotonic()-before, .10)
            self.assertTrue(cancelling.wait(.5))
            self.assertFalse(call.done.is_set())
            self.assertEqual(engine.snapshot()['inflight'], 1)
            engine.loop.call_soon_threadsafe(gate[0].set)
            engine.thread.join(.5)
        self.assertFalse(engine.thread.is_alive())
        self.assertTrue(call.done.is_set())
        self.assertEqual(engine.snapshot()['inflight'], 0)
        self.assertTrue(session.close(0))

    def test_deferred_export_accounting_and_shutdown_owned_by_existing_sender(self):
        ex = ot.OTLPExporter(endpoint='http://unused.invalid', flush_interval=60, timeout=.2)
        self.assertTrue(ex.record('test', 'a'*32, 'b'*16, None, 1, 2))
        entered, response_ready = threading.Event(), threading.Event()
        row = []
        def post(*a, **kw):
            entered.set(); response_ready.wait(1)
            return gt._Response(200, {'Content-Type': 'application/json'}, b'{}')
        with patch.object(ex._session, 'post', post):
            caller = threading.Thread(target=lambda: row.append(ex.flush(.04)))
            caller.start()
            self.assertTrue(entered.wait(1))
            ex._lock.acquire()
            try:
                response_ready.set()
                caller.join(.12)
                self.assertFalse(caller.is_alive())
                self.assertEqual(row, [False])
                before = time.monotonic()
                self.assertFalse(ex.shutdown(.03))
                self.assertLess(time.monotonic()-before, .10)
                self.assertTrue(ex._thread.is_alive())
                self.assertFalse(ex.record('late', 'a'*32, 'b'*16, None, 1, 2))
            finally:
                ex._lock.release()
            ex._thread.join(.5)
        self.assertFalse(ex._thread.is_alive())
        stats = ex.stats()
        self.assertEqual(stats['exported']+stats['failed_spans']+stats['rejected_spans'], 1)
        self.assertEqual(stats['inflight'], 0)
        self.assertEqual(stats['queued'], 0)

    def test_owner_cleanup_is_deduplicated_and_awaited_by_engine_retirement(self):
        owner, other = gt.PooledSession(1024), gt.PooledSession(1024)
        engine = owner._attach(); self.assertTrue(engine.ready.wait(1)); other._attach()
        entered, installed = threading.Event(), threading.Event()
        gate, closes = [], []
        class Client:
            async def close(self):
                closes.append('client')
        class Resolver:
            async def close(self):
                closes.append('resolver')
                event = asyncio.Event(); gate.append(event); entered.set()
                await event.wait()
        def install():
            engine.clients[owner] = Client(), Resolver(); installed.set()
        engine.loop.call_soon_threadsafe(install); self.assertTrue(installed.wait(1))
        self.assertFalse(owner.close(.03)); self.assertTrue(entered.wait(1))
        self.assertFalse(owner.close(0))
        self.assertFalse(other.close(.03))
        self.assertTrue(engine.thread.is_alive())
        self.assertEqual(closes, ['client', 'resolver'])
        engine.loop.call_soon_threadsafe(gate[0].set); engine.thread.join(.5)
        self.assertFalse(engine.thread.is_alive())
        self.assertTrue(owner.close(0)); self.assertTrue(other.close(0))
        self.assertEqual(closes, ['client', 'resolver'])

    def test_owner_close_with_global_and_condition_contention_is_bounded(self):
        for field in ('global', 'condition'):
            session = gt.PooledSession(1024)
            engine = session._attach(); self.assertTrue(engine.ready.wait(1))
            mutex = gt._ENGINE_LOCK if field == 'global' else engine.condition
            mutex.acquire()
            try:
                before = time.monotonic()
                self.assertFalse(session.close(.03))
                self.assertLess(time.monotonic()-before, .10)
                self.assertTrue(session.closed)
            finally:
                mutex.release()
            self.assertTrue(session.close(.5))

    def test_admission_wake_reacquire_uses_original_deadline(self):
        session = gt.PooledSession(1024)
        engine = session._attach(); self.assertTrue(engine.ready.wait(1))
        engine.capacity = 1
        occupying = gt._Call(session, time.monotonic()+1, None, {})
        engine.acquire(occupying)
        entered, done = threading.Event(), threading.Event()
        wake = engine.admission_wake
        wait = wake.wait
        def observed_wait(timeout):
            entered.set()
            return wait(timeout)
        wake.wait = observed_wait
        row = {}
        def acquire():
            before = time.monotonic()
            try:
                engine.acquire(gt._Call(session, time.monotonic()+.03, None, {}))
            except Exception as exc:
                row['exception'] = exc
            row['elapsed'] = time.monotonic()-before; done.set()
        worker = threading.Thread(target=acquire); worker.start()
        self.assertTrue(entered.wait(1))
        engine.condition.acquire()
        try:
            engine._wake_admission()
            completed = done.wait(.15)
        finally:
            engine.condition.release(); worker.join(1); session.close(.5)
        self.assertTrue(completed, row)
        self.assertLess(row['elapsed'], .10)
        self.assertIsInstance(row.get('exception'), requests.Timeout)

    def test_record_contention_is_nonblocking_and_loss_is_visible(self):
        ex = ot.OTLPExporter(endpoint='http://unused.invalid', flush_interval=60)
        ex._lock.acquire()
        try:
            before = time.monotonic()
            for _ in range(1000):
                self.assertFalse(ex.record('lost', 'a'*32, 'b'*16, None, 1, 2))
            self.assertLess(time.monotonic()-before, .10)
        finally:
            ex._lock.release()
        self.assertEqual(ex.stats()['dropped'], 1000)
        self.assertEqual(ex.stats()['dropped'], 1000)
        ex.shutdown(.3)

    def test_cleanup_failure_does_not_strand_loop_other_owner_or_future(self):
        owner, other = gt.PooledSession(1024), gt.PooledSession(1024)
        engine = owner._attach(); self.assertTrue(engine.ready.wait(1)); other._attach()
        installed = threading.Event(); closed = []
        class Client:
            def __init__(self, label): self.label = label
            async def close(self): closed.append(self.label)
        class Resolver:
            def __init__(self, label, fail=False): self.label, self.fail = label, fail
            async def close(self):
                closed.append(self.label)
                if self.fail: raise ValueError('synthetic private cleanup error')
        def install():
            engine.clients[owner] = Client('client1'), Resolver('resolver1', True)
            engine.clients[other] = Client('client2'), Resolver('resolver2')
            installed.set()
        engine.loop.call_soon_threadsafe(install); self.assertTrue(installed.wait(1))
        errors = []
        with patch('threading.excepthook', side_effect=lambda args: errors.append(args.exc_value)):
            engine.stop(time.monotonic()+.5)
        self.assertFalse(engine.thread.is_alive())
        self.assertTrue(engine.loop.is_closed())
        self.assertEqual(errors, [])
        self.assertCountEqual(closed, ['client1','resolver1','client2','resolver2'])
        self.assertTrue(owner._close_future.done()); self.assertTrue(other._close_future.done())
        self.assertIsNotNone(owner._close_future.exception())
        self.assertIsNone(other._close_future.exception())
        self.assertFalse(owner.close(0)); self.assertTrue(other.close(0))
        self.assertNotIn('private', str(owner._close_future.exception()))

    def test_bootstrap_contention_never_blocks_request_telemetry(self):
        old = ot._default
        ot._default = None
        ot._default_lock.acquire()
        try:
            before_count = ot._bootstrap_loss_snapshot()
            before = time.monotonic()
            with self.assertRaises(requests.Timeout):
                ot.get_exporter()
            self.assertLess(time.monotonic()-before, .03)
            before = time.monotonic()
            with self.assertRaises(requests.Timeout):
                ot.get_exporter(deadline=time.monotonic()+.03)
            self.assertLess(time.monotonic()-before, .10)
            self.assertEqual(ot._bootstrap_loss_snapshot(), before_count+2)
        finally:
            ot._default_lock.release()
            ot._default = old

    def test_repeated_close_deduplicates_queued_callback_during_paused_selector(self):
        session = gt.PooledSession(1024)
        engine = session._attach(); self.assertTrue(engine.ready.wait(1))
        entered, release = threading.Event(), threading.Event()
        def gate(): entered.set(); release.wait(1)
        engine.loop.call_soon_threadsafe(gate); self.assertTrue(entered.wait(1))
        original = engine._schedule
        published = []
        def observed(callback):
            published.append(callback); return original(callback)
        with patch.object(engine, '_schedule', observed):
            for _ in range(100): self.assertFalse(session.close(0))
        self.assertEqual(len(published), 1)
        release.set(); self.assertTrue(session.close(.5))

    def test_close_before_selector_ready_keeps_owned_startup_cleanup(self):
        entered, release = threading.Event(), threading.Event()
        constructor = asyncio.SelectorEventLoop
        def loop():
            entered.set(); release.wait(1); return constructor()
        session = gt.PooledSession(1024)
        with patch.object(gt.asyncio, 'SelectorEventLoop', loop):
            engine = session._attach()
            self.assertTrue(entered.wait(1))
            self.assertFalse(session.close(.03))
            release.set()
            self.assertTrue(session.close(.5))
        self.assertFalse(engine.thread.is_alive())
        self.assertTrue(engine.loop.is_closed())

    def test_owner_publication_after_startup_scan_cannot_lose_first_close(self):
        loop_entered, loop_release = threading.Event(), threading.Event()
        add_entered, add_release = threading.Event(), threading.Event()
        constructor = asyncio.SelectorEventLoop
        def loop():
            loop_entered.set(); loop_release.wait(1); return constructor()
        class GatedOwners(set):
            def add(self, owner):
                add_entered.set(); add_release.wait(1); super().add(owner)
        session = gt.PooledSession(1024); errors=[]
        with patch.object(gt.asyncio, 'SelectorEventLoop', loop):
            engine = gt._Engine(); gt._ENGINE = engine
            engine.owners = GatedOwners()
            self.assertTrue(loop_entered.wait(1))
            def attach():
                try: session._attach(time.monotonic()+1)
                except Exception as exc: errors.append(exc)
            worker = threading.Thread(target=attach); worker.start()
            self.assertTrue(add_entered.wait(1))
            self.assertIsNone(session._engine)
            self.assertFalse(session.close(.03))
            loop_release.set(); self.assertTrue(engine.ready.wait(1))
            # Barrier posted after startup closed-owner scan/run_forever entry.
            scanned = threading.Event(); engine.loop.call_soon_threadsafe(scanned.set)
            self.assertTrue(scanned.wait(1))
            add_release.set(); worker.join(1)
        self.assertTrue(errors)
        self.assertTrue(session.close(.5))
        self.assertFalse(engine.thread.is_alive())
        self.assertTrue(engine.loop.is_closed())

    def test_registration_paused_until_after_engine_exit_is_safely_refused(self):
        engine = gt._Engine(); gt._ENGINE = engine
        self.assertTrue(engine.ready.wait(1))
        entered, release = threading.Event(), threading.Event()
        class GatedOwners(set):
            def add(self, owner):
                entered.set(); release.wait(1); super().add(owner)
        engine.owners = GatedOwners()
        session = gt.PooledSession(1024); errors=[]
        def attach():
            try: session._attach(time.monotonic()+1)
            except Exception as exc: errors.append(exc)
        worker = threading.Thread(target=attach); worker.start()
        self.assertTrue(entered.wait(1))
        engine.stop(time.monotonic()+.5)
        self.assertFalse(engine.thread.is_alive())
        self.assertTrue(engine.loop.is_closed())
        release.set(); worker.join(1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], gt.CancelledAttempt)
        self.assertIsNone(session._engine)
        self.assertNotIn(session, engine.owners)
        self.assertTrue(session.closed)
        self.assertTrue(session.close(0))
        self.assertTrue(session._close_future.done())
