# AccessDoc — Launch Turn 15: PR #53 merged, launch gate closed

**Window:** 2026-09-15 ~19:00–19:10 UTC · Hard launch 16–17 Sep 2026  
**Base at start:** `main @ 17a0126` · **PR #53 head:** `55c3c55` (rebased, mergeable=clean)

## 1. Forensic audit

| Item | Result |
|---|---|
| Open PRs at start | #53 only |
| PR #53 mergeability | `mergeable=true`, `mergeable_state=clean` (turn-14 dirty conflict resolved) |
| Remote checks on `55c3c55` | 7/7 success — lint x2, test x2, accessdoc-evidence, GitGuardian Security Checks, Vercel Preview Comments |
| Fresh-clone dependency health | `requirements.txt` + `requirements-dev.txt` install clean on Python 3.14; missing reportlab was a sandbox gap, not a repo defect |

## 2. Local re-verification on the PR head

| Gate | Result |
|---|---|
| `python3 -m unittest discover -s tests` | **732 tests, 0 failures, 0 errors**, 12 optional Playwright skips |
| `scripts/verify_release.py` | **10/10 PASS** (compile, tests, secret_patterns, claims, placeholders, stale_files, immutable_action_refs, non_publishing_workflows, required_files, version_consistency) |

## 3. 100x concurrency torture (100 workers x 200 mixed payloads)

```json
{"workers":100,"requests":200,"wall_seconds":25.25,"throughput_rps":7.92,
 "status_histogram":{"200":134,"413":33,"422":33},
 "unexpected_5xx":0,"contract_violations":0,"transport_errors":0,"admission_retries":0,
 "latency_p50_ms":9541.71,"latency_p95_ms":18176.73,"latency_p99_ms":19712.12,"latency_max_ms":19723.5,
 "rss_floor_mb":41.7,"rss_ceiling_mb":324.6,"rss_after_mb":214.7,
 "recovery_probes":{"/healthz":200,"/api/bundle":200},"fault_recovery":"PASS"}
```

The 134/33/33 contract histogram reproduces exactly on a clean clone: oversized payloads are rejected 413 at the
ingress cap (no OOM), malformed documents 422 at MIME/boundary validation, valid multi-format work 200. Zero
unexpected 5xx, zero transport errors, zero admission retries, bounded RSS, clean post-burst recovery.

## 4. Model gateway torture + live canary

Injected-fault resilience (`scripts/gateway_bench.py`): `429_storm_fallback` PASS (served by next chain hop,
1 attempt), `outage_fail_fast` PASS at 0.1 ms, `static_kb_last_resort` PASS — all far under the 200 ms failover ceiling.

Live canary over the real gateway, credential supplied env-only and never written to disk, git config or commit:

| Chain hop | HTTP | Latency | Tokens |
|---|---|---|---|
| 1 (primary) | 200 | 504.5 ms | 17 |
| 2 (flash) | 200 | 908.1 ms | 26 |
| 3 (27B) | 200 | 545.3 ms | 20 |
| 4 (long-context) | 200 | 851.4 ms | 134 |

**4/4 HTTP 200, 0 fallbacks, all breakers closed.** A raw un-normalized model alias returns 404 upstream, which is
precisely why `normalize_model()` exists in `app/gateway.py`; the canonical chain resolves correctly.

## 5. Delivery

PR #53 squash-merged into `main` → **`f8ada86`**. No open PRs remain. Remediation cycles used: 0 of 5.

## 6. Launch decision

| Gate | Decision |
|---|---|
| Code on `main` | **GO** — 732/732 green, verifier 10/10, torture PASS, failover sub-ms, live chain 4/4 |
| Remote merge | **DONE** — #53 merged, branch history semantic and linear |
| Production ops | **NO-GO until operator acts** — `https://access-doc.vercel.app/readyz` still reports commit `17a0126` and `gateway.configured=false` |

### Operator checklist (outside repo authority)

1. Let Vercel redeploy `main @ f8ada86`; confirm `/readyz.commit` advances.
2. Install a rotated `MELIOUS_API_KEY` in Vercel until `/readyz` reports `gateway.configured=true`.
3. Rotate the GitHub PAT and Melious key that were passed in-band; both were used env-only and never committed (secret_patterns PASS, GitGuardian green).
4. Point `OTEL_EXPORTER_OTLP_ENDPOINT` at a real collector; alert on failed_batches, queue depth, spend, error rate.
5. Rollback rehearsal + named release/security/legal/accessibility sign-off before 16–17 Sep.
