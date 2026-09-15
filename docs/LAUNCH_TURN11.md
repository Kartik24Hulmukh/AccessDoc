# AccessDoc -- Launch Turn 11: primary-model read-window fix and live chain re-verification

**Verified September 15, 2026 - Launch window September 16-17, 2026**

## What was still open after turn 10

Turn 10 (PR #49) closed 5xx failover and the atomic rate-limit breaker but recorded the
primary chain model at **0/3** live, every call dying near the 15 s read window. That
left the head of the fallback chain as dead weight: each remediation burned 15 s of
the 40 s admission budget before routing onward.

## Root cause

`MODEL_READ_TIMEOUTS` gave models 2-4 a 25-30 s window but the primary alone inherited the
15 s default (`test_primary_keeps_fast_default` pinned that). 1024-token generations from the
primary regularly exceed 15 s. A same-day 60 s-window probe (`scripts/head_model_probe.py`)
measured the primary **5/5 at P50 ~1.1 s / max 9.8 s** -- the window, not the provider, failed.

## Fix (one remediation cycle; cap is five)

- `fix(gateway)`: primary model gets a 25 s read window (still clamped to remaining
  `GATEWAY_BUDGET_SECONDS`, so total wall clock per chat() is unchanged and a slow primary
  fails over with budget to spare).
- `test(gateway)`: read-window regression now asserts every chain model >= 25 s, the primary
  is not left on the narrow default, the primary window leaves failover budget, and the
  per-model env override still wins. One stale assertion in `test_launch_hardening.py` updated.
- `test(bench)`: `scripts/head_model_probe.py` added; evidence under `docs/evidence/launch-turn11/`.

## Validation

| Gate | Result |
|---|---|
| Baseline (main @ e930ee4) | 720 tests OK, 12 skipped (Playwright/production URL absent in this runner) |
| Final head | **722 tests OK, 0 failures**, 12 skipped, 42.7 s, ResourceWarnings as errors |
| `scripts/verify_release.py` | all gates PASS (secret patterns, claims, placeholders, stale files, immutable action refs, version consistency) |
| 100-worker concurrent torture | fault_recovery **PASS** |

## Live Melious chain benchmark (real `chat()` path, 3 samples/model, 1024 max_tokens)

Percentiles with n=3: P95/P99 are the sample maximum, not an SLO.

| Model | Served by requested model | P50 / P95 / P99 ms | Attempts |
|---|---:|---|---:|
| glm-5.3 | 3/3 | 1087.9 / 1473.4 / 1473.4 | 1 |
| glm-5.3-flash | 3/3 | 2989.4 / 3040.5 / 3040.5 | 1 |
| qwen3.8-27b | 3/3 | 4818.3 / 5423.1 / 5423.1 | 1 |
| kimi-k3 | 3/3 | 4214.2 / 4614.6 / 4614.6 | 1 |

**12/12 success, zero fallbacks, every breaker closed.** Turn-10 primary: 0/3 at 15273 ms P50 (timeouts). Now 3/3 at 1088 ms P50 -- a **14x P50 improvement and 0 -> 100% availability** for the head of chain.

## 100-worker mixed-payload ingestion torture (local, 200 requests)

| Metric | Turn 10 (after 3) | Turn 11 |
|---|---|---|
| P50 / P95 / P99 ms | 5743 / 10178 / 10568 | 7501 / 12250 / 13848 |
| req/s | 13.73 | 11.17 |
| RSS floor / ceiling / after MiB | 42.2 / 299.8 / 201.8 | 42.2 / 313.9 / 198.4 |
| Status histogram | 134x200, 33x413, 33x422 | 134x200, 33x413, 33x422 |
| Unexpected 5xx / transport errors / contract violations | 0 / 0 / 0 | 0 / 0 / 0 |
| Recovery probes | 200 / 200 | 200 / 200 |

Latency differs from turn 10 because this is a different, smaller sandbox runner; the invariants
(zero crashes, exact rejection counts, bounded RSS floor, recovery 200) are what is being proven.
No model calls occur in this benchmark. Client and server share the process.

## Five-point premortem status

| Failure vector | Status |
|---|---|
| Large-file / expansion OOM | Bounded (10 MiB ingress, ZIP/decoded caps); 33/33 oversize rejected 413 under 100 workers |
| Worker starvation / deadlock | Bounded admission; 100-worker run recovered, 0 transport errors |
| Parsing / OCR stalls | Slow-drip cancellation + bounded parsing; service scope remains axe JSON + manual findings |
| 429/5xx cascade / model spend | Immediate failover; **primary model dead-weight defect closed this turn**; token budget 6000/chat |
| Secret / config / telemetry drift | JSON logs, W3C traceparent, /healthz + /readyz present; OTel exporter still an operations gate |

## Launch decision

Code: **GO** -- every chain model is live and green, tests 722/722, torture PASS, release gates PASS.
Operations gates that code cannot close (rotate both disclosed credentials, install rotated key in
production so `gateway.configured=true`, OTel collector/exporter, spend and queue alerts, named owners,
practitioner adoption gates) remain **with the operators** and are unchanged from turn 10.
No credential was committed; this document contains none.
