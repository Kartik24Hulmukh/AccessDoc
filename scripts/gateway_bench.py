#!/usr/bin/env python3
"""Melious gateway benchmark: p50/p95/p99 per frontier model + resilience probes.

Credential comes exclusively from $MELIOUS_API_KEY.

Usage: gateway_bench.py [repo_root] [--output PATH] [--probes-only]

Exit codes (so the bench can act as a real validation gate):
  0  every resilience probe passed (and, in live mode, a credential was present)
  1  at least one resilience probe failed
  2  live mode requested but $MELIOUS_API_KEY is unset (nothing was measured)
"""
import argparse, json, os, sys, time, statistics


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", nargs="?", default=os.getcwd(),
                    help="repository root (default: cwd)")
    ap.add_argument("--output", default=None,
                    help="JSON report path (default: <root>/gateway_bench.json)")
    ap.add_argument("--probes-only", action="store_true",
                    help="run offline resilience probes only; no credential needed")
    return ap.parse_args(argv)


def exit_code(data, key_present, probes_only):
    """Map a report to a gate verdict. Pure, so it is unit-testable."""
    if not probes_only and not key_present:
        return 2
    probes = data.get("resilience") or {}
    if not probes or not all(bool(v.get("pass")) for v in probes.values()):
        return 1
    return 0


if __name__ == "__main__":
    ARGS = parse_args()
    ROOT = os.path.abspath(ARGS.root)
    sys.path.insert(0, ROOT)
from app.gateway import ModelGateway, CANONICAL_CHAIN, GatewayError, API_KEY_ENV

PROMPT = ("Explain how to remediate WCAG 1.1.1 Non-text Content failures "
          "found by axe-core in a public-sector dashboard.")

def bench():
    """Three independent samples/model; failures count, never fabricated N.

    Small-sample percentiles are descriptive order statistics, not an SLO.
    Sessions/breakers are reused across calls as they are in the service.
    """
    rows = {}
    for model in CANONICAL_CHAIN:
        gw = ModelGateway(chain=(model,))
        samples = []
        try:
            for _ in range(3):
                t0 = time.monotonic()
                try:
                    res = gw.chat(PROMPT, model=model, static_fallback=False)
                    sample = {"ok": True, "tokens": res.tokens}
                except GatewayError as exc:
                    sample = {"ok": False, "error": str(exc), "status": exc.status}
                sample["ms"] = round((time.monotonic() - t0) * 1000, 2)
                samples.append(sample)
        finally:
            gw._session.close()
        lat = sorted(s["ms"] for s in samples)
        good = [s for s in samples if s["ok"]]
        rows[model] = {"ok": len(good), "n": len(samples),
                       "p50_ms": lat[len(lat)//2], "p95_ms": lat[-1],
                       "p99_ms": lat[-1], "latency_scope": "all attempts including failures",
                       "avg_tokens": sum(s["tokens"] for s in good)//max(1, len(good)),
                       "samples": samples, "breaker": gw.breakers[model].snapshot()}
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
    key_present = bool(os.getenv(API_KEY_ENV, "").strip())
    if not ARGS.probes_only and not key_present:
        print(json.dumps({"error": API_KEY_ENV + " is unset; refusing to report a "
                          "live bench with zero real samples (use --probes-only)"}),
              file=sys.stderr)
        sys.exit(2)
    data = {"models": {} if ARGS.probes_only else bench(), "resilience": probes()}
    code = exit_code(data, key_present, ARGS.probes_only)
    data["verdict"] = {"exit_code": code, "probes_only": ARGS.probes_only}
    print(json.dumps(data, indent=2))
    out = ARGS.output or os.path.join(ROOT, "gateway_bench.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    sys.exit(code)
