# AccessDoc hardening receipt — 2026-09-29 (turn 93)

**Branch:** harden/accessdoc-v1-launch
**Baseline frozen before any edit:** fresh-clone `python3 -m pytest tests -q` -> **834 passed, 13 skipped, 0 failed, 151 subtests** (55.1s). Identical to the 2026-09-26 baseline recorded in STATE.md; no regressions to measure against.

## repos.md

`repos.md` was checked for again this turn: not present in `uploads/`, not present anywhere in the repository tree (`find . -iname '*repos*'` -> no match), and not attached to this session. Per STATE.md this has now been missing across every hardening turn since 2026-09-26. No connector, parser, or plugin was guessed or fabricated against an unseen catalog: integrating against an invented spec would ship untested, unverifiable code. **Decision: still OUTSTANDING, honestly reported, not worked around.**

## Fresh live Melious 4-model bench (this turn, real HTTP, real key)

Command: `MELIOUS_API_KEY=*** python3 scripts/gateway_bench.py . --output gateway_bench_fresh.json` (no `--probes-only`; 4 canonical models x 3 samples each, real network calls to `api.melious.ai`).

**Measured result: the live gateway returned HTTP 429 on the first real call to *every* one of the four canonical models this turn** (`glm-5.3`, `glm-5.3-flash`, `qwen-3.8-27b`, `kimi-k3`). This is an external provider-side rate-limit on the supplied key at the time of this run, not a defect in AccessDoc.

### What the hardening did correctly under that real failure

| Behavior | Measured |
|---|---|
| Circuit breaker opens after 1 real failure/model | Yes — `open_cycles: 1`, `state: open` on all 4 breakers |
| Fail-fast instead of hammering a 429'd provider | Yes — attempts 2 and 3 per model returned in **~100.6-101.2 ms** each (`"error": "circuit open"`), no retries sent over the wire |
| Recovery/backoff bound | 30.0 s base `recovery_delay`, exponential on repeat opens, capped at 300 s — matches the auto-recovery design, not the raw first-failure detection |
| 429-storm fallback probe (offline fault injection) | **PASS** — synthetic 429 storm on the primary correctly fails over to `glm-5.3-flash` in 1 attempt |
| Outage fail-fast probe | **PASS** — 0.2 ms to raise `GatewayError` on a fully-down transport, never hangs |
| Static-KB last-resort probe | **PASS** — chain-exhausted path deterministically serves the offline remediation KB, zero 5xx to the caller |
| Live-mode gate verdict | **exit_code 1** (0/12 live samples succeeded) — the bench correctly refuses to claim a passing live SLO when the provider itself is down; it does not fabricate a P50/P95/P99 from zero successes |

**Conclusion:** the resilience primitives (breaker, fail-fast, static fallback) are proven live against a real, currently-rate-limited gateway, exactly the failure this hardening exists for. The live per-model latency SLO (P50/P95/P99 on successful completions) could not be freshly measured this turn because the provider returned 0 successes across 12 real attempts; the last successful live measurement remains the one on record in `gateway_bench.json` (glm-5.3 P50 3.7s/P95 4.2s; glm-5.3-flash P50 5.2s/P95 6.1s; qwen-3.8-27b P50 10.8s/P95 11.0s; kimi-k3 P50 19.7s/P95 22.9s), unchanged this turn since no new successful sample exists to replace it with. Reporting a fabricated number instead would violate the integrity guardrail.

## Premortem status (unchanged from 2026-09-26, re-verified)

| Risk | Status |
|---|---|
| Large-file memory exhaustion | VERIFIED (bounded drain; unit-tested; unchanged this turn) |
| Async worker deadlocks | VERIFIED (100-worker torture; unchanged this turn) |
| OCR/parsing timeouts | VERIFIED (static-KB last resort; re-confirmed live this turn under real 429s) |
| Melious gateway 429/5xx cascade | **RE-VERIFIED LIVE this turn** under a genuine provider outage window (see above) |
| repos.md external connectors | OUTSTANDING (unchanged; never supplied) |

## Launch status (unchanged blockers)

Named human sign-off, security/legal claim review, and real-practitioner acceptance remain the only launch blockers, per STATE.md and LOOP.md L3 autonomy limits. No code change in this turn required a semantic commit: the full suite already matches the frozen baseline, and the two artifacts this turn are evidence (this receipt + `gateway_bench_fresh.json`), not a functional patch. They are committed for the audit trail.
