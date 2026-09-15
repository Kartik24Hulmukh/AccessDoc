#!/usr/bin/env python3
"""Concurrency torture bench: 100 workers x 2 rounds of mixed-size,
corrupt and oversize payloads against the self-hosted adapter.
Emits p50/p95/p99 latency, RSS floor/ceiling, status histogram and a
machine-readable fault-recovery verdict. Usage: concurrent_bench.py [repo_root]"""
import gc, json, os, sys, time, threading, random, statistics
import urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.getcwd())
sys.path.insert(0, ROOT)
os.environ.setdefault("MAX_CONCURRENT_REQUESTS", "32")
os.environ.setdefault("MAX_CONNECTIONS", "256")
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")
os.environ["ALLOWED_HOSTS"] = ""
from http.server import HTTPServer
from app.main import Handler, Server
from app.limits import MAX_HTTP_BODY_BYTES

with open(os.path.join(ROOT, "public", "sample", "axe-sample.json"), encoding="utf-8") as _fh:
    SAMPLE = json.load(_fh)

def payload(kind, i):
    if kind == "tiny":
        return json.dumps({"scanner_input": SAMPLE}).encode()
    if kind == "medium":
        big = json.loads(json.dumps(SAMPLE)); big["violations"] = (SAMPLE["violations"] * 40)[:400]
        return json.dumps({"scanner_input": big, "client_name": "Bench Co"}).encode()
    if kind == "large":
        big = json.loads(json.dumps(SAMPLE))
        nodes = [{"impact": "serious", "html": "<div>%s</div>" % ("x" * 120), "target": ["#n%d" % j]} for j in range(30)]
        big["violations"] = [dict(v, nodes=nodes) for v in SAMPLE["violations"] for _ in range(15)]
        return json.dumps({"scanner_input": big}).encode()
    if kind == "oversize":
        pad = "A" * (MAX_HTTP_BODY_BYTES + 64 * 1024)
        return json.dumps({"scanner_input": pad}).encode()
    if kind == "corrupt":
        return b"{not json at all" + str(i).encode()
    if kind == "hostile":
        big = json.loads(json.dumps(SAMPLE))
        for v in big["violations"]:
            v["help"] = "<script>alert(1)</script>" + v["help"]
            for n in v["nodes"]:
                n["html"] = "<img src=x onerror=\"alert(1)\">"
        return json.dumps({"scanner_input": big}).encode()
    raise ValueError(kind)

EXPECT = {"tiny": 200, "medium": 200, "large": 200, "hostile": 200,
          "oversize": 413, "corrupt": 422}

def rss_mb():
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024.0
    return 0.0

def main():
    srv = Server(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    os.environ["ALLOWED_HOSTS"] = "127.0.0.1:%d" % port
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    rss_floor = rss_mb(); rss_peak = rss_floor
    stop = threading.Event()
    def sampler():
        nonlocal rss_peak
        while not stop.is_set():
            rss_peak = max(rss_peak, rss_mb()); time.sleep(0.02)
    sampler_thread = threading.Thread(target=sampler, daemon=True)
    sampler_thread.start()

    results = []; lock = threading.Lock()
    def worker(task):
        kind, i = task
        body = payload(kind, i)
        req = urllib.request.Request("http://127.0.0.1:%d/api/bundle" % port, data=body,
            headers={"Content-Type": "application/json", "Host": "127.0.0.1:%d" % port})
        t0 = time.monotonic(); status = None; err = None
        transport_attempt_errors = 0; admission_retries = 0
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    status = r.status; r.read()
                break
            except urllib.error.HTTPError as e:
                status = e.code; e.read()
                ra = e.headers.get("Retry-After")
                e.close()
                if status == 503 and ra:
                    admission_retries += 1
                    time.sleep(float(ra)); continue
                break
            except OSError as e:
                transport_attempt_errors += 1
                err = repr(e); time.sleep(0.05 * (attempt + 1))
        with lock:
            results.append({"kind": kind, "status": status, "err": err,
                            "transport_attempt_errors": transport_attempt_errors,
                            "admission_retries": admission_retries,
                            "ms": round((time.monotonic() - t0) * 1000, 2)})

    kinds = ["tiny", "medium", "large", "hostile", "oversize", "corrupt"]
    rng = random.Random(7)
    tasks = [(kinds[i % len(kinds)], i) for i in range(200)]
    rng.shuffle(tasks)
    t_start = time.monotonic()
    with ThreadPoolExecutor(max_workers=100) as ex:
        list(ex.map(worker, tasks))
    wall = time.monotonic() - t_start
    # Recovery is a fresh healthy request after hostile traffic, not inferred
    # from the absence of 5xx in the traffic under test.
    recovery = {}
    for path in ("/healthz", "/api/bundle"):
        data = payload("tiny", 0) if path == "/api/bundle" else None
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                response.read()
                recovery[path] = response.status
        except (OSError, urllib.error.HTTPError) as exc:
            recovery[path] = str(exc)
            if hasattr(exc, "close"):
                exc.close()
    stop.set(); sampler_thread.join(timeout=2)
    srv.shutdown(); srv.server_close()
    gc.collect()
    rss_after = rss_mb()

    ok = [r for r in results if r["err"] is None]
    bad_transport = [r for r in results if r["err"]]
    viol = [r for r in ok if r["status"] != EXPECT[r["kind"]]]
    unexpected_5xx = [r for r in ok if r["status"] and r["status"] >= 500]
    lat = sorted(r["ms"] for r in ok)
    def pct(p):
        if not lat: return 0.0
        return lat[min(len(lat) - 1, int(p * len(lat)))]
    hist = {}
    for r in ok: hist[r["status"]] = hist.get(r["status"], 0) + 1
    verdict = {
        "workers": 100, "requests": len(results), "wall_seconds": round(wall, 2),
        "seed": 7, "throughput_rps": round(len(results) / wall, 2),
        "scope": "local self-hosted JSON ingestion; not a production 100x baseline",
        "transport_attempt_errors": sum(r["transport_attempt_errors"] for r in results),
        "admission_retries": sum(r["admission_retries"] for r in results),
        "recovery_probes": recovery, "rss_after_mb": round(rss_after, 1),
        "status_histogram": hist,
        "unexpected_5xx": len(unexpected_5xx),
        "contract_violations": len(viol),
        "transport_errors": len(bad_transport),
        "latency_p50_ms": pct(0.50), "latency_p95_ms": pct(0.95),
        "latency_p99_ms": pct(0.99), "latency_max_ms": lat[-1] if lat else 0,
        "rss_floor_mb": round(rss_floor, 1), "rss_ceiling_mb": round(rss_peak, 1),
        "fault_recovery": "PASS" if (not unexpected_5xx and not viol and not bad_transport
                                     and all(v == 200 for v in recovery.values())) else "FAIL",
    }
    print(json.dumps(verdict, indent=2))
    out = os.path.join(ROOT, "bench_results.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(verdict, fh, indent=2)
    return 0 if verdict["fault_recovery"] == "PASS" else 1

if __name__ == "__main__":
    sys.exit(main())
