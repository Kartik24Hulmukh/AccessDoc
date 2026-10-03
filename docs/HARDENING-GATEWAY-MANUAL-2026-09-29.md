# Gateway and manual-table hardening receipt

Local continuation from `803aadb` on `harden/accessdoc-v1-launch`. The current launch target is October 2026. This receipt records engineering evidence, not hosted launch approval or customer traction.

## Frozen baseline and independent review

Before edits, the browser-enabled suite passed **864 tests**, with **1 production-target skip**, **155 subtests**, and three warnings in **71.39 seconds**. Two parallel AI reviewers performed read-only gateway and adapter/parser reviews. They are not human evaluators, practitioner acceptance, or independent release signatories.

Each defect below was reproduced before its fix. Baseline source was preserved separately from the working tree; regression failure logs and runnable local measurement scripts are in `docs/evidence/gateway-manual-hardening/`.

## Implemented changes

1. **`d6f7a33` — Error-body deadlines.** The 429 billing classifier previously used `raw.read(4096)`, which could remain active beyond the request budget when bytes trickled in. Error peeks now use the same absolute-deadline, decoded-byte-bounded reader as success responses. A 402 is classified from its status without reading its optional body. Responses are closed on success, rejection, and timeout; the next request recovers through the existing pool. Prefix truncation preserves ordinary rate-limit routing without buffering the full error response.
2. **`1a5215a` — Epoch-scoped circuit admissions.** An older 200 could previously erase a newer 429 trip. Each production attempt and retry now acquires an admission epoch. Stale outcomes remain observable in counters but cannot change circuit state or recovery backoff. A current half-open success invalidates sibling probes; an abandoned probe releases its admission. Timeout weighting and its single observed-failure count are updated atomically. Tests cover the event-controlled race, half-open impersonation, late sibling failure, blocked retries, abandoned admissions, and 100 concurrent stale successes.
3. **`89b010d` — Streaming manual tables.** CSV `DictReader` padding and Markdown row padding previously retained full-width dictionaries before checking the finding limit. Both formats now iterate rows, project only recognized columns, convert accepted findings directly, and stop at row 5,001. No intermediate list of full-width dictionaries is created. Existing aliases, quoted CSV cells, duplicate-header behavior, missing optional cells, and exactly 5,000 findings remain covered. Both real-socket adapters reject oversized wide tables with 413 before any renderer call.

No new runtime dependency, database migration, crawler, or general OCR pipeline was added.

## Measured results

### Deadline reproduction: three samples per status, real loopback HTTP

The budget was 100 ms; the local upstream sent one byte every 20 ms. These tiny-sample percentiles are descriptive order statistics, not a provider SLO.

| Status | Baseline p50 / p95 / p99 ms | After p50 / p95 / p99 ms | Result |
|---|---|---|---|
| 429 | 808.211 / 811.690 / 811.690 | 101.270 / 101.275 / 101.275 | Timeout enforced; reusable pool recovers |
| 402 | 808.003 / 808.296 / 808.296 | 1.349 / 1.450 / 1.450 | Classified immediately without consuming body |

The isolated pre-fix regression also measured a separate 100-byte 402 body taking 2.003 seconds. It is a different fixture, not mixed into the percentile table.

### Manual-table amplification: one sample per format, shared parser

These are Python `tracemalloc` peaks, **not process RSS or deployed capacity**. Both versions rejected the same 5,001-row input.

| Format | Input bytes | Baseline peak traced bytes | After peak traced bytes | Baseline / after ms |
|---|---:|---:|---:|---:|
| CSV | 14,890 | 130,394,214 | 1,135,328 | 349.532 / 37.371 |
| Markdown | 26,900 | 130,638,544 | 1,173,787 | 301.965 / 55.941 |

This demonstrates removal of the reproduced header-width allocation amplification. It does not establish an arbitrary-document memory ceiling.

### Application validation

- Full browser-enabled suite: **884 passed, 1 skipped, 159 subtests**, three warnings, **73.92 seconds**. The skip still requires the exact production target.
- Focused gateway/manual regression suite: **132 passed**, **27 subtests**.
- Final loopback load: eight workers, 100 requests, **100 HTTP 200**, one deterministic bundle digest; **82.54 requests/s**, p50/p95/p99 **46.7 / 72.3 / 81.3 ms**, maximum **1,021.6 ms**.
- Warm idle RSS **34,580 KiB**, process-lifetime measured peak **42,032 KiB**, post-load RSS **41,984 KiB**. These are observations, not enforced ceilings.
- The prior continuation's single loopback run was 165.02 requests/s, p50/p95/p99 47.6/65.2/66.1 ms, idle/peak/post-load RSS 34,636/44,992/44,964 KiB. The present run overlapped full-suite validation and is not a controlled throughput comparison: **no throughput improvement is claimed**.
- Final synthetic chaos: **100 workflows, 40 disconnects**, zero captured unhandled thread exceptions, server errors, or surviving new threads. Recovery probes: `/healthz` **1.58 ms**, `/readyz` **1.26 ms**. Not 100 real people, not a coroutine-leak proof, and not a deployed-provider recovery measurement.
- Adversarial stress: **15 checks, zero failures**.
- Offline gateway resilience probes passed. No credentialed provider call was made.

The strict verifier passed **10/10 local gates**, including **868 unittest cases (1 skipped)** in 65.856 seconds. Its final result is stored separately in `release-verifier.json`; local checks must not be substituted for live or human gates.

## Five-point premortem disposition

1. **Large-file memory exhaustion:** the reproduced small-CSV/wide-header amplification is removed in both manual-table formats. HTTP body bounds and scanner limits remain. Sustained hosted capacity and arbitrary multi-format/OCR ingestion are not certified.
2. **Worker deadlocks and stale concurrent outcomes:** circuit admissions are generation-bound; abandoned recovery trials and retry admissions are covered. Synthetic socket shutdown has no captured thread leak. Active hedged-request cancellation, DNS timing, and all external worker lifecycles are not universally certified.
3. **OCR/parsing/provider timeouts:** general OCR ingestion is not a current product surface. 429 error bodies now share the deadline-aware bounded reader, and 402 does not wait for a body. Live Kimi K3 availability remains a separate failed gate.
4. **429/5xx cascades and spend:** stale completions cannot erase cooldowns; existing immediate-failover and token-budget regressions pass. These tests do not certify the provider's actual billing or four-model production behavior.
5. **False readiness and traction:** local tests are labeled explicitly. Practitioner acceptance, real-human evaluation, exact-SHA canary/rollback, and named legal/security/accessibility approvals remain incomplete. No adoption or revenue result is claimed.

## `repos.md` integration disposition

The preceding continuation reviewed the supplied catalog and selected the existing Playwright and axe-core integration for a real scan → bundle → verify handoff, with `examples/agency-handoff/README.md`. That decision remains unchanged. This continuation adds no catalog dependency: these failures require native bounded parsing and concurrency ownership, not another agent/OCR/plugin framework. See `docs/HARDENING-REMEDIATION-HANDOFF-2026-09-29.md` for the integration rationale and rejected categories.

## Reproduction and rollback

Run with the project's installed Python environment:

```bash
python -m pytest -q
python -m pytest -q tests/test_gateway_error_deadlines.py tests/test_gateway_breaker_epochs.py tests/test_manual_streaming_bounds.py
python scripts/verify_release.py
python scripts/hardening_load.py --output load.json
python scripts/disconnect_chaos.py --output chaos.json
python scripts/stress_test.py
python scripts/gateway_bench.py --probes-only --output gateway-probes.json
python docs/evidence/gateway-manual-hardening/error_deadline_bench.py /path/to/checkout
python docs/evidence/gateway-manual-hardening/manual_memory_bench.py /path/to/checkout
```

Run the last two commands against separate baseline (`803aadb`) and candidate checkouts; they use only local upstreams and test credentials. Rollback consists of reverting the three fix commits; there is no schema migration. Reverting would restore the reproduced vulnerabilities and is not recommended as a launch path.

## Release decision and delivery boundary

**HOLD public launch and auto-merge.** The remotely inspected PR #95 is open/draft at `1ae62eb6d24857052bf11a4a642b99ce3fa4b9ed`, with failing `accessdoc/live-gateway`: “11/12 live completions; K3 HTTP 504 at 40s budget. Launch hold.” Vercel's deployment-success status does not certify the new local commits or their exact deployed target.

The fixes are local and must be pushed through authorized Git credentials, then hosted CI and four-model live verification must be rerun. No Git/provider credential or production URL was injected in this environment. Previously disclosed credentials should be rotated and supplied through the deployment's secret manager, not copied into source, evidence, or PR prose. Complete exact-SHA deployed-target/rollback verification and the repository's human release gates before marking the release ready.

This receipt is also the factual draft for the release PR update: integrations, risk dispositions, measurements and limitations, rollback, and launch verification status are included above.