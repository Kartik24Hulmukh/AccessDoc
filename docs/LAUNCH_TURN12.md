# AccessDoc -- Launch Turn 12: independent re-verification of main @ 2bb7784

**Verified September 15, 2026 17:19-17:24 UTC - Launch window September 16-17, 2026**

This turn re-ran every launch gate from a fresh clone of `main` (post PR #50) in a clean
sandbox, added a failover-latency benchmark with real percentiles, and probed the production
alias. No source code changed; evidence only. Machine-readable results: `docs/evidence/launch-turn12/`.

## Gates (fresh clone, Python 3.14, ResourceWarnings as errors)

| Gate | Result |
|---|---|
| `python -m unittest discover -s tests` | **722 tests OK, 0 failures**, 12 skipped (Playwright / production URL absent), 42.9 s |
| `scripts/verify_release.py` | all gates PASS (tests, secret_patterns, claims, placeholders, stale_files, immutable_action_refs, non_publishing_workflows, required_files, version_consistency) |
| `scripts/concurrent_bench.py` 100 workers x 200 mixed requests | **fault_recovery PASS** |
| GitHub Actions on `2bb7784` | lint success, smoke success |
| Production `https://access-doc.vercel.app` | `/healthz` 200 (105 ms), `/readyz` 200 (1.02 s cold), commit = `2bb7784` |

## 100-worker ingestion torture (local, shared-process client/server)

| Metric | Turn 11 | Turn 12 |
|---|---|---|
| P50 / P95 / P99 ms | 7501 / 12250 / 13848 | 9435 / 17108 / 17638 |
| req/s | 11.17 | 8.58 |
| RSS floor / ceiling / after MiB | 42.2 / 313.9 / 198.4 | 42.3 / 306.2 / 191.0 |
| Status histogram | 134x200, 33x413, 33x422 | 134x200, 33x413, 33x422 (identical) |
| Unexpected 5xx / transport errors / contract violations | 0 / 0 / 0 | 0 / 0 / 0 |
| Recovery probes | 200 / 200 | 200 / 200 |

Absolute latency is runner-dependent (this sandbox is slower); the invariants that matter for
zero-crash recovery -- exact rejection counts, bounded RSS, zero 5xx, healthy after the burst --
are unchanged for the third consecutive turn.

## Sub-200 ms failover on 429 / 5xx (new this turn)

Real `ModelGateway.chat()` path with a synthetic transport: primary returns the status, chain
model 2 returns 200. 1000 calls per status, `time.perf_counter` percentiles.

| Primary status | P50 ms | P95 ms | P99 ms | max ms | Primary breaker after |
|---|---:|---:|---:|---:|---|
| 429 | 0.020 | 0.031 | 0.043 | 0.149 | open after 1 failure |
| 500 | 0.018 | 0.023 | 0.028 | 0.139 | open after 3 |
| 502 | 0.017 | 0.022 | 0.030 | 2.391 | open after 3 |
| 503 | 0.017 | 0.019 | 0.026 | 0.100 | open after 3 |
| 504 | 0.017 | 0.022 | 0.025 | 1.507 | open after 3 |

Worst case 2.4 ms against a 200 ms ceiling; no `sleep` on the failover path; every call served by
the next chain model. Token-budget ceiling remains 6000 tokens per `chat()`.

## Live Melious chain canary (1 sample per model, real `chat()`, key from env only)

| Model | Served by requested model | Latency ms | Tokens | Breaker |
|---|---|---:|---:|---|
| GLM-5.3 | yes | 563 | 31 | closed |
| GLM-5.3 Flash | yes | 1995 | 90 | closed |
| Qwen 3.8 27B | yes | 1568 | 55 | closed |
| Kimi K3 | yes | 1292 | 178 | closed |

4/4, zero fallbacks. A single sample per model was chosen deliberately: the chain was already
benchmarked 12/12 in turn 11 and a canary, not a load test, is the right amount of third-party
traffic for a re-verification turn.

## Five-point premortem status

| Failure vector | Status |
|---|---|
| Large-file / expansion OOM | Bounded; 33/33 oversize rejected 413 under 100 workers; RSS ceiling 306 MiB, returns to 191 MiB |
| Worker starvation / deadlock | 0 admission retries, 0 transport errors, recovery 200/200 |
| Parsing / OCR stalls | Slow-drip cancellation + bounded parsing (PR #48); scope is axe JSON + manual findings |
| 429/5xx cascade / model spend | Failover P99 < 0.05 ms, breaker opens on first 429; live chain 4/4 |
| Secret / config / telemetry drift | JSON logs + traceparent verified in test output; `/healthz` `/readyz` live in production; **`gateway.configured=false` in production** |

## Launch decision

**Code: GO.** Every gate re-verified green from a clean clone; production serves the merged SHA.

**Operations: still blocked on the same items as turns 10 and 11**, none of which code can close:

1. Rotate both credentials disclosed in-band in the task prompts; they have now been used across three turns.
2. Install the *rotated* `MELIOUS_API_KEY` in the Vercel project so `/readyz` reports `gateway.configured=true`, then record an authenticated production canary.
3. OTel exporter/collector, spend and queue alerts, rollback rehearsal.
4. Named release/legal/security owners; external practitioner adoption gates.

No credential is committed in this document or under `docs/evidence/launch-turn12/`.
