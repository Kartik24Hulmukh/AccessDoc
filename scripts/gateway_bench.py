#!/usr/bin/env python3
"""Melious gateway benchmark: p50/p95/p99 per frontier model + resilience probes.
Credential comes exclusively from $MELIOUS_API_KEY. Usage: gateway_bench.py [repo_root]"""
import json, os, sys, time, statistics
ROOT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.getcwd())
sys.path.insert(0, ROOT)
from app.gateway import ModelGateway, CANONICAL_CHAIN, GatewayError

PROMPT = ("Explain how to remediate WCAG 1.1.1 Non-text Content failures "
          "found by axe-core in a public-sector dashboard.")

def bench():
    rows = {}
    for model in CANONICAL_CHAIN:
        lat = []; toks = []; okc = 0
        for _ in range(3):
            gw = ModelGateway(chain=(model,))
            t0 = time.monotonic()
            try:
                res = gw.chat(PROMPT, model=model, static_fallback=False)
                okc += 1; toks.append(res.tokens)
                lat.append(round((time.monotonic() - t0) * 1000, 2))
            except GatewayError as e:
                lat.append(round((time.monotonic() - t0) * 1000, 2))
                rows[model] = {"ok": okc, "n": 3, "error": str(e)}
                break
        else:
            lat.sort()
            rows[model] = {"ok": okc, "n": 3,
                           "p50_ms": lat[len(lat)//2], "p95_ms": lat[-1],
                           "p99_ms": lat[-1], "avg_tokens": sum(toks)//max(1,len(toks))}
    return rows

def probes():
    out = {}
    calls = {"n": 0}
    def storm(model, messages):
        calls["n"] += 1
        if model == "glm-5.3" and calls["n"] <= 4:
            return 429, {"Retry-After": "0"}, {"error": "rate limited"}
        return 200, {}, {"choices": [{"message": {"content": "served by " + model}}],
                         "usage": {"total_tokens": 42}}
    gw = ModelGateway(transport=storm, base_backoff=0.01, max_sleep=0.05)
    res = gw.chat(PROMPT)
    out["429_storm_fallback"] = {"served_by": res.model, "attempts": res.attempts,
                                 "pass": res.model == "glm-5.3-flash"}
    def outage(model, messages):
        raise GatewayError("gateway down", status=503, model=model)
    gw2 = ModelGateway(transport=outage, base_backoff=0.01, max_sleep=0.02)
    t0 = time.monotonic()
    try:
        gw2.chat(PROMPT, static_fallback=False); out["outage_fail_fast"] = {"pass": False}
    except GatewayError:
        out["outage_fail_fast"] = {"pass": True, "ms": round((time.monotonic()-t0)*1000, 1)}
    res3 = gw2.chat(PROMPT, static_fallback=True)
    out["static_kb_last_resort"] = {"pass": res3.fallback and bool(res3.text),
                                    "model": res3.model}
    return out

if __name__ == "__main__":
    data = {"models": bench(), "resilience": probes()}
    print(json.dumps(data, indent=2))
    json.dump(data, open(os.path.join(ROOT, "gateway_bench.json"), "w"), indent=2)
