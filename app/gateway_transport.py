"""Owned, process-bounded async HTTP transport behind the synchronous gateway.

One selector loop owns reusable aiohttp pools and c-ares DNS. Cancellation
propagates through DNS, connect, headers and decoded-body reads; no libc
resolver executor or detached Requests worker can later transmit a POST.
"""
import asyncio
import atexit
from concurrent.futures import Future, TimeoutError as FutureTimeout
import inspect
import os
import threading
import time
import zlib

import aiohttp
import requests


class CancelledAttempt(requests.RequestException):
    """The owning request cancelled this attempt, not a provider failure."""


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


class _Engine:
    def __init__(self):
        self.capacity = int(os.getenv("GATEWAY_MAX_UPSTREAM_REQUESTS", "8"))
        if self.capacity < 1:
            raise ValueError("GATEWAY_MAX_UPSTREAM_REQUESTS must be positive")
        self.condition = threading.Condition()
        self.owners, self.calls, self.clients = set(), set(), {}
        self.used, self.peak, self.closed = 0, 0, False
        self.ready = threading.Event()
        self.start_error = None
        self.thread = threading.Thread(target=self._run, name="gateway-io", daemon=True)
        self.thread.start()

    def _run(self):
        # c-ares integrates directly with selector descriptors, also on Windows.
        try:
            self.loop = asyncio.SelectorEventLoop()
            asyncio.set_event_loop(self.loop)
        except Exception as exc:
            self.start_error = type(exc).__name__
            self.ready.set()
            return
        self.ready.set()
        try:
            if not self.closed:
                self.loop.run_forever()
        finally:
            self.loop.run_until_complete(self._close_all())
            self.loop.close()

    async def _close_client(self, owner):
        pair = self.clients.pop(owner, None)
        if pair:
            client, resolver = pair
            await client.close()
            result = resolver.close()
            if inspect.isawaitable(result):
                await result

    async def _close_all(self):
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for owner in list(self.clients):
            await self._close_client(owner)

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

    def acquire(self, owner, deadline, cancel):
        with self.condition:
            while self.used >= self.capacity:
                remaining = deadline - time.monotonic()
                if owner.closed or self.closed or (cancel and cancel.is_set()):
                    raise CancelledAttempt("gateway attempt cancelled")
                if remaining <= 0:
                    raise requests.Timeout("gateway admission deadline exceeded")
                self.condition.wait(remaining)
            if owner.closed or self.closed or (cancel and cancel.is_set()):
                raise CancelledAttempt("gateway attempt cancelled")
            if time.monotonic() >= deadline:
                raise requests.Timeout("gateway admission deadline exceeded")
            self.used += 1
            self.peak = max(self.peak, self.used)

    def submit(self, call):
        with self.condition:
            self.calls.add(call)
        def start():
            call.task = self.loop.create_task(self._request(call))
            call.task.add_done_callback(lambda task: self._finish(call, task))
            if call.cancel_requested or (call.cancel and call.cancel.is_set()):
                call.task.cancel()
        try:
            self.loop.call_soon_threadsafe(start)
        except RuntimeError:
            with self.condition:
                self.calls.discard(call)
                self.used -= 1
                self.condition.notify_all()
            call.done.set()
            call.result.set_exception(CancelledAttempt("gateway transport closed"))

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
            # Do not copy URLs, proxy credentials or request headers into errors.
            error = requests.ConnectionError("gateway transport failure: " + type(exc).__name__)
        else:
            error = None
        finally:
            with self.condition:
                self.calls.discard(call)
                self.used -= 1
                self.condition.notify_all()
            call.done.set()
        if error is None:
            call.result.set_result(value)
        else:
            call.result.set_exception(error)

    def cancel_call(self, call):
        call.cancel_requested = True
        def cancel():
            if call.task and not call.task.done():
                call.task.cancel()
        if not self.loop.is_closed():
            self.loop.call_soon_threadsafe(cancel)

    def cancel_owner(self, owner, event=None):
        with self.condition:
            calls = [c for c in self.calls if c.owner is owner and
                     (event is None or c.cancel is event)]
            self.condition.notify_all()  # wake cancelled admission waiters too
        for call in calls:
            self.cancel_call(call)
        return calls

    async def _request(self, call):
        remaining = call.deadline - time.monotonic()
        if remaining <= 0:
            raise asyncio.TimeoutError()
        if self.closed or call.owner.closed or (call.cancel and call.cancel.is_set()):
            raise asyncio.CancelledError()
        return await asyncio.wait_for(self._perform(call), timeout=remaining)

    async def _perform(self, call):
        options = call.options
        connect, read = options["timeout"]
        timeout = aiohttp.ClientTimeout(
            total=max(0.001, call.deadline - time.monotonic()),
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
        with self.condition:
            self.closed = True
            self.condition.notify_all()
            calls = list(self.calls)
        for call in calls:
            self.cancel_call(call)
        if self.ready.is_set() and hasattr(self, "loop") and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self.loop.stop)
        if threading.current_thread() is not self.thread:
            self.thread.join(timeout=2 if deadline is None else max(0.0, deadline - time.monotonic()))


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
        self._close_future = None

    def _attach(self):
        global _ENGINE
        with self._lock, _ENGINE_LOCK:
            if self.closed:
                raise CancelledAttempt("gateway transport closed")
            if self._engine is None:
                if _ENGINE is None or _ENGINE.closed:
                    _ENGINE = _Engine()
                self._engine = _ENGINE
                self._engine.owners.add(self)
            return self._engine

    def post(self, url, *, headers, json, timeout, stream=True,
             deadline=None, cancel=None):
        deadline = deadline if deadline is not None else time.monotonic() + sum(timeout)
        engine = self._attach()
        # Reserve a small part of the existing budget for native cancellation
        # drain; never add an unconditional reporting grace to caller latency.
        remaining = deadline - time.monotonic()
        cleanup = min(0.05, max(0.0, remaining / 3))
        network_deadline = deadline - cleanup
        if not engine.ready.wait(max(0.0, network_deadline - time.monotonic())):
            raise requests.Timeout("gateway I/O startup deadline exceeded")
        if engine.start_error:
            raise requests.ConnectionError("gateway I/O startup failed: " + engine.start_error)
        engine.acquire(self, network_deadline, cancel)
        call = _Call(self, network_deadline, cancel,
                     {"url": url, "headers": headers, "json": json, "timeout": timeout})
        engine.submit(call)
        try:
            return call.result.result(timeout=max(0.0, network_deadline - time.monotonic()))
        except FutureTimeout:
            engine.cancel_call(call)
            call.done.wait(max(0.0, deadline - time.monotonic()))
            raise requests.Timeout("gateway absolute HTTP deadline exceeded") from None

    def cancel(self, event):
        if self._engine:
            return self._engine.cancel_owner(self, event)
        return []

    def snapshot(self):
        return self._engine.snapshot() if self._engine else {
            "capacity": int(os.getenv("GATEWAY_MAX_UPSTREAM_REQUESTS", "8")),
            "inflight": 0, "peak_inflight": 0, "active_calls": 0, "loop_alive": False}

    def close(self, timeout=None, *, deadline=None):
        """Close this owner; optional absolute budget includes cancellation/cleanup.

        With no arguments preserve the gateway's historical two-second drain
        plus engine-stop behavior. Explicit budgets return a cleanup-completed
        bool; expired budgets still schedule native cancellation and cleanup,
        but never wait an extra grace interval. Other owners are not stopped.
        """
        global _ENGINE
        bounded = timeout is not None or deadline is not None
        if deadline is None and timeout is not None:
            deadline = time.monotonic() + max(0.0, timeout)
        with self._lock:
            if self.closed:
                if not bounded:
                    return None
                engine = self._engine
                if not engine:
                    return True
                with engine.condition:
                    active = any(c.owner is self for c in engine.calls)
                if engine.closed:
                    return not active and not engine.thread.is_alive()
                future = self._close_future
                return (not active and future is not None and future.done()
                        and not future.cancelled() and future.exception() is None)
            self.closed = True
            engine = self._engine
        if not engine:
            return True if bounded else None
        calls = engine.cancel_owner(self)
        end = deadline if bounded else time.monotonic() + 2
        complete = True
        for call in calls:
            complete = call.done.wait(max(0.0, end - time.monotonic())) and complete
        if engine.thread.is_alive() and engine.ready.is_set() and hasattr(engine, "loop"):
            future = asyncio.run_coroutine_threadsafe(engine._close_client(self), engine.loop)
            self._close_future = future
            if threading.current_thread() is not engine.thread:
                if bounded:
                    try:
                        future.result(timeout=max(0.0, end - time.monotonic()))
                    except Exception:
                        complete = False  # cleanup remains owned by the selector
                else:
                    future.result(timeout=max(0.001, end - time.monotonic()))
        with _ENGINE_LOCK:
            engine.owners.discard(self)
            last_owner = not engine.owners
            if last_owner and _ENGINE is engine:
                _ENGINE = None
        if last_owner:
            # Never hold global attach admission while joining a retiring engine.
            engine.stop(deadline=end if bounded else None)
            complete = not engine.thread.is_alive() and complete
        return complete if bounded else None


def shutdown_transport():
    global _ENGINE
    with _ENGINE_LOCK:
        engine, _ENGINE = _ENGINE, None
    if engine:
        engine.stop()


atexit.register(shutdown_transport)