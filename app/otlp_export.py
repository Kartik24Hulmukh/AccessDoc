"""Bounded OTLP/HTTP JSON exporter with owned native absolute deadlines.

The native PooledSession uses cancellable selector/c-ares I/O (DNS through
bounded decoded body), not detached HTTP workers. Each exporter owns its client
pool, but SHARES GATEWAY_MAX_UPSTREAM_REQUESTS process-wide native admission
with gateway requests. Collector work can consume a slot; admission wait is
inside the export budget. Gateway proxy routing is NOT inherited by collectors.

record is bounded enqueue only. Exactly one sender owns drain/network/accounting.
Each batch is attempted once, including partial rejection. Exported means
collector-accepted spans; rejected, unconfirmed failures, overflow and shutdown
losses are separate. Public status contains fixed codes, never collector text.
"""
from __future__ import annotations

import atexit
import collections
import itertools
import json
import math
import os
import queue
import threading
import time
import urllib.parse

import requests
from .gateway_transport import PooledSession, _take
from .deadline import join as _join

_MAX_QUEUE = 2048
_MAX_BATCH = 256
_MAX_ATTR_LEN = 256
_MAX_RESPONSE_BYTES = 65_536
_MAX_PAYLOAD_BYTES = 4 * 1024 * 1024


def _endpoint():
    ep = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "").strip()
    if ep:
        return ep
    base = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    return base.rstrip("/") + "/v1/traces" if base else ""


def _headers():
    out = {"Content-Type": "application/json", "Accept": "application/json"}
    raw = os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "")
    for part in itertools.islice(raw.split(","), 32):
        if "=" in part:
            k, v = part.split("=", 1)
            k = k.strip()[:128]
            if k:
                out[k] = urllib.parse.unquote(v.strip())[:1024]
    return out


def _attr(k, v):
    k = str(k)[:128]
    if isinstance(v, bool):
        return {"key": k, "value": {"boolValue": v}}
    if isinstance(v, int) and -(2**63) <= v < 2**63:
        return {"key": k, "value": {"intValue": str(v)}}
    if isinstance(v, float) and math.isfinite(v):
        return {"key": k, "value": {"doubleValue": v}}
    return {"key": k, "value": {"stringValue": str(v)[:_MAX_ATTR_LEN]}}


def _seconds(value):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("export intervals/timeouts must be positive and finite")
    return value


def _budget(value):
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError("export budget must be nonnegative and finite")
    return value


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate response key")
        obj[key] = value
    return obj


def _rejections(raw, batch_size):
    """Validate bounded JSON ExportTraceServiceResponse, ignoring private text."""
    obj = json.loads(raw, object_pairs_hook=_unique_object,
                     parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
    if not isinstance(obj, dict) or set(obj) - {"partialSuccess"}:
        raise ValueError("invalid export response")
    if "partialSuccess" not in obj:
        return 0
    part = obj["partialSuccess"]
    if not isinstance(part, dict) or set(part) - {"rejectedSpans", "errorMessage"}:
        raise ValueError("invalid partial response")
    if "errorMessage" in part and not isinstance(part["errorMessage"], str):
        raise ValueError("invalid collector message")
    n = part.get("rejectedSpans", 0)
    if isinstance(n, str) and n.isascii() and n.isdigit() and len(n) <= 20:
        n = int(n)
    if type(n) is not int or not 0 <= n <= batch_size:
        raise ValueError("invalid rejected span count")
    return n


class OTLPExporter:
    def __init__(self, endpoint=None, service_name=None, flush_interval=None,
                 timeout=None, max_queue=_MAX_QUEUE, max_batch=_MAX_BATCH):
        self.endpoint = endpoint if endpoint is not None else _endpoint()
        if self.endpoint:
            u = urllib.parse.urlsplit(self.endpoint)
            if (len(self.endpoint) > 2048 or u.scheme not in ("http", "https")
                    or not u.hostname or u.username is not None or u.password is not None
                    or u.fragment):
                raise ValueError("invalid OTLP endpoint")
            _ = u.port
        self.service_name = str(service_name or os.getenv("OTEL_SERVICE_NAME", "accessdoc"))[:256]
        self.flush_interval = _seconds(flush_interval if flush_interval is not None else
                                      float(os.getenv("OTEL_BSP_SCHEDULE_DELAY_MS", "1000")) / 1000)
        self.timeout = _seconds(timeout if timeout is not None else
                               float(os.getenv("OTEL_EXPORTER_OTLP_TIMEOUT_MS", "2000")) / 1000)
        if type(max_queue) is not int or not 1 <= max_queue <= _MAX_QUEUE:
            raise ValueError("max_queue must be within 1..2048")
        if type(max_batch) is not int or not 1 <= max_batch <= _MAX_BATCH:
            raise ValueError("max_batch must be within 1..256")
        self.max_batch = max_batch
        self._q = collections.deque(maxlen=max_queue)
        self._lock = threading.Lock()
        self._sender = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._closing = False
        self._finalize = threading.Event()
        # Sender serialization + applying before every dequeue bounds this
        # mailbox to one completion. Existing sender owns deferred accounting.
        self._pending = queue.SimpleQueue()
        self._discard_pending = False
        self._record_losses = itertools.count()
        self._record_loss_seen = 0
        self._session = PooledSession(_MAX_RESPONSE_BYTES) if self.enabled else None
        self._retirement = self._session.call_group() if self._session is not None else None
        if self._session is not None:
            self._session.proxy = None  # collector has no gateway proxy/credential routing
        self.exported = self.dropped = self.failed_batches = 0
        self.rejected_spans = self.failed_spans = self.shutdown_dropped = 0
        self.last_error = None
        self._inflight = 0
        self._thread = None
        if self.enabled:
            self._thread = threading.Thread(target=self._run, name="otlp-export", daemon=True)
            self._thread.start()

    @property
    def enabled(self):
        return bool(self.endpoint)

    def record(self, name, trace_id, span_id, parent_span_id, start_ns, end_ns,
               attrs=None, status_ok=True, kind=1):
        if not self.enabled:
            return False
        if type(kind) is not int or kind not in (1, 2, 3, 4, 5):
            raise ValueError("invalid OTLP span kind")
        rec = {
            "traceId": str(trace_id)[:32], "spanId": str(span_id)[:16],
            "parentSpanId": str(parent_span_id or "")[:16],
            "name": str(name)[:128], "kind": kind,
            "startTimeUnixNano": str(int(start_ns)), "endTimeUnixNano": str(int(end_ns)),
            "attributes": [_attr(k, v) for k, v in itertools.islice((attrs or {}).items(), 32)],
            "status": {"code": 1 if status_ok else 2},
        }
        if self._closing:
            return False
        if not self._lock.acquire(blocking=False):
            # CPython's C-level next(count) is one atomic primitive; a scalar
            # ledger, not one queued object per contended record. Applied under
            # _lock without imposing a blocking second mutex on record.
            next(self._record_losses)
            self._wake.set()
            return False
        try:
            self._apply_pending()
            if self._closing:
                return False
            if len(self._q) == self._q.maxlen:
                self.dropped += 1
            self._q.append(rec)
            if len(self._q) >= self.max_batch:
                self._wake.set()
        finally:
            self._lock.release()
        return True

    def _apply_pending(self):
        # Called only while holding _lock. No blocking/network operations here.
        marker = next(self._record_losses)
        self.dropped += marker - self._record_loss_seen
        self._record_loss_seen = marker + 1
        while True:
            try:
                accepted, rejected, failed, error = self._pending.get_nowait()
            except queue.Empty:
                break
            self.exported += accepted
            self.rejected_spans += rejected
            if error:
                self.failed_batches += 1
                self.failed_spans += failed
                self.last_error = error
            self._inflight = 0
        if self._discard_pending:
            lost = len(self._q)
            self._q.clear()
            self.dropped += lost
            self.shutdown_dropped += lost
            self._discard_pending = False

    def _drain(self, deadline):
        # Only sender may dequeue; every caller-side state wait is budgeted.
        if not _take(self._lock, deadline):
            return None
        try:
            self._apply_pending()
            batch = [self._q.popleft() for _ in range(min(self.max_batch, len(self._q)))]
            self._inflight = len(batch)
            return batch
        finally:
            self._lock.release()

    def _payload(self, batch):
        return {"resourceSpans": [{
            "resource": {"attributes": [_attr("service.name", self.service_name),
                                         _attr("service.version", os.getenv("ACCESSDOC_VERSION", "")[:128])]},
            "scopeSpans": [{"scope": {"name": "accessdoc"}, "spans": batch}],
        }]}

    def _send(self, batch, deadline):
        """Sender-owned single attempt; all work/cleanup uses the caller deadline."""
        error, accepted, rejected = None, 0, 0
        response = None
        try:
            deadline = min(deadline, time.monotonic() + self.timeout)
            payload = self._payload(batch)
            if len(json.dumps(payload, allow_nan=False).encode()) > _MAX_PAYLOAD_BYTES:
                error = "EXPORT_TOO_LARGE"
            elif time.monotonic() >= deadline:
                error = "TIMEOUT"
            else:
                response = self._session.post(
                    self.endpoint, headers=_headers(), json=payload,
                    timeout=(self.timeout, self.timeout), deadline=deadline,
                    call_group=self._retirement)
                if response.status_code != 200:  # OTLP success is 200, never redirects/202/204
                    error = "HTTP_STATUS"
                elif next((v.split(";", 1)[0].strip().lower() for k, v in response.headers.items()
                           if k.lower() == "content-type"), "") != "application/json":
                    error = "INVALID_RESPONSE"
                else:
                    raw = b"".join(response.iter_content(_MAX_RESPONSE_BYTES))
                    if len(raw) > _MAX_RESPONSE_BYTES or time.monotonic() >= deadline:
                        error = "TIMEOUT" if time.monotonic() >= deadline else "INVALID_RESPONSE"
                    else:
                        rejected = _rejections(raw, len(batch))
                        if time.monotonic() >= deadline:
                            rejected = 0
                            error = "TIMEOUT"
                        else:
                            accepted = len(batch) - rejected
                            if rejected:
                                error = "COLLECTOR_REJECTED"
        except requests.Timeout:
            error = "TIMEOUT"
        except (ValueError, UnicodeError, RecursionError):
            error = "INVALID_RESPONSE"
        except Exception:
            error = "TRANSPORT_ERROR"
        finally:
            if response is not None:
                response.close()  # bounded memory-only native facade, not blocking socket drain
            self._pending.put((accepted, rejected, len(batch)-accepted-rejected, error))
            if _take(self._lock, deadline):
                try:
                    self._apply_pending()
                finally:
                    self._lock.release()
            else:
                self._wake.set()
                # Result isn't fully accounted within the caller budget.
                return False
        return error is None

    @staticmethod
    def _work_cutoff(deadline):
        # Reserve once, across all batches, inside the original caller budget.
        remaining = max(0.0, deadline - time.monotonic())
        return deadline - min(0.05, remaining / 3)

    def _flush_until(self, deadline, baseline):
        if not _take(self._sender, deadline):
            return False  # do not cancel the background sender whose lock we lack
        work_deadline = self._work_cutoff(deadline)
        ok = True
        try:
            # A previous bounded failure may still own native cleanup. Empty
            # queues must not return false success or dequeue over that owner.
            if self._retirement is not None:
                ok = self._retirement.drain(work_deadline)
            while ok and time.monotonic() < work_deadline:
                batch = self._drain(work_deadline)
                if batch is None:
                    ok = False
                    break
                if not batch:
                    break
                if not self._send(batch, work_deadline):
                    ok = False
                    break  # single attempt; do not send pending batches on failure
            # Native handles outlive failed span accounting until actual call
            # retirement. No optimistic decrement or extra post-budget grace.
            cleaned = (self._retirement.drain(deadline)
                       if self._retirement is not None else True)
            if self._session is not None and self._session.cleanup_pending:
                cleaned = False
            if not _take(self._lock, deadline):
                return False
            try:
                self._apply_pending()
                return (ok and cleaned and not self._q and not self._inflight
                        and (self.failed_batches, self.dropped) == baseline)
            finally:
                self._lock.release()
        finally:
            self._sender.release()

    def flush(self, timeout=None):
        """True iff drained and all batches observed during THIS call were accepted.

        Sender/admission wait, all exports and cancellation share one absolute
        budget. False on partial rejection, any observed failed batch/drop, pending
        work, unfinished native cleanup or sender timeout. One work cutoff and
        native retirement reserve cover all batches; cleanup_pending remains
        visible after a bounded incomplete drain. No retries. True is not recovery/acknowledgement
        of losses before this call: consult cumulative failure/drop counters.
        """
        deadline = time.monotonic() + _budget(self.timeout if timeout is None else timeout)
        if not _take(self._lock, deadline):
            return False
        try:
            self._apply_pending()
            baseline = (self.failed_batches, self.dropped)
        finally:
            self._lock.release()
        return self._flush_until(deadline, baseline)

    def _run(self):
        try:
            while not self._stop.is_set():
                self._wake.wait(self.flush_interval)
                self._wake.clear()
                if self._stop.is_set():
                    break
                deadline = time.monotonic() + self.timeout
                if not _take(self._sender, deadline):
                    continue
                try:
                    if self._stop.is_set():
                        break
                    work_deadline = self._work_cutoff(deadline)
                    ready = (self._retirement.drain(work_deadline)
                             if self._retirement is not None else True)
                    batch = self._drain(work_deadline) if ready else None
                    if batch:
                        self._send(batch, work_deadline)
                    if self._retirement is not None:
                        self._retirement.drain(deadline)
                finally:
                    self._sender.release()
        finally:
            # This existing owner must not exit before the bounded shutdown
            # caller has published final accounting/disposal intent. No detached
            # cleanup thread, and no extra grace in the caller's return path.
            self._finalize.wait()
            with self._sender, self._lock:
                self._apply_pending()
                self._discard_pending = True
                self._apply_pending()
            if self._session is not None:
                self._session.close(deadline=time.monotonic())

    def shutdown(self, timeout=2.0):
        """Stop admission, drain once, cancel/close owner within ONE shared budget.

        Returns flush-and-cleanup success. Expired cleanup is still scheduled on
        the owned native loop; it never gets an extra caller-blocking grace.
        Remaining queued spans are counted as shutdown drops, never transmitted.
        """
        deadline = time.monotonic() + _budget(timeout)
        # Immediate admission intent; record rechecks inside the queue mutex.
        self._closing = True
        self._stop.set()
        self._wake.set()
        ok = False
        if _take(self._lock, deadline):
            try:
                self._apply_pending()
                baseline = (self.failed_batches, self.dropped)
            finally:
                self._lock.release()
            ok = self._flush_until(deadline, baseline)
        self._discard_pending = True
        if _take(self._lock, deadline):
            try:
                self._apply_pending()
            finally:
                self._lock.release()
        else:
            ok = False
        self._finalize.set()
        cleaned = self._session.close(deadline=deadline) if self._session is not None else True
        if self._thread is not None and threading.current_thread() is not self._thread:
            _join(self._thread, deadline)
            cleaned = not self._thread.is_alive() and cleaned
        return ok and cleaned

    def stats(self):
        with self._lock:
            self._apply_pending()
            return {"enabled": self.enabled, "exported": self.exported, "dropped": self.dropped,
                    "failed_batches": self.failed_batches, "queued": len(self._q),
                    "rejected_spans": self.rejected_spans, "failed_spans": self.failed_spans,
                    "shutdown_dropped": self.shutdown_dropped, "inflight": self._inflight,
                    "cleanup_pending": max(self._retirement.pending if self._retirement is not None else 0,
                                           int(bool(self._session and self._session.cleanup_pending))),
                    "closing": self._closing, "last_error": self.last_error,
                    "bootstrap_dropped": _bootstrap_loss_snapshot()}


_default = None
_default_lock = threading.Lock()
# Separate process-wide losses where no exporter existed to own the span yet.
# CPython count uses atomic C-level next; snapshot markers are accounted below.
_bootstrap_losses = itertools.count()
_bootstrap_snapshot_lock = threading.Lock()
_bootstrap_marker = -1
_bootstrap_total = 0


def _bootstrap_loss_snapshot():
    # count has no public peek operation. Account a snapshot marker exactly as
    # the exporter-owned record loss ledger does; never use pickle internals.
    # A competing observer receives the last completed monotonic snapshot.
    global _bootstrap_marker, _bootstrap_total
    if not _bootstrap_snapshot_lock.acquire(blocking=False):
        return _bootstrap_total
    try:
        marker = next(_bootstrap_losses)
        _bootstrap_total += marker - _bootstrap_marker - 1
        _bootstrap_marker = marker
        return _bootstrap_total
    finally:
        _bootstrap_snapshot_lock.release()


def get_exporter(*, deadline=None):
    """Fast-path existing exporter; bootstrap contention never blocks telemetry.

    A supplied deadline budgets bootstrap mutex wait. With no deadline (the
    request-path telemetry API), a busy bootstrap fails immediately and is
    visible separately as cumulative process-wide bootstrap_dropped.
    """
    global _default
    existing = _default
    if existing is not None:
        return existing
    acquired = (_default_lock.acquire(blocking=False) if deadline is None else
                _take(_default_lock, deadline))
    if not acquired:
        next(_bootstrap_losses)
        raise requests.Timeout("OTLP exporter bootstrap busy")
    try:
        if _default is None:
            _default = OTLPExporter()
            if _default.enabled:
                atexit.register(_default.shutdown, 1.0)
        return _default
    finally:
        _default_lock.release()


def reset_exporter(exporter=None):
    """Swap the process-wide exporter (tests / config reload)."""
    global _default
    with _default_lock:
        old, _default = _default, exporter
    if old is not None:
        old.shutdown(0.5)
    return _default
