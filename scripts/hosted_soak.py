#!/usr/bin/env python3
"""Bounded loopback-only hosted soak, overload and recovery evidence.

No remote target option by design. Measures completed valid bundles separately
from deliberate 503 admission rejections. RSS/CPU cover this local process only.
Not a staging capacity certificate. Example: --seconds 60 --workers 8
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import math
import os
from pathlib import Path
import resource
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.handler import handler
from app.main import Handler, Server
from app.bundle import validate_bundle


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def run(adapter, seconds, workers):
    server = Server(("127.0.0.1", 0), adapter)
    os.environ["ALLOWED_HOSTS"] = f"127.0.0.1:{server.server_port}"
    os.environ["RATE_LIMIT_PER_MINUTE"] = "1000000"
    os.environ["ACCESSDOC_REQUIRE_AUTH"] = "true"
    os.environ["ACCESSDOC_API_KEY"] = "local-soak-only"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # Explicit 100x finding-instance expansion, not a throughput promise.
    payload = json.dumps({"scanner_input": {"violations": [{"id": "image-alt", "impact": "critical", "nodes": [{"target": [f"#n{i}"]} for i in range(100)]}]}, "audit_date": "2026-09-13"}).encode()
    stop = threading.Event()
    samples = []

    def memory():
        while not stop.wait(1):
            rss = None
            try:
                rss = int(Path("/proc/self/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")
            except (OSError, ValueError, IndexError):
                pass
            samples.append({"elapsed_s": round(time.monotonic() - start, 2), "rss_bytes": rss})

    def post():
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=15)
        begin = time.monotonic()
        try:
            conn.request("POST", "/api/bundle", payload, {"Content-Type": "application/json", "Authorization": "Bearer local-soak-only"})
            response = conn.getresponse()
            body = response.read()
            status = response.status
            valid = status != 200 or validate_bundle(body)["valid"]
            retry = response.getheader("Retry-After")
            return status, time.monotonic() - begin, valid, retry
        except (OSError, http.client.HTTPException):
            return 0, time.monotonic() - begin, False, None
        finally:
            conn.close()

    start = time.monotonic()
    cpu_start = time.process_time()
    sampler = threading.Thread(target=memory, daemon=True)
    sampler.start()

    def worker():
        results = []
        while time.monotonic() - start < seconds:
            result = post()
            results.append(result)
            # Avoid a rejection spin-loop; bounded synthetic closed-loop traffic.
            if result[0] == 503:
                time.sleep(.05)
        return results

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = [r for chunk in pool.map(lambda _: worker(), range(workers)) for r in chunk]
        elapsed = time.monotonic() - start
        cpu = time.process_time() - cpu_start
        recovery = post()
        counts = {str(status): sum(r[0] == status for r in results) for status in set(r[0] for r in results)}
        latencies = [r[1] * 1000 for r in results if r[0] == 200]
        invalid = sum(not r[2] for r in results)
        passed = (bool(latencies) and not invalid and all(r[0] in (200, 503) for r in results)
                  and all(r[3] for r in results if r[0] == 503) and recovery[0] == 200 and recovery[2])
        return {"adapter": adapter.__module__, "seconds": round(elapsed, 2), "workers": workers,
                "finding_instances": 100, "attempts": len(results), "statuses": counts,
                "successful_bundles_per_second": round(len(latencies) / elapsed, 2),
                "success_p50_ms": percentile(latencies, .5), "success_p95_ms": percentile(latencies, .95),
                "success_p99_ms": percentile(latencies, .99), "cpu_seconds": round(cpu, 2),
                "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "rss_samples": samples, "invalid_or_transport_errors": invalid,
                "recovery_status": recovery[0], "pass": passed}
    finally:
        stop.set()
        sampler.join()
        server.shutdown()
        server.server_close()
        thread.join()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--output", default="hosted-soak.json")
    args = parser.parse_args()
    if not 1 <= args.seconds <= 300 or not 1 <= args.workers <= 32:
        parser.error("seconds must be 1..300 and workers 1..32")
    result = {"scope": "Local closed-loop, authenticated 100-instance payload; not production/staging throughput proof",
              "results": [run(adapter, args.seconds, args.workers) for adapter in (handler, Handler)]}
    result["pass"] = all(r["pass"] for r in result["results"])
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"output": args.output, "pass": result["pass"]}))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
