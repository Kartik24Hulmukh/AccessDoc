# AccessDoc Turn 14 - harden/accessdoc-prod rebased onto main @ 17a0126 + full re-verification

Date: 2026-09-15 (UTC), pre-launch window Sep 16-17. This closes the single open item from the turn-13
code checkpoint: PR #53 could not merge because `main` advanced from `0a4764b` to `17a0126` (PR #52
squash-merged) while its checks ran, leaving the branch `mergeable=false / dirty`.

## What was done
1. Rebased `harden/accessdoc-prod` (4 commits: 24d8f6f / 7e91fe0 / f2bd31b / f94787c) onto `main @ 17a0126`.
   The single content conflict was `docs/LAUNCH_TURN13.md` (add/add: PR #52 also landed a turn-13 record).
   Resolution: one merged narrative carrying both records (independent re-verification + OTLP export gate).
   No code files conflicted; the four commits are now `469b9d7 / 884c458 / 102a298 / 75ed0e1`.
2. Re-verified everything from the rebased tree in a fresh run (same sandbox, Python 3.14.6,
   ResourceWarnings as errors).

## Post-rebase validation
| Gate | Result |
|---|---|
| `unittest discover -s tests` | **732 tests, 0 failures, 0 errors**, 12 skipped (optional Playwright) - 41.5 s via verify_release |
| `scripts/verify_release.py` | **10/10 PASS** (compile, tests, secret_patterns, claims, placeholders, stale_files, immutable_action_refs, non_publishing_workflows, required_files, version_consistency) |
| 100-worker x 200 mixed tiny/medium/large/hostile/oversize/corrupt, OTLP export ON (live stub collector on 127.0.0.1:4318) | fault_recovery **PASS**; histogram 134x200 / 33x413 / 33x422; unexpected 5xx 0; transport errors 0; admission retries 0; recovery /healthz=200 /api/bundle=200 |
| Same, collector UNREACHABLE (chaos, http://127.0.0.1:49999) | fault_recovery **PASS**; identical 134/33/33 histogram; 0 unexpected 5xx; 0 transport errors |
| Injected 429/500/502/503/504 failover (1000 calls each, real `chat()` path) | P50 0.0049 ms; P99 <= 0.011 ms; worst sample 0.0413 ms vs 200 ms ceiling - **pass on every status** |
| Live Melious chain canary (env-only credential, 1 sample/model) | **4/4 HTTP 200, 0 fallbacks**, all breakers closed |
| Production probes https://access-doc.vercel.app | /healthz 200, /readyz 200; served commit **17a0126** (PR #52 merged); `gateway.configured=false` remains the operator gate |

## Benchmark deltas (turn-12 baseline -> this run)
| Metric | Turn 12 | Turn 13 re-verify (PR #52) | This run: export ON | This run: collector DOWN |
|---|---|---|---|---|
| P50 / P95 / P99 ms | 9435 / 17108 / 17638 | 5537 / 10164 / 10922 | 9194.7 / 18195.3 / 19062.8 | 9479.1 / 17260.8 / 18022.4 |
| Throughput req/s | 8.58 | 13.73 | 8.13 | 8.53 |
| RSS floor / ceiling / after MiB | 42.3 / 306.2 / 191.0 | 42.3 / 323.4 / 200.7 | 42.1 / 325.5 / 211.2 | 41.6 / 309.0 / 191.5 |

Runner-dependent absolutes: this sandbox run is slower than the PR #52 runner but consistent with the turn-12
baseline on the same harness; the invariants that matter (contract histogram exact, 0 unexpected 5xx,
0 transport errors, bounded RSS, clean post-burst recovery, exporter non-blocking) hold identically with the
collector up and unreachable. RSS ceiling is within noise of prior turns (bounded 2048-span queue).

## Launch verification status
- **Code: GO.** The hardening line and `main` are now the same tree plus these 4 commits; 732/732 green,
  release verifier 10/10, torture PASS with tracing export ON and with the collector dead, failover and
  live-chain gates re-proven post-rebase.
- **Production ops: NO-GO pending owner action (unchanged, cannot be closed in-repo):** rotate the in-band
  Melious key and GitHub PAT (treat as compromised), install the rotated `MELIOUS_API_KEY` in Vercel so
  `/readyz` reports `gateway.configured=true`, point `OTEL_EXPORTER_OTLP_ENDPOINT` at a real collector and wire
  spend/queue/error alerts, rollback rehearsal, named release/security/legal/accessibility approvals.

## Evidence (this commit)
- `docs/evidence/launch-turn13/concurrent_torture_otlp_export_on.json` - 100x torture, collector up
- `docs/evidence/launch-turn13/concurrent_torture_otlp_collector_down.json` - chaos variant
- `docs/evidence/launch-turn13/failover_latency.json` - 5x1000 injected-status failover
- `docs/evidence/launch-turn13/live_chain_canary.json` - live 4-model canary (no credential material)
- `docs/evidence/launch-turn13/production_probe.json` - production probes (serving 17a0126)

No secret appears in this commit (verify_release secret_patterns PASS; credential used env-only, never printed,
never written to the tree).
