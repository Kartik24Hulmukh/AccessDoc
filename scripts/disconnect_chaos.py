#!/usr/bin/env python3
"""Loopback-only disconnect/malformed-input chaos; no human participants.

Usage: python scripts/disconnect_chaos.py [output.json]; defaults to chaos_report.json.
"""
import concurrent.futures
import http.client
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["RATE_LIMIT_PER_MINUTE"] = "100000"
from app.main import Handler, Server


def main():
    server = Server(("127.0.0.1", 0), Handler)
    port = server.server_port
    os.environ["ALLOWED_HOSTS"] = "127.0.0.1:%d" % port
    runner = threading.Thread(target=server.serve_forever)
    runner.start()
    uncaught = []
    original = threading.excepthook
    threading.excepthook = lambda args: uncaught.append(args.exc_type.__name__)
    baseline = {t.ident for t in threading.enumerate()}
    rows = []
    def journey(i):
        start = time.monotonic()
        mode = i % 5
        if mode in (0, 1):
            # Close before headers complete, or cancel partway through the body.
            with socket.create_connection(("127.0.0.1", port), timeout=10) as conn:
                head = b"POST /api/bundle HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                if mode == 1:
                    head += b"Content-Type: application/json\r\nContent-Length: 500\r\n\r\n{"
                conn.sendall(head)
                conn.shutdown(socket.SHUT_WR)
            return {"profile": i, "case": "cancel-body" if mode else "close-headers", "pass": True}
        body, mime, expected = [
            (b"%PDF-1.7 invalid", "application/pdf", 422),
            (b"{broken", "application/json", 422),
            (b"PK\x03\x04invalid", "application/zip", 422),
        ][mode - 2]
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            conn.request("POST", "/api/bundle", body, {"Content-Type": mime})
            response = conn.getresponse()
            response.read()
            return {"profile": i, "case": mime, "status": response.status,
                    "pass": response.status == expected,
                    "ms": round((time.monotonic() - start) * 1000, 2)}
        finally:
            conn.close()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=100) as pool:
            futures = [pool.submit(journey, i) for i in range(100)]
            for i, future in enumerate(futures):
                try:
                    rows.append(future.result())
                except Exception as exc:
                    rows.append({"profile": i, "pass": False, "error": type(exc).__name__})
        probes = {}
        for route in ("/healthz", "/readyz"):
            start = time.monotonic()
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            try:
                conn.request("GET", route)
                response = conn.getresponse()
                response.read()
                probes[route] = {"status": response.status, "ms": round((time.monotonic()-start)*1000, 2)}
            finally:
                conn.close()
    finally:
        server.shutdown()
        server.server_close()
        runner.join(timeout=5)
        threading.excepthook = original
    leaked = [t.name for t in threading.enumerate() if t.ident not in baseline]
    report = {"scope": "100 synthetic socket workflows; 40 disconnects; no humans; loopback only",
              "workflows": rows, "recovery": probes, "unhandled_thread_exceptions": uncaught,
              "new_threads_after_shutdown": leaked}
    report["pass"] = (all(r["pass"] for r in rows) and not uncaught and not leaked
                      and all(p["status"] == 200 and p["ms"] < 200 for p in probes.values()))
    out_path = Path(sys.argv[1] if len(sys.argv) > 1 else "chaos_report.json")
    out_path.write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "workflows"}))
    return 0 if report["pass"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
