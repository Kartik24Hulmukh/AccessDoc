"""Vercel serverless handler for AccessDoc bundle generation.

This is a bounded ReportLab demo API. It accepts axe-core JSON, produces a
deterministic evidence ZIP, and returns it. It does NOT expose pdf_engine=
weasyprint or receipt_history from the public API — those are internal/CLI-only
paths. All inputs are size-limited before expensive work begins.

Security headers, strict content-type/length validation, and bounded reads
ensure hostile payloads cannot exhaust resources or leak internal errors.
"""
# Bounded serverless endpoint for ReportLab PDF & OpenACR evidence generation.
import json
import sys
import os
import uuid
import platform
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from http.server import BaseHTTPRequestHandler
from app.service import build_artifacts
from app.bundle import build_bundle
from app.models import VERSION
from app.http_policy import auth_error, auth_required, public_body
from app import telemetry

READ_CHUNK_BYTES = 64 * 1024
from app.limits import (
    LimitExceeded,
    limits_summary,
    MAX_HTTP_BODY_BYTES,
    MAX_VIOLATIONS,
    MAX_TOTAL_NODES,
    MAX_NODES_PER_VIOLATION,
    MAX_STRING_CHARS,
    MAX_MANUAL_FINDINGS,
)

ADAPTER_VERSION = VERSION

_STARTED_MONO = time.monotonic()

_METRICS_LOCK = threading.Lock()
_METRICS = {
    "requests_total": 0,
    "errors_total": 0,
    "reports_total": 0,
    "overload_rejections_total": 0,
    "client_disconnects_total": 0,
}


def _bump(name, n=1):
    """Bounded per-process counter increment backing the hosted /metrics surface."""
    with _METRICS_LOCK:
        _METRICS[name] = _METRICS.get(name, 0) + n


def _metrics_text():
    """Prometheus exposition mirroring app/main.py /metrics plus RAM floor/ceiling."""
    lines = []
    with _METRICS_LOCK:
        snapshot = dict(_METRICS)
    for key in ("requests_total", "errors_total", "reports_total",
                "overload_rejections_total", "client_disconnects_total"):
        lines.append("accessdoc_%s %d" % (key, snapshot.get(key, 0)))
    models, chain = {}, []
    try:
        from app import remediate as remediation
        snap = remediation.health() or {}
        models = snap.get("models", {}) or {}
        chain = list(snap.get("chain", []) or [])
    except Exception:
        models, chain = {}, []
    if not chain:
        try:
            from app.gateway import CANONICAL_CHAIN
            chain = list(CANONICAL_CHAIN)
        except Exception:
            chain = []
    for model in sorted(set(chain) | set(models)):
        state = 1 if (models.get(model) or {}).get("state") == "open" else 0
        lines.append('accessdoc_gateway_circuit_open{model="%s"} %d' % (model, state))
    stats = _process_stats()
    for key in ("rss_kib", "max_rss_kib", "threads"):
        if key in stats:
            lines.append("accessdoc_process_%s %d" % (key, int(stats[key])))
    lines.append("accessdoc_runtime_uptime_seconds %s" % round(time.monotonic() - _STARTED_MONO, 1))
    return "\n".join(lines) + "\n"


def _process_stats():
    """Best-effort process memory snapshot for /healthz capacity claims.

    Launch telemetry gap (Sessions 8/9/10): no RAM floor/ceiling was ever
    exposed, so capacity claims were unverifiable. ru_maxrss is monotonic
    (peak since process start); /proc/self/status VmRSS gives the live
    resident set on Linux. Everything is bounded integers, no PII.
    """
    out = {}
    try:
        import resource
        out["max_rss_kib"] = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except Exception:
        pass
    try:
        with open("/proc/self/status", "rb") as fh:
            for line in fh:
                if line.startswith(b"VmRSS:"):
                    out["rss_kib"] = int(line.split()[1])
                    break
    except Exception:
        pass
    try:
        out["threads"] = int(threading.active_count())
    except Exception:
        pass
    return out

# The self-hosted adapter (app/main.py) serves /api/generate with a download
# token flow; the stateless serverless adapter cannot store artifacts, so it
# answers those aliases with an actionable hint instead of a bare 404.
_GENERATE_ALIASES = ("/api/generate", "/api/v1/generate")
_GENERATE_HINT = (
    "Not found. The serverless adapter does not expose /api/generate; POST the same JSON body to /api/bundle to receive the evidence ZIP directly (see docs/API_V1.md)"
)
# Per-process only: serverless replicas require an external global quota.
GENERATION_CAPACITY = threading.BoundedSemaphore(max(1, int(os.getenv("MAX_CONCURRENT_REQUESTS", "2"))))
# Remediation calls are slow model round-trips; they must never starve PDF
# generation, so they admit from their own bounded pool.
REMEDIATION_CAPACITY = threading.BoundedSemaphore(max(1, int(os.getenv("MAX_CONCURRENT_REMEDIATIONS", "4"))))
_REMEDIATE_PATHS = ("/api/remediate", "/api/v1/remediate")
GENERATION_QUEUE_TIMEOUT = 0.05  # bounded semaphore handoff, not a retry sleep
REMEDIATION_QUEUE_TIMEOUT = max(0.0, float(os.getenv("REMEDIATION_QUEUE_TIMEOUT_SECONDS", "10")))

# Only these keys from the request body are forwarded to build_artifacts.
# pdf_engine and receipt_history are deliberately excluded from the public API.
_PASSTHROUGH = (
    "scanner_input", "client_name", "agency_name", "audit_date",
    "manual_findings", "enrich", "include_sarif", "include_vpat",
    "include_eaa", "prior_receipt",
)

# Security headers applied to every response.
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
    # Prevent error pages from being rendered as HTML by browsers.
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}

# ---------------------------------------------------------------------- #
# Hosted UI + developer docs. Vercel routes every path to this handler, so the
# static report builder in public/ must be served from here or it is dark in
# production. Strict allowlist: no directory walking, no path joins from input.
# ---------------------------------------------------------------------- #
_PUBLIC_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public")
_PAGE_CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
             "connect-src 'self'; font-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
_STATIC_FILES = {
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/docs": ("docs.html", "text/html; charset=utf-8"),
    "/docs/index.html": ("docs.html", "text/html; charset=utf-8"),
    "/openapi.json": ("openapi.json", "application/json; charset=utf-8"),
    "/static/app.css": ("static/app.css", "text/css; charset=utf-8"),
    "/static/app.js": ("static/app.js", "text/javascript; charset=utf-8"),
    "/static/report.css": ("static/report.css", "text/css; charset=utf-8"),
    "/sample/axe-sample.json": ("sample/axe-sample.json", "application/json; charset=utf-8"),
}
_STATIC_MAX_BYTES = 512 * 1024


def _load_static(path):
    """Return (bytes, content_type) for an allowlisted asset, or None."""
    entry = _STATIC_FILES.get(path)
    if not entry:
        return None
    rel, ctype = entry
    full = os.path.join(_PUBLIC_ROOT, *rel.split("/"))
    try:
        if os.path.getsize(full) <= _STATIC_MAX_BYTES:
            with open(full, "rb") as fh:
                return fh.read(_STATIC_MAX_BYTES), ctype
    except OSError:
        pass
    # Vercel does not bundle public/ into the Python function; fall back to the
    # generated, allowlisted copy that ships inside api/ (scripts/embed_public_assets.py).
    try:
        from api import public_assets
    except Exception:
        try:
            import public_assets  # api/ is the CWD-less lambda root on some runtimes
        except Exception:
            return None
    data = public_assets.load(rel)
    if data is None or len(data) > _STATIC_MAX_BYTES:
        return None
    return data, ctype


def _wants_html(accept):
    """Browsers ask for text/html first; probes, curl and SDKs do not."""
    accept = (accept or "").lower()
    if "text/html" not in accept:
        return False
    if "application/json" in accept and accept.find("application/json") < accept.find("text/html"):
        return False
    return True


class handler(BaseHTTPRequestHandler):
    """Bounded HTTP handler for AccessDoc bundle generation.

    All error responses are JSON with a generic message and a request ID.
    Raw exception text is never returned to the client.
    """

    # Never advertise the Python/BaseHTTP version on stdlib-generated errors.
    server_version = f"AccessDoc/{VERSION}"
    sys_version = ""

    # Suppress default stderr logging (Vercel captures stdout/stderr separately).
    def setup(self):
        super().setup()
        self.connection.settimeout(float(os.getenv("SOCKET_TIMEOUT_SECONDS", "15")))

    def log_message(self, fmt, *args):
        pass

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _send_json(self, status, payload, extra_headers=None):
        """Send a JSON response with security headers. Never renders HTML."""
        body = json.dumps(payload).encode("utf-8")
        self._status = status
        _bump("requests_total")
        if status >= 400:
            _bump("errors_total")
        self.send_response(status)
        if hasattr(self, "request_id"):
            self.send_header("X-Request-ID", self.request_id)
        self.send_header("traceparent", telemetry.traceparent_header(self._trace()))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for k, v in _SECURITY_HEADERS.items():
            self.send_header(k, v)
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            _bump("client_disconnects_total")

    def _trace(self):
        """Adopt the inbound W3C traceparent (or mint a root span) once per request."""
        ctx = getattr(self, "_trace_ctx", None)
        if not ctx:
            inbound = self.headers.get("traceparent") if getattr(self, "headers", None) else None
            ctx = telemetry.start_trace(inbound, request_id=getattr(self, "request_id", None))
            self._trace_ctx = ctx
        return ctx

    def send_error(self, code, message=None, explain=None):
        """Stdlib parse failures (400/414/431/501) must honour the JSON contract.

        BaseHTTPRequestHandler.send_error renders an HTML page that reflects
        the client's request line, carries no security headers and no
        X-Request-ID. Route it through the bounded JSON error path instead and
        never echo client-supplied text.
        """
        self.close_connection = True
        if not hasattr(self, "request_id"):
            self.request_id = uuid.uuid4().hex[:12]
        self._trace_ctx = None
        self._trace()
        short = self.responses.get(code, ("Request rejected",))[0]
        self._send_json(code, {"error": short, "request_id": self.request_id},
                        {"Connection": "close"})

    def _error(self, status, message, request_id=None):
        """Send a bounded error response. No exception detail leakage."""
        if request_id is None:
            request_id = uuid.uuid4().hex[:12]
        self._send_json(status, {
            "error": message,
            "request_id": request_id,
        })

    def _read_bounded_body(self):
        """Read the request body with strict Content-Length and size limits.

        Returns (raw_bytes, error_status, error_message).
        If error_status is not None, the caller should send the error response.
        """
        lengths = self.headers.get_all("Content-Length") or []
        if len(lengths) > 1 or self.headers.get("Transfer-Encoding") or self.headers.get("Content-Encoding"):
            return None, 400, "Ambiguous or unsupported request framing"
        cl_header = self.headers.get("Content-Length")

        # Content-Length is required for POST.
        if cl_header is None:
            return None, 411, "Content-Length required"

        # Must be a valid non-negative integer.
        try:
            length = int(cl_header)
        except (ValueError, TypeError):
            return None, 400, "Malformed Content-Length"

        if length < 0:
            return None, 400, "Negative Content-Length"

        if length > MAX_HTTP_BODY_BYTES:
            return None, 413, "Request body too large"

        # Read exactly the declared number of bytes.
        # Even if Content-Length is absent we cap reads at MAX_HTTP_BODY_BYTES,
        # but we already required it above for POST.
        # Chunked streaming read (64 KiB slices): no single oversized allocation,
        # early abort on client disconnect.
        buf = bytearray()
        remaining = length
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, READ_CHUNK_BYTES))
            if not chunk:
                break
            buf += chunk
            remaining -= len(chunk)
        raw = bytes(buf)
        if len(raw) < length:
            # Client disconnected early; treat as malformed.
            return None, 400, "Request body shorter than Content-Length"

        return raw, None, None

    def _validate_axe_structure(self, scanner_input):
        """Validate axe-core JSON structure before expensive processing.

        Returns (ok, error_status, error_message).
        """
        import json as _json

        # scanner_input may be a string or a dict (already parsed).
        if isinstance(scanner_input, str):
            try:
                data = _json.loads(scanner_input)
            except (_json.JSONDecodeError, RecursionError):
                return False, 400, "Malformed JSON in scanner_input"
        elif isinstance(scanner_input, dict):
            data = scanner_input
        else:
            return False, 422, "scanner_input must be a JSON object or string"

        if not isinstance(data, dict):
            return False, 422, "axe-core input must be a JSON object"

        if "violations" not in data:
            return False, 422, "scanner_input missing 'violations' array"
        violations_raw = data["violations"]
        if violations_raw is None:
            violations_raw = []  # explicit null == empty (shared parser contract)
        if not isinstance(violations_raw, list):
            return False, 422, "'violations' must be a list"

        if len(violations_raw) > MAX_VIOLATIONS:
            return False, 413, f"Too many violations (limit {MAX_VIOLATIONS})"

        total_nodes = 0
        for v in violations_raw:
            if not isinstance(v, dict):
                continue
            nodes = v.get("nodes")
            if nodes is not None:
                if not isinstance(nodes, list):
                    return False, 422, "'nodes' must be a list"
                node_count = len(nodes)
                if node_count > MAX_NODES_PER_VIOLATION:
                    return False, 413, (
                        f"Too many nodes in a single violation "
                        f"(limit {MAX_NODES_PER_VIOLATION})"
                    )
                total_nodes += node_count
                if total_nodes > MAX_TOTAL_NODES:
                    return False, 413, (
                        f"Too many total nodes (limit {MAX_TOTAL_NODES})"
                    )

            # Bound string fields in each violation.
            for field in ("id", "impact", "description", "helpUrl"):
                val = v.get(field)
                if isinstance(val, str) and len(val) > MAX_STRING_CHARS:
                    return False, 413, (
                        f"Violation field '{field}' exceeds "
                        f"{MAX_STRING_CHARS} characters"
                    )

        # Shared validation must not inherit the CLI-only oversize opt-out.
        from app.parser import parse_axe_json
        try:
            parse_axe_json(data, allow_oversized=False)
        except LimitExceeded:
            return False, 413, "Scanner input exceeds resource limits"
        except (ValueError, RecursionError):
            return False, 422, "Invalid axe-core data"
        return True, None, None

    # ------------------------------------------------------------------ #
    # HTTP methods
    # ------------------------------------------------------------------ #

    def _gateway_snapshot(self):
        """Circuit-breaker / configuration view for readiness probes."""
        snap = {"configured": bool(os.getenv("MELIOUS_API_KEY"))}
        try:
            from app import remediate as remediation
            snap.update(remediation.health())
        except Exception:
            snap["available"] = False
        return snap

    def _send_static(self, path, head_only=False):
        """Serve an allowlisted public asset with page-scoped CSP. Returns True if served."""
        loaded = _load_static(path)
        if loaded is None:
            return False
        body, ctype = loaded
        _bump("requests_total")
        self._status = 200
        self.send_response(200)
        self.send_header("X-Request-ID", self.request_id)
        self.send_header("traceparent", telemetry.traceparent_header(self._trace()))
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Vary", "Accept")
        for k, v in _SECURITY_HEADERS.items():
            if k == "Content-Security-Policy":
                v = _PAGE_CSP
            self.send_header(k, v)
        self.end_headers()
        if not head_only:
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                _bump("client_disconnects_total")
        return True

    def _send_text_metrics(self):
        """Prometheus exposition format on the hosted adapter; HEAD-safe."""
        body = _metrics_text().encode("utf-8")
        _bump("requests_total")
        self._status = 200
        self.send_response(200)
        self.send_header("X-Request-ID", self.request_id)
        self.send_header("traceparent", telemetry.traceparent_header(self._trace()))
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for k, v in _SECURITY_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                _bump("client_disconnects_total")
        return True

    def do_GET(self):
        """Hosted UI on '/' (browsers) and '/index.html'; JSON health on '/' (API clients),
        '/readyz', '/healthz'; ceilings on '/limits'; docs on '/docs' + '/openapi.json'."""
        self.request_id = uuid.uuid4().hex[:12]
        self._trace_ctx = None
        commit_sha = os.environ.get("VERCEL_GIT_COMMIT_SHA", "unknown")
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path == "/" and _wants_html(self.headers.get("Accept")) and self._send_static("/index.html"):
            return
        if path in _STATIC_FILES and self._send_static(path):
            return
        if path in ("/", "/readyz", "/healthz", "/health"):
            self._send_json(200, {
                "service": "AccessDoc",
                "adapter_version": ADAPTER_VERSION,
                "status": "ok",
                "commit": commit_sha,
                "api_note": "Bounded ReportLab demo API. See docs for limitations.",
                "endpoints": ["/api/bundle", "/api/remediate", "/limits", "/docs", "/openapi.json"],
                "ui": "/index.html",
                "gateway": self._gateway_snapshot(),
                "process": _process_stats(),
                "runtime": {"python": platform.python_version(), "uptime_seconds": round(time.monotonic() - _STARTED_MONO, 1)},
            })
            return
        if path == "/metrics":
            self._send_text_metrics()
            return
        if path == "/limits":
            limits = dict(limits_summary())
            limits.update({
                "api_key_required": auth_required(),
                "rate_limit_per_minute": None,
                "max_concurrent_requests_per_process": int(os.getenv("MAX_CONCURRENT_REQUESTS", "2")),
                "note": "Per-process admission only; provider/WAF quotas are still required.",
            })
            self._send_json(200, limits)
            return
        if path == "/api/bundle":
            self._send_json(200, {
                "service": "AccessDoc",
                "adapter_version": ADAPTER_VERSION,
                "endpoint": "/api/bundle",
                "method": "POST",
                "commit": commit_sha,
                "description": "Send POST with axe-core JSON in scanner_input to generate an evidence ZIP.",
                "docs": "/docs",
                "openapi": "/openapi.json",
            })
            return
        if path in _REMEDIATE_PATHS:
            self._send_json(200, {
                "service": "AccessDoc",
                "adapter_version": ADAPTER_VERSION,
                "endpoint": "/api/remediate",
                "method": "POST",
                "description": "POST {scanner_input|violations, client_name?, model?} for a prioritised WCAG 2.2 remediation plan. Advisory only - AccessDoc never claims conformance.",
                "gateway": self._gateway_snapshot(),
            })
            return
        if path in _GENERATE_ALIASES:
            self._error(404, _GENERATE_HINT)
            return
        self._error(404, "Not found")

    def do_POST(self):
        self.close_connection = True
        self.request_id = uuid.uuid4().hex[:12]
        self._trace_ctx = None
        self._trace()
        self._status = 500
        start = time.monotonic()
        _p = self.path.split("?")[0].rstrip("/") or "/"
        _rem = _p in _REMEDIATE_PATHS
        pool = REMEDIATION_CAPACITY if _rem else GENERATION_CAPACITY
        # Model round-trips are seconds long, so remediation waits briefly in an
        # admission queue before shedding. Generation gets a bounded handoff
        # wait: response bytes can reach a client before the previous handler
        # releases its slot. Keep the slot through writes to bound live memory.
        if _rem:
            acquired = pool.acquire(timeout=REMEDIATION_QUEUE_TIMEOUT)
        else:
            acquired = pool.acquire(timeout=GENERATION_QUEUE_TIMEOUT)
        try:
            if not acquired:
                self._send_json(503, {"error": "Generation capacity exhausted", "request_id": self.request_id}, {"Retry-After": "1"})
                return
            self._post()
        finally:
            if acquired:
                pool.release()
            if not acquired:
                _bump("overload_rejections_total")
            elif self._status == 200 and not _rem:
                _bump("reports_total")
            print(json.dumps({"event": "request", "request_id": self.request_id,
                              "method": "POST", "status": self._status,
                              "duration_ms": round((time.monotonic() - start) * 1000, 2)}), flush=True)

    def _post(self):
        """Generate an evidence ZIP from axe-core JSON."""
        self.close_connection = True
        request_id = self.request_id
        denied = auth_error(self.headers)
        if denied:
            status, code = denied
            self._error(status, code, request_id)
            return

        # 1. Read body with strict Content-Length and size limits.
        raw, err_status, err_msg = self._read_bounded_body()
        if err_status is not None:
            self._error(err_status, err_msg, request_id)
            return

        # 2. Path check: '/' and '/api/bundle' are valid for POST.
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path in _GENERATE_ALIASES:
            self._error(404, _GENERATE_HINT, request_id)
            return
        if path not in ("/", "/api/bundle") + _REMEDIATE_PATHS:
            self._error(404, "Not found", request_id)
            return

        # 3. Content-Type must be application/json.
        ct = self.headers.get("Content-Type", "")
        if ct.split(";", 1)[0].strip().lower() != "application/json":
            self._error(415, "Content-Type must be application/json", request_id)
            return

        # 4. Parse JSON.
        try:
            body = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
            self._error(400, "Malformed JSON", request_id)
            return

        if not isinstance(body, dict):
            self._error(422, "Request body must be a JSON object", request_id)
            return

        # 4b. AI remediation plans are answered from the model gateway, not the
        #     artifact pipeline (stateless, no ZIP).
        if path in _REMEDIATE_PATHS:
            self._remediate(body, request_id)
            return

        # 5. scanner_input is required.
        scanner_input = body.get("scanner_input")
        if not scanner_input:
            self._error(400, "scanner_input required", request_id)
            return

        # 6. Validate axe-core structure and limits before expensive work.
        ok, err_status, err_msg = self._validate_axe_structure(scanner_input)
        if not ok:
            self._error(err_status, err_msg, request_id)
            return

        # 7. Bound manual_findings count if present.
        manual = body.get("manual_findings")
        if manual is not None:
            if isinstance(manual, list) and len(manual) > MAX_MANUAL_FINDINGS:
                self._error(413, f"Too many manual findings (limit {MAX_MANUAL_FINDINGS})", request_id)
                return

        # 8. Build artifacts with only passthrough keys.
        #    pdf_engine and receipt_history are NOT in _PASSTHROUGH, so they
        #    are silently dropped and never reach build_artifacts.
        safe_body = {k: v for k, v in body.items() if k in _PASSTHROUGH}

        try:
            artifacts = build_artifacts(public_body(safe_body))
            zip_bytes = build_bundle(artifacts)
        except LimitExceeded:
            self._error(413, "Input exceeds resource limits", request_id)
            return
        except ValueError as exc:
            # ValueError from parsing/validation — return 422.
            self._error(422, "Invalid axe-core data", request_id)
            return
        except Exception:
            # Any unexpected failure — return 500 with NO detail leakage.
            # The request_id allows server-side log correlation.
            self._error(500, "Internal error", request_id)
            return

        # 9. Send the ZIP.
        _bump("requests_total")
        self._status = 200
        self.send_response(200)
        self.send_header("X-Request-ID", request_id)
        self.send_header("Content-Type", "application/zip")
        self.send_header(
            "Content-Disposition",
            'attachment; filename="accessdoc-bundle.zip"',
        )
        self.send_header("Content-Length", str(len(zip_bytes)))
        for k, v in _SECURITY_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(zip_bytes)
        except (BrokenPipeError, ConnectionResetError):
            _bump("client_disconnects_total")

    def _remediate(self, body, request_id):
        """POST /api/remediate - AI remediation plan via the Melious gateway.

        Stateless and safe for the serverless adapter: no artifact store is
        touched. Credential comes from $MELIOUS_API_KEY only. Gateway faults
        degrade through the ordered model chain to the static knowledge base;
        a missing credential is an explicit 503 with Retry-After, never a 500.
        """
        try:
            from app import remediate as remediation
            from app.gateway import GatewayError
        except Exception:
            self._error(503, "GATEWAY_UNAVAILABLE", request_id)
            return
        strict = remediation.strict_gateway()
        if strict and not os.getenv("MELIOUS_API_KEY"):
            self._send_json(503, {"error": "GATEWAY_UNAVAILABLE",
                                  "detail": "MELIOUS_API_KEY is not configured for this deployment",
                                  "request_id": request_id}, {"Retry-After": "5"})
            return
        model = body.get("model")
        if model is not None and not isinstance(model, str):
            self._error(422, "model must be a string", request_id)
            return
        try:
            out = remediation.remediate(body, model=model)
        except ValueError as exc:
            self._error(422, str(exc)[:200], request_id)
            return
        except GatewayError:
            if strict:
                self._send_json(503, {"error": "GATEWAY_UNAVAILABLE", "request_id": request_id},
                                {"Retry-After": "5"})
                return
            out = remediation.remediate_offline(body)
            out["request_id"] = request_id
            out["adapter"] = "serverless"
            self._send_json(200, out, {"X-AccessDoc-Mode": "degraded-offline-kb"})
            return
        except Exception:
            self._error(500, "Internal error", request_id)
            return
        out["request_id"] = request_id
        out["adapter"] = "serverless"
        self._send_json(200, out)

    def do_PUT(self):
        self._error(405, "Method not allowed")

    def do_DELETE(self):
        self._error(405, "Method not allowed")

    def do_PATCH(self):
        self._error(405, "Method not allowed")

    def do_HEAD(self):
        self.request_id = uuid.uuid4().hex[:12]
        self._trace_ctx = None
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path == "/" and _wants_html(self.headers.get("Accept")) and self._send_static("/index.html", head_only=True):
            return
        if path in _STATIC_FILES and self._send_static(path, head_only=True):
            return
        if path == "/metrics":
            self._send_text_metrics()
            return
        if path not in ("/", "/readyz", "/healthz", "/health", "/api/bundle", "/limits") + _REMEDIATE_PATHS:
            self._error(404, "Not found")
            return
        self.send_response(200)
        self.send_header("X-Request-ID", self.request_id)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        for k, v in _SECURITY_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()

    def do_OPTIONS(self):
        """CORS preflight. Conservative: only GET and POST."""
        self.send_response(204)
        for k, v in _SECURITY_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
