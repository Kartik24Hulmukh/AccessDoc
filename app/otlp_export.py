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
import threading
import time
import urllib.parse

import requests
from .gateway_transport import PooledSession

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
        self._session = PooledSession(_MAX_RESPONSE_BYTES) if self.enabled else None
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
        with self._lock:
            if self._closing:
                return False
            if len(self._q) == self._q.maxlen:
                self.dropped += 1
            self._q.append(rec)
            if len(self._q) >= self.max_batch:
                self._wake.set()
        return True

    def _drain(self):
        # Only the sender owner may dequeue: includes daemon, flush and shutdown.
        with self._lock:
            batch = [self._q.popleft() for _ in range(min(self.max_batch, len(self._q)))]
            self._inflight = len(batch)
        return batch

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
                    timeout=(self.timeout, self.timeout), deadline=deadline)
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
            with self._lock:
                self.exported += accepted
                self.rejected_spans += rejected
                if error:
                    self.failed_batches += 1
                    self.failed_spans += len(batch) - accepted - rejected
                    self.last_error = error
                self._inflight = 0
        return error is None

    def _flush_until(self, deadline, baseline):
        if not self._sender.acquire(timeout=max(0.0, deadline - time.monotonic())):
            return False
        ok = True
        try:
            while time.monotonic() < deadline:
                batch = self._drain()
                if not batch:
                    break
                if not self._send(batch, deadline):
                    ok = False
                    break  # never spin through pending batches after a failed attempt
            with self._lock:
                return ok and not self._q and not self._inflight and (self.failed_batches, self.dropped) == baseline
        finally:
            self._sender.release()

    def flush(self, timeout=None):
        """True iff drained and all batches observed during THIS call were accepted.

        Sender/admission wait, all exports and cancellation share one absolute
        budget. False on partial rejection, any observed failed batch/drop, pending
        work or sender timeout. No retries. True is not recovery/acknowledgement
        of losses before this call: consult cumulative failure/drop counters.
        """
        deadline = time.monotonic() + _budget(self.timeout if timeout is None else timeout)
        with self._lock:
            baseline = (self.failed_batches, self.dropped)
        return self._flush_until(deadline, baseline)

    def _run(self):
        while not self._stop.is_set():
            self._wake.wait(self.flush_interval)
            self._wake.clear()
            if self._stop.is_set():
                break
            deadline = time.monotonic() + self.timeout
            if not self._sender.acquire(timeout=max(0.0, deadline - time.monotonic())):
                continue
            try:
                if self._stop.is_set():
                    break
                batch = self._drain()
                if batch:
                    self._send(batch, deadline)
            finally:
                self._sender.release()

    def shutdown(self, timeout=2.0):
        """Stop admission, drain once, cancel/close owner within ONE shared budget.

        Returns flush-and-cleanup success. Expired cleanup is still scheduled on
        the owned native loop; it never gets an extra caller-blocking grace.
        Remaining queued spans are counted as shutdown drops, never transmitted.
        """
        deadline = time.monotonic() + _budget(timeout)
        with self._lock:
            self._closing = True
            baseline = (self.failed_batches, self.dropped)
        self._stop.set()
        self._wake.set()
        ok = self._flush_until(deadline, baseline)
        with self._lock:
            lost = len(self._q)
            self._q.clear()
            self.dropped += lost
            self.shutdown_dropped += lost
        cleaned = self._session.close(deadline=deadline) if self._session is not None else True
        if self._thread is not None and threading.current_thread() is not self._thread:
            self._thread.join(max(0.0, deadline - time.monotonic()))
            cleaned = not self._thread.is_alive() and cleaned
        return ok and cleaned

    def stats(self):
        with self._lock:
            return {"enabled": self.enabled, "exported": self.exported, "dropped": self.dropped,
                    "failed_batches": self.failed_batches, "queued": len(self._q),
                    "rejected_spans": self.rejected_spans, "failed_spans": self.failed_spans,
                    "shutdown_dropped": self.shutdown_dropped, "inflight": self._inflight,
                    "closing": self._closing, "last_error": self.last_error}


_default = None
_default_lock = threading.Lock()


def get_exporter():
    global _default
    with _default_lock:
        if _default is None:
            _default = OTLPExporter()
            if _default.enabled:
                atexit.register(_default.shutdown, 1.0)
        return _default


def reset_exporter(exporter=None):
    """Swap the process-wide exporter (tests / config reload)."""
    global _default
    with _default_lock:
        old, _default = _default, exporter
    if old is not None:
        old.shutdown(0.5)
    return _default
