"""Vercel serverless handler for AccessDoc bundle generation.

This is a bounded ReportLab demo API. It accepts axe-core JSON, produces a
deterministic evidence ZIP, and returns it. It does NOT expose pdf_engine=
weasyprint or receipt_history from the public API — those are internal/CLI-only
paths. All inputs are size-limited before expensive work begins.

Security headers, strict content-type/length validation, and bounded reads
ensure hostile payloads cannot exhaust resources or leak internal errors.
"""
import json
import sys
import os
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from http.server import BaseHTTPRequestHandler
from app.service import build_artifacts
from app.bundle import build_bundle
from app.models import VERSION
from app.limits import (
    MAX_HTTP_BODY_BYTES,
    MAX_VIOLATIONS,
    MAX_TOTAL_NODES,
    MAX_NODES_PER_VIOLATION,
    MAX_STRING_CHARS,
    MAX_MANUAL_FINDINGS,
)

ADAPTER_VERSION = VERSION

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
    # Conservative CORS: same-origin only. No wildcard.
    "Access-Control-Allow-Origin": "null",
    "Access-Control-Allow-Methods": "GET, POST",
    "Access-Control-Allow-Headers": "Content-Type",
    # Prevent error pages from being rendered as HTML by browsers.
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer",
}


class handler(BaseHTTPRequestHandler):
    """Bounded HTTP handler for AccessDoc bundle generation.

    All error responses are JSON with a generic message and a request ID.
    Raw exception text is never returned to the client.
    """

    # Suppress default stderr logging (Vercel captures stdout/stderr separately).
    def log_message(self, fmt, *args):
        pass

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _send_json(self, status, payload, extra_headers=None):
        """Send a JSON response with security headers. Never renders HTML."""
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for k, v in _SECURITY_HEADERS.items():
            self.send_header(k, v)
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

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
        raw = self.rfile.read(length)
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
            except _json.JSONDecodeError:
                return False, 400, "Malformed JSON in scanner_input"
        elif isinstance(scanner_input, dict):
            data = scanner_input
        else:
            return False, 422, "scanner_input must be a JSON object or string"

        if not isinstance(data, dict):
            return False, 422, "axe-core input must be a JSON object"

        violations_raw = data.get("violations")
        if violations_raw is None:
            return False, 422, "scanner_input missing 'violations' array"

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

        return True, None, None

    # ------------------------------------------------------------------ #
    # HTTP methods
    # ------------------------------------------------------------------ #

    def do_GET(self):
        """Health check on '/', '/readyz', '/healthz', '/api/bundle'."""
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path in ("/", "/readyz", "/healthz", "/health"):
            self._send_json(200, {
                "service": "AccessDoc",
                "adapter_version": ADAPTER_VERSION,
                "status": "ok",
                "api_note": "Bounded ReportLab demo API. See docs for limitations.",
            })
            return
        if path == "/api/bundle":
            self._send_json(200, {
                "service": "AccessDoc",
                "adapter_version": ADAPTER_VERSION,
                "endpoint": "/api/bundle",
                "method": "POST",
                "description": "Send POST with axe-core JSON in scanner_input to generate an evidence ZIP.",
            })
            return
        self._error(404, "Not found")

    def do_POST(self):
        """Generate an evidence ZIP from axe-core JSON."""
        request_id = uuid.uuid4().hex[:12]

        # 1. Read body with strict Content-Length and size limits.
        raw, err_status, err_msg = self._read_bounded_body()
        if err_status is not None:
            self._error(err_status, err_msg, request_id)
            return

        # 2. Path check: '/' and '/api/bundle' are valid for POST.
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path not in ("/", "/api/bundle"):
            self._error(404, "Not found", request_id)
            return

        # 3. Content-Type must be application/json.
        ct = self.headers.get("Content-Type", "")
        if "application/json" not in ct.lower():
            self._error(415, "Content-Type must be application/json", request_id)
            return

        # 4. Parse JSON.
        try:
            body = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._error(400, "Malformed JSON", request_id)
            return

        if not isinstance(body, dict):
            self._error(422, "Request body must be a JSON object", request_id)
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
            artifacts = build_artifacts(safe_body)
            zip_bytes = build_bundle(artifacts)
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
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header(
            "Content-Disposition",
            'attachment; filename="accessdoc-bundle.zip"',
        )
        self.send_header("Content-Length", str(len(zip_bytes)))
        for k, v in _SECURITY_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(zip_bytes)

    def do_PUT(self):
        self._error(405, "Method not allowed")

    def do_DELETE(self):
        self._error(405, "Method not allowed")

    def do_PATCH(self):
        self._error(405, "Method not allowed")

    def do_HEAD(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path not in ("/", "/readyz", "/healthz", "/health", "/api/bundle"):
            self._error(404, "Not found")
            return
        self.send_response(200)
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
