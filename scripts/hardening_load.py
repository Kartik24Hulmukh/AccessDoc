#!/usr/bin/env python3
"""Bounded LOCAL load/contract gate. Never stress-tests a public endpoint.

Usage: python scripts/hardening_load.py --output hardening-load.json
100x denotes 1 -> 100 generated finding instances, NOT throughput capacity.
"""
import argparse
import concurrent.futures
import hashlib
import http.client
import json
import os
from pathlib import Path
import statistics
import sys
import threading
import time
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import api.handler as adapter
from api.handler import handler
from app.bundle import validate_bundle
from app.service import build_artifacts
from app.parser import parse_axe_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="hardening-load.json")
    args = parser.parse_args()
    adapter.GENERATION_CAPACITY = threading.BoundedSemaphore(8)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    results = {"scope": "loopback only; 8 workers, 100 requests; not capacity certification",
               "workers": 8, "requests": 100, "contract": [], "scale": []}
    fixture = {"url": "https://example.com", "testEngine": {"version": "4.11.0"},
               "violations": [{"id": "image-alt", "impact": "critical",
                               "nodes": [{"target": ["#hero"]}]}]}
    body = {"scanner_input": fixture, "audit_date": "2026-09-13", "client_name": "Load test",
            "include_sarif": True, "include_vpat": True, "include_eaa": True}
    failures = []

    def post(payload, content_type="application/json"):
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        start = time.perf_counter()
        try:
            conn.request("POST", "/api/bundle", raw, {"Content-Type": content_type})
            response = conn.getresponse()
            content = response.read()
            return response.status, content, time.perf_counter() - start
        finally:
            conn.close()

    try:
        cases = [
            ("null violations", {"scanner_input": {"violations": None}}, 200, "application/json"),
            ("missing violations", {"scanner_input": {"url": "https://example.com"}}, 422, "application/json"),
            ("malformed description", {"scanner_input": {"violations": [{"id": "x", "description": {}}]}}, 422, "application/json"),
            ("wrong metadata type", dict(body, client_name={}), 422, "application/json"),
            ("wrong boolean type", dict(body, enrich="false"), 422, "application/json"),
            ("string ceiling", dict(body, client_name="a" * 10001), 413, "application/json"),
            ("manual CSV ceiling", dict(body, manual_findings="id,impact\n" + "x,serious\n" * 5001), 413, "application/json"),
            ("content-type lookalike", body, 415, "application/json-invalid"),
            ("deep JSON", b'{"x":' + b'[' * 1100 + b'0' + b']' * 1100 + b'}', 400, "application/json"),
        ]
        for name, payload, expected, ct in cases:
            status, content, elapsed = post(payload, ct)
            ok = status == expected
            if status == 200:
                ok = ok and validate_bundle(content)["valid"]
            results["contract"].append({"name": name, "expected": expected, "actual": status, "pass": ok})
            if not ok:
                failures.append(name)
        start = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(lambda _: post(body), range(100)))
        elapsed = time.perf_counter() - start
        latencies = sorted(r[2] for r in responses)
        digests = set()
        for status, content, latency in responses:
            if status != 200 or not validate_bundle(content)["valid"]:
                failures.append("load response invalid")
            digests.add(hashlib.sha256(content).hexdigest())
        if len(digests) != 1:
            failures.append("concurrent deterministic output differs")
        results["load"] = {"seconds": round(elapsed, 4), "requests_per_second": round(100 / elapsed, 2),
                           "p50_seconds": round(statistics.median(latencies), 4),
                           "p95_seconds": round(latencies[94], 4), "max_seconds": round(max(latencies), 4),
                           "unique_bundle_digests": len(digests), "all_200": all(r[0] == 200 for r in responses)}
        for scale in (1, 100):
            scanner = dict(fixture, violations=[{"id": "image-alt", "impact": "critical", "nodes": [
                {"target": [f"#n-{i}"]} for i in range(scale)]}])
            started = time.perf_counter()
            arts = build_artifacts(dict(body, scanner_input=scanner))
            receipt = json.loads(arts.receipt_json)
            ok = receipt["summary"]["critical"] == scale == len(receipt["violations"])
            results["scale"].append({"finding_instances": scale, "seconds": round(time.perf_counter()-started, 4), "pass": ok})
            if not ok:
                failures.append("count invariant")
        results["failures"] = failures
        results["pass"] = not failures
        Path(args.output).write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps(results, indent=2))
        return bool(failures)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
