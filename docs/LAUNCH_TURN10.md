# AccessDoc launch hardening — Turn 10 checkpoint

Date: 2026-09-15 UTC. Launch window: September 16–17, 2026.
Branch: `harden/accessdoc-prod`. Code commit: `1665af5`.
Release PR: https://github.com/Kartik24Hulmukh/AccessDoc/pull/49

## Executive verdict

**Local code validation passes; unqualified production launch remains NO-GO.**
The prior turn's PR #49 was open with every check successful at resumption. This turn
extends that same PR with a measured server-error failover fix and atomic rate-limit
breaker handling. Merge is gated on successful checks for the exact updated head.
No launch certification, immutable release publication or production configuration
change is implied by this hardening PR.

## Forensic reconciliation

- Main at resumption: `66b407a`; PR #48 merged; PR #49 head `8c86058`.
- Fresh checkout; all edits/commits on the required hardening branch. Numerous old
  remote feature/release branches remain; none were deleted or merged speculatively.
- Baseline: 718 tests, no failures, one optional production-health skip. With production
  URL and browser dependencies enabled: **720 tests, zero failures, zero skips**, 65.126 s.
  Includes real browser authenticated sample-to-bundle/accessibility tests, CLI/API/MCP,
  production health, hostile ZIPs and real-socket slow-drip regression.
- Focused gateway suite: 36/36. Standalone stress: 15/15. Release verifier: every gate PASS.
- `pip-audit -r requirements-dev.txt`: no known vulnerabilities across 14 resolved packages.
  This is a point-in-time advisory scan, not proof of absence of vulnerabilities; requirements
  still use ranges and production dependency reproducibility is a remaining concern.
- Production `/healthz` and `/readyz`: 200 at `66b407a`, **gateway.configured=false**.
  A 200 readiness response proves the deterministic API, not configured AI remediation.

## Resolved failure logs and atomic change

1. Before: HTTP 500/503 retried the failed provider three times with exponential jitter.
   Five injected-transport samples measured 503 P50 **2151.514 ms**, P95/P99 **2247.455 ms**,
   five total provider calls per request (four failing + one healthy).
2. After: 429 and every server error route onward immediately; 408 retains bounded retry
   and shared deadline/token checks. 503 P50 **0.009 ms**, P95/P99 **0.010 ms**, two calls.
   Local 429 P95/P99 **0.035 ms**; 500 P95/P99 **0.012 ms**; 504 P95/P99 **0.010 ms**.
   These isolate routing overhead with telemetry mocked, not network response time or an SLO.
3. Before: the rate-limit path repeatedly called `record_failure()` until OPEN, fabricating
   failure counts and allowing an unbounded race with concurrent success resets.
   After: `CircuitBreaker.trip()` increments once and opens under one lock. A 200-operation,
   100-worker regression verifies exact failure counts and subsequent recovery.
4. Regression tests assert one constrained-model call, no sleeps and <200 ms local routing.
   Existing 100-worker shared-gateway outage/recovery regression remains green.
   One code remediation cycle; no module exceeded the five-cycle cap.

## Ingestion benchmark (actual mixed-size, not multi-format OCR)

200 requests/run; 100 thread-pool workers; seed 7. Axe JSON tiny/medium/large, hostile
markup, malformed JSON and oversized bodies. No real model calls occur in this ingestion
benchmark. Old report attribution of ingestion timings to reasoning-model variance is
not supported by this script. Baseline ran alongside other tests; patched runs were
sequential. Deltas are descriptive and not attributable to gateway changes.

| Run | P50 / P95 / P99 ms | req/s | RSS floor / peak / after MiB |
|---|---|---:|---|
| Before (`8c86058`) | 6166.31 / 10905.38 / 11490.02 | 12.68 | 42.3 / 321.7 / 212.0 |
| After 1 | 5531.02 / 9515.74 / 10594.25 | 13.86 | 42.4 / 297.6 / 182.8 |
| After 2 | 5650.75 / 10109.92 / 10713.62 | 13.80 | 42.3 / 316.4 / 207.8 |
| After 3 | 5743.08 / 10177.99 / 10567.69 | 13.73 | 42.2 / 299.8 / 201.8 |

Every run: 134 HTTP 200, 33 HTTP 413, 33 HTTP 422; zero unexpected 5xx, transport errors,
transport-attempt errors or contract violations; fresh health and bundle recovery both 200.
The three after runs restart the process: **not a same-process RSS plateau proof** and not
100 times a measured production baseline. Memory measurement includes client and server.

Additional 30 s/adapter, 32-worker authenticated loopback soak with 100 finding instances:
- Serverless adapter: 1,064 valid bundles, 4,932 explicit 503 admission rejections; 35.29 successful bundles/s.
- Self-hosted adapter: 1,053 valid bundles, 4,629 explicit 503 admission rejections; 34.90 successful bundles/s.
- Both: zero invalid bundles/transport errors, every 503 has Retry-After, fresh recovery 200.
- Sampled RSS ranges: 54.9–61.3 MiB and 68.7–86.4 MiB respectively, ending near peak.
  Sustained plateau is **not established**. An attempted 100-worker soak invocation was
  correctly rejected by that script's 32-worker limit; the separate benchmark above uses 100.

## Five-point premortem and remaining controls

| Failure vector | Verified control | Residual gate |
|---|---|---|
| Large input / expansion OOM | 10 MiB ingress cap, ZIP/decoded-body bounds; hostile tests and 413 stress pass | Deployed same-process soak and cgroup/RSS plateau |
| Worker starvation / deadlock | Bounded admission; 100-worker recovery; exact atomic breaker transitions | Production DNS/connect stalls and sustained queue saturation |
| Slow parsing / OCR | Real-socket slow-drip cancellation; bounded axe parsing and ZIP validation | Current service is axe JSON + manual findings, not a general PDF/DOCX/OCR ingestion service; roadmap's other importer claims need reconciliation |
| 429/5xx cascade / expensive models | Immediate routing after error, token/deadline checks, connection reuse, static fallback | End-to-end <200 ms impossible for slow network windows; provider spend ceilings are not proven by returned usage alone |
| Secret/config/telemetry drift | JSON logs, W3C context and health probes present | Rotate credentials, install production key; configure actual OTel SDK/exporter/collector and alert routes; verify exported trace continuity |

## Launch and traction gates (not replaced by green CI)

1. Rotate both disclosed credentials immediately. They were used only for authorized Git
   delivery and bounded synthetic gateway testing in this run, never installed into production
   or committed. The earlier verification attachment actually includes plaintext secrets despite
   claiming otherwise; treat it as sensitive and restrict/delete it according to retention policy.
2. Install only the rotated provider key in Vercel Production, redeploy exact approved SHA,
   verify configured=true, then capture authenticated remediation canary with model, latency,
   usage and fallback. Do not blindly increase global timeout beyond the hosting execution limit.
3. Establish provider availability/quotas, collector/exporter and spend/queue/error alerts. Existing
   optional OTel API integration does not prove a deployed SDK or correctly linked exported traces.
4. Certify staging/production-equivalent capacity, parser formats actually supported, rollback,
   independent AppSec and keyboard/screen-reader/PDF reviews; publish immutable SBOM/provenance.
5. Assign named release/legal/security owners. Run roadmap adoption gates: 4/5 practitioners
   install and generate within 15 min; 4/5 accept sanitized real evidence; 3 deliver with <=30 min
   editing; 2 repeat within 30 days; one external contribution. No traction claims were fabricated.

## Reproduction and evidence

Install `requirements-dev.txt`, Playwright Chromium and axe-core 4.11.0. Set
`ACCESSDOC_AXE_PATH` to the installed axe.min.js; set `ACCESSDOC_PRODUCTION_URL` for the live
health test. Run unittest discovery with ResourceWarnings as errors, `scripts/stress_test.py`,
`scripts/verify_release.py`, `scripts/concurrent_bench.py`, `scripts/hardening_load.py`,
`scripts/hosted_soak.py --seconds 30 --workers 32`, and `scripts/routing_delta_bench.py`.
Live provider benchmarking uses only the credential environment variable and three samples/model.
Machine-readable evidence lives in `docs/evidence/launch-turn10/`.

## Live Melious benchmark (this run)

Synthetic WCAG prompt, 25 s per-chat budget, three samples per model, pooled sessions.
Percentiles include failures; n=3 P95/P99 are simply the sample maximum, not an SLO.
Model identifiers below are the actual configured gateway identifiers.

| Model | Success | P50 / P95 / P99 ms | Mean successful tokens | Breaker |
|---|---:|---|---:|---|
| glm-5.3 | 0/3 | 15273.69 / 15342.14 / 15342.14 | 0 | open |
| glm-5.3-flash | 3/3 | 22762.74 / 24889.67 / 24889.67 | 1076 | closed |
| qwen3.8-27b | 3/3 | 10868.31 / 11008.47 / 11008.47 | 1075 | closed |
| kimi-k3 | 3/3 | 20141.34 / 24550.84 / 24550.84 | 1193 | closed |

GLM-5.3 timed out on all three requests near the 15 s read window; the other three
models succeeded 3/3. This does not establish sustained availability. Deterministic
429-storm, outage fail-fast (0.1 ms) and static fallback probes passed.
No production secret was installed and no production ingestion endpoint was load-tested.
