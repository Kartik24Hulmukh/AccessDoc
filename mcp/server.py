#!/usr/bin/env python3
"""AccessDoc MCP server (JSON-RPC 2.0 over stdio). Zero external deps."""
import base64
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.service import build_artifacts
from app.bundle import build_bundle, validate_bundle
from app.catalog import catalog_summary
from app.models import VERSION

PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {"name": "catalog_info",
     "description": "Return the AccessDoc WCAG rule catalog summary.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "generate_bundle",
     "description": "Generate a tamper-evident evidence bundle (zip) from axe-core JSON. Returns base64.",
     "inputSchema": {"type": "object", "properties": {
         "scanner_input": {"type": "string"}, "client_name": {"type": "string"},
         "audit_date": {"type": "string"}, "include_sarif": {"type": "boolean"},
         "include_vpat": {"type": "boolean"}, "include_eaa": {"type": "boolean"},
         "enrich": {"type": "boolean"}}, "required": ["scanner_input"]}},
    {"name": "export_openacr",
     "description": "Return the EN 301 549-mapped OpenACR YAML.",
     "inputSchema": {"type": "object", "properties": {
         "scanner_input": {"type": "string"}, "client_name": {"type": "string"}},
         "required": ["scanner_input"]}},
    {"name": "export_sarif",
     "description": "Return SARIF 2.1.0 findings JSON.",
     "inputSchema": {"type": "object", "properties": {
         "scanner_input": {"type": "string"}}, "required": ["scanner_input"]}},
    {"name": "export_vpat",
     "description": "Return a VPAT draft (HTML). Marked DRAFT - automated evidence only.",
     "inputSchema": {"type": "object", "properties": {
         "scanner_input": {"type": "string"}, "client_name": {"type": "string"}},
         "required": ["scanner_input"]}},
    {"name": "verify_bundle",
     "description": "Validate a base64-encoded AccessDoc bundle zip.",
     "inputSchema": {"type": "object", "properties": {
         "bundle_base64": {"type": "string"}}, "required": ["bundle_base64"]}},
]


def _text_result(text):
    return {"content": [{"type": "text", "text": text}]}


def call_tool(name, args):
    args = args or {}
    if name == "catalog_info":
        return _text_result(json.dumps(catalog_summary(), indent=2))
    if name == "generate_bundle":
        arts = build_artifacts(args)
        data = build_bundle(arts)
        return _text_result(json.dumps({
            "bundle_base64": base64.b64encode(data).decode(),
            "bytes": len(data),
            "members": list(arts.payloads().keys()) + ["manifest.json"],
            "accessdoc_version": VERSION}))
    if name == "export_openacr":
        return _text_result(build_artifacts(args).openacr_yaml)
    if name == "export_sarif":
        a = dict(args); a["include_sarif"] = True
        return _text_result(build_artifacts(a).sarif_json)
    if name == "export_vpat":
        a = dict(args); a["include_vpat"] = True
        return _text_result(build_artifacts(a).vpat_html)
    if name == "verify_bundle":
        data = base64.b64decode(args.get("bundle_base64", ""))
        return _text_result(json.dumps(validate_bundle(data), indent=2))
    raise ValueError(f"Unknown tool: {name}")


def handle_request(req):
    method = req.get("method")
    req_id = req.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "accessdoc-mcp", "version": VERSION}}}
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = req.get("params", {})
        try:
            result = call_tool(params.get("name"), params.get("arguments"))
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": f"error: {exc}"}],
                "isError": True}}
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}}


def serve(stdin=None, stdout=None):
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        resp = handle_request(req)
        if resp is not None:
            stdout.write(json.dumps(resp) + "\n")
            stdout.flush()


if __name__ == "__main__":
    serve()
