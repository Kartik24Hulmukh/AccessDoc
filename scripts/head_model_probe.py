"""Live head-of-chain availability probe: is the first model slow or down?

Usage: MELIOUS_API_KEY=... python3 scripts/head_model_probe.py [--samples N] [--window S]
Writes JSON (stdout) with per-sample status/latency/tokens. Never prints the key.
"""
import argparse, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import gateway as gw

p = argparse.ArgumentParser()
p.add_argument("--samples", type=int, default=3)
p.add_argument("--window", type=float, default=60.0)
p.add_argument("--models", default="")
p.add_argument("--max-tokens", type=int, default=256)
a = p.parse_args()
models = [gw.normalize_model(m) for m in a.models.split(",") if m] or list(gw.CANONICAL_CHAIN)
g = gw.ModelGateway(read_timeout=a.window, budget_seconds=a.window + 5)
msgs = [{"role": "user", "content": "List three WCAG 2.2 AA fixes for a missing form label. Be brief."}]
out = {"window_s": a.window, "results": {}}
for m in models:
    rows = []
    for _ in range(a.samples):
        t0 = time.monotonic()
        try:
            st, hdr, body = g._post(m, msgs, max_tokens=a.max_tokens, remaining=a.window)
            usage = (body or {}).get("usage", {}) or {}
            rows.append({"status": st, "ms": round((time.monotonic() - t0) * 1000, 1),
                         "tokens": usage.get("total_tokens"), "ok": st == 200 and bool(body.get("choices"))})
        except Exception as e:
            rows.append({"status": None, "ms": round((time.monotonic() - t0) * 1000, 1),
                         "error": type(e).__name__, "ok": False})
    lat = sorted(r["ms"] for r in rows)
    out["results"][m] = {"samples": rows, "success": sum(r["ok"] for r in rows),
                         "p50_ms": lat[len(lat) // 2], "max_ms": lat[-1]}
print(json.dumps(out, indent=2))
