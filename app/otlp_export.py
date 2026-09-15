"""Zero-dependency OTLP/HTTP (JSON) span exporter.

Closes the launch gate "real OpenTelemetry export needs an SDK install":
when ``OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`` (or ``OTEL_EXPORTER_OTLP_ENDPOINT``)
is set, finished spans are batched and POSTed as OTLP/JSON to the collector.

Design rules (first principles, hostile-environment safe):
* Never blocks a request path: ``record`` is an O(1) enqueue onto a bounded
  deque; on overflow the oldest span is dropped and counted (``dropped``).
* Single daemon flusher thread, batch size + flush interval bounded, connection
  reuse via ``http.client`` keep-alive, hard per-export deadline.
* Collector failures are counted, never raised, and never retried in a loop
  that could pile up memory (the batch is discarded after one failed attempt).
* Disabled entirely when no endpoint is configured; ``stats()`` is exposed via
  ``/readyz`` so operators can see export health without log scraping.
"""
from __future__ import annotations

import atexit
import collections
import http.client
import json
import os
import threading
import time
import urllib.parse

_MAX_QUEUE = 2048
_MAX_BATCH = 256
_MAX_ATTR_LEN = 256


def _endpoint():
    ep = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "").strip()
    if ep:
        return ep
    base = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    return base.rstrip("/") + "/v1/traces" if base else ""


def _headers():
    out = {"Content-Type": "application/json"}
    raw = os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "")
    for part in raw.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            k = k.strip()[:128]
            if k:
                out[k] = urllib.parse.unquote(v.strip())[:1024]
    return out


def _attr(k, v):
    if isinstance(v, bool):
        return {"key": k, "value": {"boolValue": v}}
    if isinstance(v, int):
        return {"key": k, "value": {"intValue": str(v)}}
    if isinstance(v, float):
        return {"key": k, "value": {"doubleValue": v}}
    return {"key": k, "value": {"stringValue": str(v)[:_MAX_ATTR_LEN]}}


class OTLPExporter:
    def __init__(self, endpoint=None, service_name=None, flush_interval=None,
                 timeout=None, max_queue=_MAX_QUEUE, max_batch=_MAX_BATCH):
        self.endpoint = endpoint if endpoint is not None else _endpoint()
        self.service_name = service_name or os.getenv("OTEL_SERVICE_NAME", "accessdoc")
        self.flush_interval = float(flush_interval or os.getenv("OTEL_BSP_SCHEDULE_DELAY_MS", "1000")) / (1.0 if flush_interval else 1000.0)
        self.timeout = float(timeout or os.getenv("OTEL_EXPORTER_OTLP_TIMEOUT_MS", "2000")) / (1.0 if timeout else 1000.0)
        self.max_batch = max_batch
        self._q = collections.deque(maxlen=max_queue)
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._conn = None
        self.exported = 0
        self.dropped = 0
        self.failed_batches = 0
        self.last_error = None
        self._thread = None
        if self.enabled:
            self._thread = threading.Thread(target=self._run, name="otlp-export", daemon=True)
            self._thread.start()

    @property
    def enabled(self):
        return bool(self.endpoint)

    def record(self, name, trace_id, span_id, parent_span_id, start_ns, end_ns, attrs=None, status_ok=True):
        if not self.enabled:
            return False
        rec = {
            "traceId": trace_id, "spanId": span_id,
            "parentSpanId": parent_span_id or "",
            "name": str(name)[:128], "kind": 1,
            "startTimeUnixNano": str(int(start_ns)), "endTimeUnixNano": str(int(end_ns)),
            "attributes": [_attr(k, v) for k, v in (attrs or {}).items()][:32],
            "status": {"code": 1 if status_ok else 2},
        }
        with self._lock:
            if len(self._q) == self._q.maxlen:
                self.dropped += 1
            self._q.append(rec)
            if len(self._q) >= self.max_batch:
                self._wake.set()
        return True

    def _drain(self):
        with self._lock:
            batch = [self._q.popleft() for _ in range(min(self.max_batch, len(self._q)))]
        return batch

    def _payload(self, batch):
        return json.dumps({"resourceSpans": [{
            "resource": {"attributes": [_attr("service.name", self.service_name),
                                         _attr("service.version", os.getenv("ACCESSDOC_VERSION", ""))]},
            "scopeSpans": [{"scope": {"name": "accessdoc"}, "spans": batch}],
        }]}, separators=(",", ":"), default=str).encode("utf-8")

    def _connection(self):
        if self._conn is not None:
            return self._conn
        u = urllib.parse.urlsplit(self.endpoint)
        cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
        self._conn = cls(u.hostname, u.port, timeout=self.timeout)
        return self._conn

    def _send(self, batch):
        u = urllib.parse.urlsplit(self.endpoint)
        path = (u.path or "/v1/traces") + (("?" + u.query) if u.query else "")
        body = self._payload(batch)
        deadline = time.monotonic() + self.timeout
        try:
            conn = self._connection()
            conn.request("POST", path, body=body, headers=_headers())
            resp = conn.getresponse()
            resp.read(65536)
            if time.monotonic() > deadline or resp.status >= 400:
                raise OSError("otlp export status %s" % resp.status)
            self.exported += len(batch)
            return True
        except Exception as exc:  # collector down: count, drop batch, reset conn
            self.failed_batches += 1
            self.last_error = type(exc).__name__
            try:
                if self._conn is not None:
                    self._conn.close()
            finally:
                self._conn = None
            return False

    def flush(self, timeout=None):
        """Synchronously export everything queued (used by tests / shutdown)."""
        end = time.monotonic() + (timeout if timeout is not None else self.timeout)
        while self._q and time.monotonic() < end:
            batch = self._drain()
            if not batch:
                break
            self._send(batch)
        return not self._q

    def _run(self):
        while not self._stop.is_set():
            self._wake.wait(self.flush_interval)
            self._wake.clear()
            batch = self._drain()
            if batch:
                self._send(batch)

    def shutdown(self, timeout=2.0):
        self._stop.set()
        self._wake.set()
        self.flush(timeout)
        if self._thread is not None:
            self._thread.join(timeout)
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def stats(self):
        return {"enabled": self.enabled, "exported": self.exported, "dropped": self.dropped,
                "failed_batches": self.failed_batches, "queued": len(self._q),
                "last_error": self.last_error}


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
