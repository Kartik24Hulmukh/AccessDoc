"""Distributed tracing + structured JSON logging (stdlib-first, OpenTelemetry-optional).

* W3C Trace Context (``traceparent``) parse / mint / propagate on every hop
  (client -> hosted or serverless adapter -> Melious gateway).
* When ``opentelemetry-api`` is installed spans are exported through the
  configured OTel tracer; otherwise a zero-dependency span with the same call
  shape emits a structured ``span`` log line. Production can flip tracing on by
  installing the SDK + an exporter - no code change needed.
* ``log_event`` writes exactly one JSON object per line carrying ``trace_id`` /
  ``span_id`` so the gateway, adapters and load scripts share a single schema.
"""
from __future__ import annotations

import contextlib
import json
import re
import secrets
import threading
import time

_TP = re.compile(r"^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")
_local = threading.local()
try:  # optional dependency - never required at runtime
    from opentelemetry import trace as _otel_trace  # type: ignore
    _tracer = _otel_trace.get_tracer("accessdoc")
except Exception:  # pragma: no cover - exercised when SDK absent
    _otel_trace = None
    _tracer = None


def parse_traceparent(value):
    """Return (trace_id, parent_span_id, flags) for a valid W3C header, else None."""
    m = _TP.match(str(value or "").strip().lower()[:55])
    if not m or m.group(1) == "ff":
        return None
    trace_id, span_id = m.group(2), m.group(3)
    if trace_id == "0" * 32 or span_id == "0" * 16:
        return None
    return trace_id, span_id, m.group(4)


def new_trace_id():
    return secrets.token_hex(16)


def new_span_id():
    return secrets.token_hex(8)


def start_trace(traceparent=None, **attrs):
    """Adopt an inbound context (or mint a root) and bind it to this thread."""
    parsed = parse_traceparent(traceparent)
    ctx = {"trace_id": parsed[0] if parsed else new_trace_id(),
           "span_id": new_span_id(),
           "parent_span_id": parsed[1] if parsed else None}
    ctx.update(attrs)
    _local.ctx = ctx
    return ctx


def current():
    ctx = getattr(_local, "ctx", None)
    return ctx if ctx else start_trace()


def clear():
    _local.ctx = None


def traceparent_header(ctx=None):
    ctx = ctx or current()
    return "00-%s-%s-01" % (ctx["trace_id"], ctx["span_id"])


@contextlib.contextmanager
def span(name, **attrs):
    """Child span bound to the current trace; OTel-backed when available."""
    parent = current()
    child = dict(parent, span_id=new_span_id(), parent_span_id=parent["span_id"])
    prev = getattr(_local, "ctx", None)
    _local.ctx = child
    t0 = time.monotonic()
    start_ns = time.time_ns()
    ok = True
    otel_cm = _tracer.start_as_current_span(name) if _tracer is not None else contextlib.nullcontext()
    try:
        with otel_cm as s:
            if s is not None:
                for k, v in attrs.items():
                    try:
                        s.set_attribute(k, v)
                    except Exception:
                        pass
            try:
                yield child
            except BaseException:
                ok = False
                raise
    finally:
        _local.ctx = prev
        log_event("span", name=name, span_id=child["span_id"],
                  parent_span_id=parent["span_id"],
                  duration_ms=round((time.monotonic() - t0) * 1000, 2), **attrs)
        _export_span(name, child, parent, start_ns, time.time_ns(), attrs, ok)


def _export_span(name, child, parent, start_ns, end_ns, attrs, ok):
    """Ship the finished span to the OTLP/HTTP exporter (never raises, never blocks)."""
    try:
        from . import otlp_export
        otlp_export.get_exporter().record(name, child["trace_id"], child["span_id"],
                                          parent["span_id"], start_ns, end_ns,
                                          attrs, status_ok=ok)
    except Exception:
        pass


def log_event(event, level="info", **fields):
    """Emit one structured JSON log line (never raises)."""
    ctx = current()
    rec = {"ts": time.time(), "level": level, "event": event,
           "trace_id": ctx["trace_id"], "span_id": ctx["span_id"]}
    rec.update(fields)
    try:
        print(json.dumps(rec, separators=(",", ":"), default=str), flush=True)
    except Exception:
        pass
    return rec


def otel_enabled():
    return _tracer is not None


def record_server_span(ctx, method, route, status, start_ns, end_ns):
    """Emit the SERVER span for one HTTP request (parent = inbound traceparent)."""
    try:
        from . import otlp_export
        return otlp_export.get_exporter().record(
            "%s %s" % (method, route), ctx["trace_id"], ctx["span_id"], ctx.get("parent_span_id"),
            start_ns, end_ns,
            {"http.request.method": str(method), "http.route": str(route),
             "http.response.status_code": int(status), "request_id": ctx.get("request_id", "")},
            status_ok=int(status) < 500)
    except Exception:
        return False


def export_status():
    """Operator-facing tracing status for /readyz."""
    try:
        from . import otlp_export
        st = otlp_export.get_exporter().stats()
    except Exception:
        st = {"enabled": False}
    st["sdk"] = otel_enabled()
    return st
