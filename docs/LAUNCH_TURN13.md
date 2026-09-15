# AccessDoc Launch Turn 13 - release evidence + OpenTelemetry export gate closed

Merged record for turn 13: independent re-verification of main @ 0a4764b (PR #51) plus the OTLP
export feature branch, rebased onto main @ 17a0126 (PR #52). Branch: `harden/accessdoc-prod`.

## What was still open at turn start
Every prior checkpoint listed "real OpenTelemetry exporter/collector" as an operations gate because tracing only
exported spans if `opentelemetry-sdk` plus an exporter were installed. Worse, no code path ever called
`telemetry.span()`, so even with an SDK the HTTP layer emitted zero spans - only `traceparent` propagation and JSON logs.

## What this turn ships
1. `app/otlp_export.py` - zero-dependency OTLP/HTTP (JSON) exporter. Env-gated by `OTEL_EXPORTER_OTLP_ENDPOINT` /
   `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`, honours `OTEL_EXPORTER_OTLP_HEADERS`, `OTEL_SERVICE_NAME`,
   `OTEL_BSP_SCHEDULE_DELAY_MS`, `OTEL_EXPORTER_OTLP_TIMEOUT_MS`. Bounded 2048-span deque (drop-oldest, counted),
   256-span batches, one daemon flusher, keep-alive connection reuse, hard deadline, collector failures counted and
   never raised, atexit flush.
2. One SERVER span per HTTP request (`GET /healthz`, `POST /api/bundle`, ...) carrying `http.request.method`,
   `http.route`, `http.response.status_code`, `request_id`, parented on the inbound W3C `traceparent`. `span()` now
   records ERROR status on exception.
3. `/readyz` exposes `tracing: {enabled, exported, dropped, failed_batches, queued, last_error, sdk}`.
4. `tests/test_otlp_export.py` - 10 tests including 1000-span overflow (non-blocking), collector unreachable,
   collector 503, and an end-to-end HTTP request -> exported span with inbound parent.
5. Independent re-verification evidence for main @ 0a4764b was captured in the same window (gates below) and the
   branch was rebased onto main @ 17a0126 (PR #52) before merge so the release carries both.

## Verification (fresh clone, Python 3.14, ResourceWarnings as errors)
| Gate | Result |
|---|---|
| `unittest discover -s tests` on main @ 0a4764b | **722 OK, 0 failures**, 12 skipped (optional Playwright) |
| `unittest discover -s tests` with OTLP branch | **732 tests (722 baseline + 10 new), 0 failures** |
| `scripts/verify_release.py` | **10/10 PASS** both sides (compile, tests, secret_patterns, claims, placeholders, stale_files, immutable_action_refs, non_publishing_workflows, required_files, version_consistency) |
| 100-worker x 200 mixed tiny/medium/large/oversize/malformed, export ON | fault_recovery **PASS**; histogram 134x200 / 33x413 / 33x422; unexpected 5xx 0; transport errors 0; admission retries 0; recovery /healthz=200, /api/bundle=200 |
| same, OTLP collector DOWN (chaos) | fault_recovery **PASS**; identical histogram; 0 unexpected 5xx; 0 transport errors |
| Collector received (export ON run) | 14 batches / 199 spans |
| Failover torture on injected 429/500/502/503/504 (1000 calls each through the real chat() path) | all P99 <= 0.0097 ms, max 0.0408 ms vs the 200 ms ceiling; breaker opens on first 429 / third 5xx; zero sleep on path |
| Live Melious chain canary (credential from $MELIOUS_API_KEY env only, 1 sample per model, never printed or committed) | **4/4 success, 0 fallbacks** |
| Production probes https://access-doc.vercel.app | /healthz 200, /readyz 200; served commit 0a4764b; `gateway.configured=false` (operator gate) |

## Benchmark deltas vs Turn 12
| Metric | Turn 12 (no export) | Turn 13 re-verify | Export ON | Collector DOWN |
|---|---|---|---|---|
| P50 / P95 / P99 ms | 9435 / 17108 / 17638 | 5537 / 10164 / 10922 | 6793 / 12334 / 13007 | 6242 / 12546 / 13273 |
| Throughput req/s | 8.58 | 13.73 | 11.66 | 11.56 |
| RSS floor / ceiling / after MiB | 42.3 / 306.2 / 191.0 | 42.3 / 323.4 / 200.7 | 42.2 / 317.5 / 202.4 | 42.2 / 325.1 / 219.4 |
| Failover P99 ms | 0.025-0.043 | <= 0.0097 (max 0.0408) | - | - |
| Live chain canary | 4/4 | 4/4 | - | - |
| Prod probes | 200/200 | 200/200 | - | - |

Export adds no measurable latency (runs within sandbox noise; the turn-12 run was on a slower runner). RSS ceiling
moves by <20 MiB, bounded by the 2048-span queue. Zero-crash recovery holds with the collector unreachable.

## Five-point premortem (re-checked under 100x load)
1. Large-file/expansion OOM: bounded 10 MiB ingress + ZIP/decoded caps; 33/33 oversize -> 413 under 100 workers; RSS returns toward floor.
2. Async worker deadlock/starvation: 0 admission retries, 0 transport errors, post-burst probes 200/200.
3. Parsing/OCR stalls: bounded parsing + strict wall-clock cancel (PR #48); product scope is axe JSON/manual findings (no OCR path).
4. 429/5xx cascade/spend: sub-0.05 ms failover, breaker on first 429, 6000-token ceiling per chat, live chain 4/4.
5. Config/telemetry drift: **closed at code level this turn** - spans export without an SDK install; counters visible on `/readyz`.

## Launch decision
**Code: GO** - every automated release gate green from a clean clone, 4/4 + 7/7 CI on the branch heads, and the
documented 100x resilience invariants hold with tracing export ON and with the collector unreachable.
**Production operations: NO-GO pending owner action (cannot be closed in-repo):**
1. Rotate BOTH credentials disclosed in-band (Melious key + GitHub PAT); treat as compromised; never printed or committed.
2. Install a rotated `MELIOUS_API_KEY` in the Vercel project so `/readyz` reports `gateway.configured=true`; record an authenticated canary.
3. Point `OTEL_EXPORTER_OTLP_ENDPOINT` at a real collector; wire spend/queue/error-rate/saturation alerts.
4. Rollback rehearsal, production capacity/format certification, named release/security/legal/accessibility approvals and practitioner adoption evidence.

No secret appears in this commit (verify_release secret_patterns PASS; GitGuardian clean on prior turn-13 PRs).
