"""Vercel serverless handler for AccessDoc bundle generation."""
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from http.server import BaseHTTPRequestHandler
from app.service import build_artifacts
from app.bundle import build_bundle
from app.models import VERSION

ADAPTER_VERSION = VERSION

_PASSTHROUGH = (
    "scanner_input", "client_name", "agency_name", "audit_date",
    "manual_findings", "enrich", "include_sarif", "include_vpat",
    "include_eaa", "prior_receipt",
)


class handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "service": "AccessDoc",
            "adapter_version": ADAPTER_VERSION,
            "status": "ok",
        }).encode())

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            body = json.loads(raw) if raw else {}
            if not body.get("scanner_input"):
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "scanner_input required"}).encode())
                return
            safe_body = {k: v for k, v in body.items() if k in _PASSTHROUGH}
            zip_bytes = build_bundle(build_artifacts(safe_body))
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", 'attachment; filename="accessdoc-bundle.zip"')
            self.send_header("Content-Length", str(len(zip_bytes)))
            self.end_headers()
            self.wfile.write(zip_bytes)
        except Exception as exc:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(exc)}).encode())
