# AccessDoc Launch Turn 13 - independent re-verification

Captured 2026-09-15T18:17:11Z from a fresh shallow-free clone of main @ 0a4764b335a73b5679d4565637559ec28c055d40 (PR #51 squash-merged). Work branch: harden/accessdoc-prod.

## Gates re-verified
- python3 -m unittest discover -s tests -q: **722 OK, 0 failures**, 12 skipped (optional Playwright browser tests unavailable in sandbox)
- scripts/verify_release.py: **10/10 PASS** (compile, tests, secret_patterns, claims, placeholders, stale_files, immutable_action_refs, non_publishing_workflows, required_files, version_consistency)
- scripts/concurrent_bench.py - 100 workers x 200 mixed tiny/medium/large/oversize/malformed payloads: **fault_recovery PASS**; histogram 134x200 / 33x413 / 33x422; unexpected_5xx 0; transport_errors 0; admission_retries 0; recovery /healthz=200 and /api/bundle=200
- Failover torture on injected 429/500/502/503/504 (1000 calls each through the real chat() path): all P99 far below the 200 ms failover ceiling; breaker opens on first 429 / third 5xx; zero sleep on path
- injected 429: n=1000 p50 0.0050 ms p95 0.0079 p99 0.0097 max 0.0408 (ceiling 200 ms), fallback glm-5.3-flash
- injected 500: n=1000 p50 0.0050 ms p95 0.0052 p99 0.0063 max 0.0174 (ceiling 200 ms), fallback glm-5.3-flash
- injected 502: n=1000 p50 0.0050 ms p95 0.0052 p99 0.0081 max 0.0246 (ceiling 200 ms), fallback glm-5.3-flash
- injected 503: n=1000 p50 0.0050 ms p95 0.0080 p99 0.0084 max 0.0157 (ceiling 200 ms), fallback glm-5.3-flash
- injected 504: n=1000 p50 0.0050 ms p95 0.0067 p99 0.0085 max 0.0160 (ceiling 200 ms), fallback glm-5.3-flash
- Live Melious chain canary (credential from $MELIOUS_API_KEY env only, 1 sample per model, never printed or committed): **4/4 success, 0 fallbacks**
- glm-5.3: 1/1 HTTP 200, p50 1506.5 ms, tokens 204
- glm-5.3-flash: 1/1 HTTP 200, p50 3865.8 ms, tokens 273
- qwen3.8-27b: 1/1 HTTP 200, p50 2964.7 ms, tokens 285
- kimi-k3: 1/1 HTTP 200, p50 4552.9 ms, tokens 399
- Production probes https://access-doc.vercel.app: /healthz 200 (131 ms), /readyz 200 (61 ms); served commit 0a4764b335a73b5679d4565637559ec28c055d40; gateway.configured=false

## Benchmark deltas vs Turn 12
| Metric | Turn 12 | Turn 13 |
|---|---|---|
| torture P50/P95/P99 (ms) | 9435/17108/17638 | 5537.29/10164.21/10922.41 |
| throughput (req/s) | 8.58 | 13.73 |
| RSS floor/ceiling/after (MiB) | 42.3/306.2/191.0 | 42.3/323.4/200.7 |
| failover P99 (ms) | 0.025-0.043 | <=0.0097 |
| live chain canary | 4/4 | 4/4 |
| prod probes | 200/200 | 200/200 |

## Five-point premortem (re-checked)
1. Large-file/expansion OOM: bounded 10 MiB ingress + ZIP/decoded caps; 33/33 oversize -> 413 under 100 workers; RSS returns toward floor.
2. Async worker deadlock/starvation: 0 admission retries, 0 transport errors, post-burst probes 200/200.
3. Parsing/OCR stalls: bounded parsing + strict wall-clock cancel; product scope is axe JSON/manual findings (no OCR path).
4. 429/5xx cascade/spend: sub-0.05 ms failover, breaker on first 429, 6000-token ceiling per chat, live chain 4/4.
5. Config/telemetry drift: structured JSON stdout logs + W3C traceparent verified; /healthz /readyz live; real OTel exporter remains an operator gate.

## Launch decision
**Code: GO** - every automated release gate green from a clean clone and the documented 100x resilience invariants hold.
**Production operations: NO-GO pending owner action (unchanged):** rotate both in-band credentials (Melious key + GitHub PAT) and reinstall a rotated gateway secret in the Vercel project so /readyz reports gateway.configured=true; stand up a real OTel collector + spend/queue/error alerts; rollback rehearsal and capacity/format certification; named release/security/legal approvals and practitioner adoption evidence.
No secret appears in this commit (verify_release secret_patterns PASS).
