"""Owned, process-bounded async HTTP transport behind the synchronous gateway.

One selector loop owns reusable aiohttp pools and c-ares DNS. Cancellation
propagates through DNS, connect, headers and decoded-body reads; no libc
resolver executor or detached Requests worker can later transmit a POST.
"""
import asyncio
import atexit
from concurrent.futures import Future, TimeoutError as FutureTimeout
from .deadline import join as _join, result as _future_result, take as _deadline_take, wait as _wait
import inspect
import itertools
import os
import threading
import time
import zlib

import aiohttp
import requests


class CancelledAttempt(requests.RequestException):
    """The owning request cancelled this attempt, not a provider failure."""


def _take(lock, deadline):
    """Every caller-side mutex wait consumes the same absolute budget."""
    return _deadline_take(lock, deadline)


class _Response:
    def __init__(self, status, headers, body):
        self.status_code, self.headers, self._body = status, headers, body

    def iter_content(self, chunk_size):
        for offset in range(0, len(self._body), chunk_size):
            yield self._body[offset:offset + chunk_size]

    def close(self):
        self._body = b""


class _Call:
    def __init__(self, owner, deadline, cancel, options):
        self.owner, self.deadline, self.cancel, self.options = owner, deadline, cancel, options
        self.result, self.done, self.task = Future(), threading.Event(), None
        self.cancel_requested = False
        self.registered = self.retired = False
        self.deadline_handle = None
        self.deadline_expired = False


class _NativeRequestTask(asyncio.Task):
    """Cancellation admission for this one real native IO task, not the loop.

    aiohttp/asyncio phase timers may call cancel directly and later uncancel.
    Admit one cancellation for the request lifetime; uncancel can update the
    standard Task counter but cannot re-arm cancellation during finalization.
    No shielded worker/task is detached, and phase timeout caps stay intact.
    """
    def __init__(self, coro, *, call, loop):
        self._native_call = call
        self._cancel_admitted = False
        self.cancel_origin = None
        super().__init__(coro, loop=loop)

    def cancel(self, msg=None):
        if self._cancel_admitted or self.done():
            return False
        call = self._native_call
        if call.cancel_requested or call.owner.closed or (call.cancel and call.cancel.is_set()):
            self.cancel_origin = "owner"
        elif call.deadline_expired:
            self.cancel_origin = "deadline"
        else:
            self.cancel_origin = "phase"
        self._cancel_admitted = True
        return super().cancel(msg)


class _CallGroup:
    """Sender-owned handles; immutable snapshots allow truthful status reads.

    Only the serialized sender registers/drains this group. Completed handles
    are pruned before each admission; an unfinished call prevents the exporter
    from submitting another batch. There is no per-failure orphan worker/list.
    """
    def __init__(self, owner):
        self.owner = owner
        self._calls = ()

    def add(self, engine, call):
        self._calls = tuple(pair for pair in self._calls if not pair[1].done.is_set()) + ((engine, call),)

    @property
    def pending(self):
        return sum(not call.done.is_set() for _, call in self._calls)

    def drain(self, deadline):
        calls = self._calls
        for engine, call in calls:
            # Re-cancelling a task can interrupt its cancellation finalizer.
            # Publish cancellation once; never retire an active slot here.
            if not call.done.is_set() and not call.cancel_requested:
                engine.cancel_call(call)
        complete = True
        for _, call in calls:
            complete = _wait(call.done, deadline) and complete
        self._calls = tuple(pair for pair in calls if not pair[1].done.is_set())
        return complete and not self._calls


class _Engine:
    def __init__(self):
        self.capacity = int(os.getenv("GATEWAY_MAX_UPSTREAM_REQUESTS", "8"))
        if self.capacity < 1:
            raise ValueError("GATEWAY_MAX_UPSTREAM_REQUESTS must be positive")
        self.condition = threading.Condition()
        self.admission_wake = threading.Event()
        self.owners, self.calls, self.clients = set(), set(), {}
        self.used, self.peak, self.closed = 0, 0, False
        self.ready = threading.Event()
        self.start_error = None
        self.terminated = threading.Event()
        self.cleanups = set()
        self.cleanup_errors = {}
        self.thread = threading.Thread(target=self._run, name="gateway-io", daemon=True)
        self.thread.start()

    def _run(self):
        # Only this thread creates tasks and owns deferred cleanup. The global
        # engine remains a retirement barrier until this thread actually exits.
        try:
            self.loop = asyncio.SelectorEventLoop()
            asyncio.set_event_loop(self.loop)
            self.ready.set()
            # Closure may have been published before the loop existed. Such
            # an owner remains in our registry; bootstrap owns its deferred
            # intent instead of relying on a dropped cross-thread callback.
            for owner in list(self.owners):
                if owner.closed:
                    self.loop.call_soon(self._close_owner, owner)
            if not self.closed:
                self.loop.run_forever()
        except Exception as exc:
            self.start_error = type(exc).__name__
        finally:
            self.closed = True
            self.ready.set()
            try:
                if hasattr(self, "loop"):
                    try:
                        self.loop.run_until_complete(self._close_all())
                    except Exception:
                        # A cleanup failure must not strand the selector open
                        # or leave a completion future claiming pending forever.
                        for owner in set(self.owners) | set(self.clients):
                            if not owner._close_future.done():
                                owner._close_future.set_exception(
                                    CancelledAttempt("gateway cleanup failed"))
                    finally:
                        self.loop.close()
            finally:
                self.terminated.set()

    async def _close_client(self, owner):
        # Keep the pair visible until cleanup completes, including a suspended
        # resolver. Failure is retained and never retried or called success.
        if owner in self.cleanup_errors:
            raise self.cleanup_errors[owner]
        pair = self.clients.get(owner)
        if not pair:
            return
        client, resolver = pair
        failed = False
        try:
            await client.close()
        except Exception:
            failed = True
        try:
            result = resolver.close()
            if inspect.isawaitable(result):
                await result
        except Exception:
            failed = True
        if failed:
            error = CancelledAttempt("gateway cleanup failed")
            self.cleanup_errors[owner] = error
            raise error
        self.clients.pop(owner, None)

    async def _close_all(self):
        with self.condition:
            calls = list(self.calls)
        for call in calls:
            call.cancel_requested = True
            if call.task is None:
                self._retire(call, error=CancelledAttempt("gateway transport closed"))
            else:
                self._cancel_task_once(call)
        tasks = [c.task for c in calls if c.task is not None]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        # Completion dispatch may be deliberately delayed; retirement itself
        # is idempotent, including a never-submitted registered reservation.
        for call in calls:
            if call.task is not None:
                self._finish(call, call.task)
        if self.cleanups:
            await asyncio.gather(*list(self.cleanups), return_exceptions=True)
        cleanup_owners = set(self.owners) | set(self.clients)
        for owner in list(self.clients):
            try:
                await self._close_client(owner)
            except Exception:
                # Attempt every owner's cleanup even if an earlier resolver
                # fails. _close_client records a sanitized terminal outcome.
                pass
        for owner in cleanup_owners:
            if not owner._close_future.done():
                if owner in self.cleanup_errors:
                    owner._close_future.set_exception(self.cleanup_errors[owner])
                else:
                    owner._close_future.set_result(True)

    def _schedule(self, callback):
        # Do not create a coroutine on a caller thread or a stopped/open loop.
        if self.closed or not self.ready.is_set() or not hasattr(self, "loop"):
            return False
        try:
            if self.loop.is_closed():
                return False
            self.loop.call_soon_threadsafe(callback)
            return True
        except RuntimeError:
            return False

    def close_owner(self, owner):
        # closed intent is visible even if callback dispatch is paused. If the
        # engine is retiring, _close_all owns this owner's resources instead.
        if next(owner._close_requests) == 0:
            self._schedule(lambda: self._close_owner(owner))

    def _close_owner(self, owner):
        if self.closed:
            return
        with _ENGINE_LOCK:
            self.owners.discard(owner)
            last = not self.owners
            if last:
                self.closed = True
        with self.condition:
            calls = [c for c in self.calls if c.owner is owner]
            self._wake_admission()
        for call in calls:
            self.cancel_call(call)
        if last:
            # _close_all, not a newly queued coroutine, owns final cleanup.
            # Include the retired owner for its completion future.
            self.owners.add(owner)
            self.loop.stop()
            return
        if owner._cleanup_started:
            return
        owner._cleanup_started = True
        async def cleanup():
            for call in calls:
                if call.task is not None:
                    await asyncio.gather(call.task, return_exceptions=True)
                    self._finish(call, call.task)
                else:
                    self._retire(call, error=CancelledAttempt("gateway transport closed"))
            await self._close_client(owner)
        task = self.loop.create_task(cleanup())
        self.cleanups.add(task)
        def finished(task):
            self.cleanups.discard(task)
            if not owner._close_future.done():
                if task.cancelled():
                    owner._close_future.set_exception(CancelledAttempt("gateway cleanup cancelled"))
                elif task.exception() is not None:
                    owner._close_future.set_exception(task.exception())
                else:
                    owner._close_future.set_result(True)
        task.add_done_callback(finished)

    def _client(self, owner):
        if owner not in self.clients:
            resolver = (owner.resolver_factory(self.loop) if owner.resolver_factory
                        else aiohttp.AsyncResolver())
            connector = aiohttp.TCPConnector(
                resolver=resolver, use_dns_cache=False, limit=self.capacity,
                timeout_ceil_threshold=float("inf"))
            client = aiohttp.ClientSession(
                connector=connector, auto_decompress=False,
                cookie_jar=aiohttp.DummyCookieJar(), trust_env=False,
                read_bufsize=16_384, max_line_size=8190, max_field_size=8190)
            self.clients[owner] = client, resolver
        return self.clients[owner][0]

    def _wake_admission(self):
        # Registry mutex held by selector. Each epoch stays signaled forever;
        # later waiters use a fresh event, so notification cannot be cleared
        # before an earlier waiter actually begins its unlocked wait.
        wake, self.admission_wake = self.admission_wake, threading.Event()
        wake.set()
        self.condition.notify_all()

    def acquire(self, call):
        deadline, owner, cancel = call.deadline, call.owner, call.cancel
        while True:
            if not _take(self.condition, deadline):
                raise requests.Timeout("gateway admission deadline exceeded")
            try:
                if owner.closed or self.closed or (cancel and cancel.is_set()):
                    raise CancelledAttempt("gateway attempt cancelled")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise requests.Timeout("gateway admission deadline exceeded")
                if self.used < self.capacity:
                    # Reservation and registry publication are one transaction.
                    self.calls.add(call)
                    call.registered = True
                    self.used += 1
                    self.peak = max(self.peak, self.used)
                    return
                wake = self.admission_wake
            finally:
                self.condition.release()
            # Condition.wait would implicitly reacquire an unbounded mutex.
            # Wait unlocked, then re-enter through _take(original deadline).
            if not _wait(wake, deadline):
                raise requests.Timeout("gateway admission deadline exceeded")

    def submit(self, call):
        def start():
            if call.retired or call.done.is_set() or call.result.done():
                return
            if (self.closed or call.owner.closed or call.cancel_requested
                    or (call.cancel and call.cancel.is_set())):
                self._retire(call, error=CancelledAttempt("gateway attempt cancelled"))
                return
            if time.monotonic() >= call.deadline:
                self._retire(call, error=requests.Timeout("gateway absolute HTTP deadline exceeded"))
                return
            call.task = _NativeRequestTask(self._request(call), call=call, loop=self.loop)
            call.task.add_done_callback(lambda task: self._finish(call, task))
        if not self._schedule(start):
            call.cancel_requested = True
            # If retiring, _close_all owns retirement of the registered call;
            # do not take its mutex or create a late task on the caller thread.

    def _retire(self, call, value=None, error=None):
        with self.condition:
            if call.retired:
                return
            call.retired = True
            if call.registered:
                self.calls.discard(call)
                self.used -= 1
                self._wake_admission()
            if error is None:
                call.result.set_result(value)
            else:
                call.result.set_exception(error)
            call.done.set()

    def _finish(self, call, task):
        try:
            value = task.result()
        except asyncio.CancelledError:
            error = CancelledAttempt("gateway attempt cancelled")
        except (asyncio.TimeoutError, TimeoutError):
            error = requests.Timeout("gateway absolute HTTP deadline exceeded")
        except requests.RequestException as exc:
            error = exc
        except Exception as exc:
            error = requests.ConnectionError("gateway transport failure: " + type(exc).__name__)
        else:
            return self._retire(call, value=value)
        self._retire(call, error=error)

    def _cancel_task_once(self, call):
        # Selector-only: manual cancellation disarms the absolute deadline,
        # and expiry itself cannot interrupt an already-running finalizer.
        handle, call.deadline_handle = call.deadline_handle, None
        if handle is not None:
            handle.cancel()
        if call.task is not None and not call.task.done() and not call.task.cancelling():
            call.task.cancel()

    def cancel_call(self, call):
        call.cancel_requested = True
        def cancel():
            if call.retired:
                return
            if call.task is None:
                self._retire(call, error=CancelledAttempt("gateway attempt cancelled"))
            else:
                self._cancel_task_once(call)
        self._schedule(cancel)

    def cancel_owner(self, owner, event=None):
        def cancel():
            with self.condition:
                calls = [c for c in self.calls if c.owner is owner and
                         (event is None or c.cancel is event)]
                self._wake_admission()
            for call in calls:
                self.cancel_call(call)
        self._schedule(cancel)
        return []  # asynchronous intent; completion belongs to each call.done

    async def _request(self, call):
        remaining = call.deadline - time.monotonic()
        if remaining <= 0:
            raise asyncio.TimeoutError()
        if (self.closed or call.owner.closed or call.cancel_requested or call.retired
                or (call.cancel and call.cancel.is_set())):
            raise asyncio.CancelledError()
        def expire():
            if not call.cancel_requested:
                call.deadline_expired = True
            self._cancel_task_once(call)
        call.deadline_handle = self.loop.call_at(call.deadline, expire)
        try:
            value = await self._perform(call)
            origin = call.task.cancel_origin
            if origin is not None or time.monotonic() >= call.deadline:
                if isinstance(value, _Response):
                    value.close()
                if origin == "owner":
                    raise asyncio.CancelledError()
                raise asyncio.TimeoutError()
            return value
        except asyncio.CancelledError:
            if call.task.cancel_origin == "deadline":
                raise asyncio.TimeoutError() from None
            raise
        except asyncio.TimeoutError:
            # A rejected later aiohttp timeout still marks its context expired
            # and may translate the first manual CancelledError on __aexit__.
            # Preserve the cancellation that actually initiated finalization.
            if call.task.cancel_origin == "owner":
                raise asyncio.CancelledError() from None
            raise
        finally:
            handle, call.deadline_handle = call.deadline_handle, None
            if handle is not None:
                handle.cancel()

    async def _perform(self, call):
        # Refuse before pool/resolver/socket creation if cancellation/closure
        # arrived after the selector's start guard.
        if (self.closed or call.owner.closed or call.cancel_requested or call.retired
                or (call.cancel and call.cancel.is_set())):
            raise asyncio.CancelledError()
        if time.monotonic() >= call.deadline:
            raise asyncio.TimeoutError()
        options = call.options
        connect, read = options["timeout"]
        timeout = aiohttp.ClientTimeout(
            # The owned once-only _request timer enforces the absolute total.
            # A second aiohttp total timer could recancel retained finalization.
            total=None,
            connect=connect, sock_connect=connect, sock_read=read,
            ceil_threshold=float("inf"))
        async with self._client(call.owner).post(
                options["url"], headers=options["headers"], json=options["json"],
                timeout=timeout, allow_redirects=False, proxy=call.owner.proxy) as response:
            status, headers = response.status, dict(response.headers)
            if status not in (200, 429):
                return _Response(status, headers, b"")
            limit = (call.owner.max_response_bytes if status == 200 else
                     min(4096, call.owner.max_response_bytes))
            body = await self._read_body(response, limit, prefix=status == 429)
            return _Response(status, headers, body)

    @staticmethod
    async def _read_body(response, limit, prefix=False):
        coding = response.headers.get("Content-Encoding", "").strip().lower()
        if coding in ("gzip", "deflate"):
            decoder = zlib.decompressobj(16 + zlib.MAX_WBITS if coding == "gzip"
                                         else zlib.MAX_WBITS)
        elif coding in ("", "identity"):
            decoder = None
        else:
            raise requests.ConnectionError("unsupported gateway content encoding")
        body, wire = bytearray(), 0
        wire_limit = max(65_536, limit * 4 + 65_536)
        while True:
            chunk = await response.content.read(16_384)
            if not chunk:
                if decoder is not None and not decoder.eof:
                    raise requests.ConnectionError("truncated compressed gateway response")
                return bytes(body)
            wire += len(chunk)
            if wire > wire_limit:
                raise requests.ConnectionError("gateway wire byte limit exceeded")
            pending = chunk
            while pending:
                allowance = min(16_384, limit - len(body) + (0 if prefix else 1))
                if allowance <= 0:
                    return bytes(body)
                decoded = decoder.decompress(pending, allowance) if decoder else pending
                pending = decoder.unconsumed_tail if decoder else b""
                if prefix:
                    body.extend(decoded[:limit - len(body)])
                    if len(body) == limit:
                        return bytes(body)
                else:
                    if len(body) + len(decoded) > limit:
                        raise requests.ConnectionError("gateway decoded byte limit exceeded")
                    body.extend(decoded)

    def snapshot(self):
        with self.condition:
            return {"capacity": self.capacity, "inflight": self.used,
                    "peak_inflight": self.peak, "active_calls": len(self.calls),
                    "loop_alive": self.thread.is_alive()}

    def stop(self, deadline=None):
        # Publish stop without waiting for a contended condition/global mutex.
        self.closed = True
        self.admission_wake.set()
        if self.ready.is_set() and hasattr(self, "loop"):
            try:
                self.loop.call_soon_threadsafe(self.loop.stop)
            except RuntimeError:
                pass
        if threading.current_thread() is not self.thread:
            self.thread.join(timeout=2) if deadline is None else _join(self.thread, deadline)


_ENGINE = None
_ENGINE_LOCK = threading.RLock()


class PooledSession:
    """Small synchronous facade; the owned async loop performs all real I/O."""
    def __init__(self, max_response_bytes):
        self.max_response_bytes, self.closed = max_response_bytes, False
        self.resolver_factory = None  # deterministic resolver injection for tests
        # Explicit operator routing only: avoid executor-backed ambient
        # proxy/netrc discovery and accidental filesystem credential reads.
        self.proxy = os.getenv("GATEWAY_PROXY_URL", "").strip() or None
        if self.proxy:
            from urllib.parse import urlsplit
            try:
                target = urlsplit(self.proxy)
                valid = (target.scheme in ("http", "https") and target.hostname
                         and not target.query and not target.fragment
                         and target.path in ("", "/") and len(self.proxy) <= 2048)
                _ = target.port
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("GATEWAY_PROXY_URL must be a clean HTTP(S) origin")
        self._engine, self._lock = None, threading.RLock()
        self._close_future = Future()
        self._cleanup_started = False
        # Atomic CPython count primitive deduplicates publication, including
        # repeated close while selector dispatch is paused.
        self._close_requests = itertools.count()

    def _attach(self, deadline=None):
        global _ENGINE
        deadline = time.monotonic() + 2 if deadline is None else deadline
        if not _take(self._lock, deadline):
            raise requests.Timeout("gateway session admission deadline exceeded")
        try:
            while True:
                if self.closed:
                    raise CancelledAttempt("gateway transport closed")
                if self._engine is not None:
                    if self._engine.closed:
                        raise CancelledAttempt("gateway transport retiring")
                    return self._engine
                if not _take(_ENGINE_LOCK, deadline):
                    raise requests.Timeout("gateway process admission deadline exceeded")
                retiring = None
                try:
                    if _ENGINE is not None and _ENGINE.closed and _ENGINE.thread.is_alive():
                        retiring = _ENGINE
                    else:
                        if _ENGINE is None or _ENGINE.closed:
                            _ENGINE = _Engine()
                        # Publish owner registration before the session pointer.
                        # close can never consume its single publication token
                        # for an engine whose startup scan cannot see this owner.
                        engine = _ENGINE
                        engine.owners.add(self)
                        # stop deliberately publishes intent without the global
                        # mutex. It may have completed during owner insertion.
                        # This owner has never admitted IO: detach and close it
                        # instead of returning a finalized engine whose final
                        # snapshot can no longer resolve its closure future.
                        if engine.closed:
                            engine.owners.discard(self)
                            self.closed = True
                            raise CancelledAttempt("gateway transport retiring")
                        self._engine = engine
                finally:
                    _ENGINE_LOCK.release()
                if retiring is not None:
                    # No global lock is held while retirement waits. A completed
                    # cleanup event is not enough: actual thread exit is required.
                    _join(retiring.thread, deadline)
                    if retiring.thread.is_alive() or time.monotonic() >= deadline:
                        raise requests.Timeout("gateway retirement deadline exceeded")
                    continue
                if self.closed:
                    self._engine.close_owner(self)
                    raise CancelledAttempt("gateway transport closed")
                return self._engine
        finally:
            self._lock.release()

    @property
    def cleanup_pending(self):
        if not self.closed:
            return False
        engine = self._engine
        return (not self._close_future.done() or
                (engine is not None and engine.closed and engine.thread.is_alive()))

    def call_group(self):
        return _CallGroup(self)

    def post(self, url, *, headers, json, timeout, stream=True,
             deadline=None, cancel=None, call_group=None):
        if call_group is not None and call_group.owner is not self:
            raise ValueError("native call group belongs to another owner")
        deadline = deadline if deadline is not None else time.monotonic() + sum(timeout)
        engine = self._attach(deadline)
        # Reserve a small part of the existing budget for native cancellation
        # drain; never add an unconditional reporting grace to caller latency.
        remaining = deadline - time.monotonic()
        # A tracked sender reserves cleanup once for its whole flush. Ordinary
        # gateway callers retain their historical per-post internal reserve.
        cleanup = 0.0 if call_group is not None else min(0.05, max(0.0, remaining / 3))
        network_deadline = deadline - cleanup
        if not _wait(engine.ready, network_deadline):
            raise requests.Timeout("gateway I/O startup deadline exceeded")
        if engine.start_error:
            raise requests.ConnectionError("gateway I/O startup failed: " + engine.start_error)
        call = _Call(self, network_deadline, cancel,
                     {"url": url, "headers": headers, "json": json, "timeout": timeout})
        engine.acquire(call)
        if call_group is not None:
            call_group.add(engine, call)
        engine.submit(call)
        try:
            return _future_result(call.result, network_deadline)
        except FutureTimeout:
            engine.cancel_call(call)
            drained = _wait(call.done, deadline)
            error = requests.Timeout("gateway absolute HTTP deadline exceeded")
            error.cleanup_pending = not drained
            raise error from None

    def cancel(self, event):
        if self._engine:
            return self._engine.cancel_owner(self, event)
        return []

    def snapshot(self):
        return self._engine.snapshot() if self._engine else {
            "capacity": int(os.getenv("GATEWAY_MAX_UPSTREAM_REQUESTS", "8")),
            "inflight": 0, "peak_inflight": 0, "active_calls": 0, "loop_alive": False}

    def close(self, timeout=None, *, deadline=None):
        """Publish closure immediately; wait only within the caller's budget.

        Deferred cleanup is owned by the existing selector and its finalizer,
        never by a detached helper thread or a caller-created late coroutine.
        """
        bounded = timeout is not None or deadline is not None
        end = (deadline if deadline is not None else
               time.monotonic() + (2 if timeout is None else max(0.0, timeout)))
        self.closed = True
        engine = self._engine
        if engine is not None:
            engine.close_owner(self)
        if not _take(self._lock, end):
            return False if bounded else None
        try:
            engine = self._engine
            if engine is None:
                if not self._close_future.done():
                    self._close_future.set_result(True)
                return True if bounded else None
            engine.close_owner(self)
        finally:
            self._lock.release()
        complete = False
        try:
            complete = _future_result(self._close_future, end)
        except Exception:
            pass
        if engine.closed and threading.current_thread() is not engine.thread:
            _join(engine.thread, end)
            complete = complete and not engine.thread.is_alive()
        return bool(complete) if bounded else None


def shutdown_transport():
    # Do not clear the process retirement barrier before actual termination.
    engine = _ENGINE
    if engine:
        engine.stop()


atexit.register(shutdown_transport)