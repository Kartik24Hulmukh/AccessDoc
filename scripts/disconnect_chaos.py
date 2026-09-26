#!/usr/bin/env python3
"""Loopback-only disconnect/malformed-input chaos; no human participants.

Usage: python scripts/disconnect_chaos.py [output.json] [--output output.json].
Defaults to chaos_report.json.
"""
import argparse
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
from app.main import Handler, Server


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_positional", nargs="?")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    args.output = args.output or args.output_positional or "chaos_report.json"
    return args


def body_read_interrupted(status, body):
    """Only the real body reader's truncated-input response proves coverage.

    A preflight rejection, socket write succeeding, or generic invalid JSON
    response does not establish that the server consumed a partial body.
    """
    try:
        error = json.loads(body).get("error", {})
        return (status == 422 and error.get("code") == "INVALID_INPUT"
                and error.get("message") == "Truncated request body")
    except (ValueError, TypeError, AttributeError):
        return False


def main():
    args = parse_args()
    os.environ["RATE_LIMIT_PER_MINUTE"] = "100000"
    server_errors = []

    class ObservedServer(Server):
        def handle_error(self, request, client_address):
            # ThreadingMixIn consumes handler failures before threading.excepthook.
            server_errors.append(sys.exc_info()[0].__name__)

    server = ObservedServer(("127.0.0.1", 0), Handler)
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
                head = f"POST /api/bundle HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n".encode("ascii")
                if mode == 1:
                    head += b"Content-Type: application/json\r\nContent-Length: 500\r\n\r\n{"
                conn.sendall(head)
                conn.shutdown(socket.SHUT_WR)
                if mode == 1:
                    # Half-close upload, retain the receive side for proof of the
                    # exact rejection. No sleep or optimistic send-only verdict.
                    with http.client.HTTPResponse(conn) as response:
                        response.begin()
                        content = response.read()
                        interrupted = body_read_interrupted(response.status, content)
                        return {"profile": i, "case": "cancel-body",
                                "status": response.status,
                                "body_read_interrupted": interrupted,
                                "pass": interrupted}
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
              "new_threads_after_shutdown": leaked, "server_errors": server_errors,
              "server_runner_alive": runner.is_alive()}
    report["pass"] = (all(r["pass"] for r in rows) and not uncaught and not leaked
                      and not server_errors and not runner.is_alive()
                      and all(p["status"] == 200 and p["ms"] < 200 for p in probes.values()))
    out_path = Path(args.output)
    out_path.write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "workflows"}))
    return 0 if report["pass"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
