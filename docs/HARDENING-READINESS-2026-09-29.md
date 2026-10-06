# AccessDoc continuation: passive gateway readiness and measured launch hold

Date: 2026-09-29. Resumed actual main `7ab1817` after reading both supplied handoffs. The reports conflict on whether billing is the only launch blocker; repository governance still requires named approvals, independent reviews, practitioner evidence, and exact deployment identity.

## Mutation and integration ledger

- Hypothesis: operators need a machine-readable optional-AI degradation reason and remaining billing cooldown without health probes spending credits or evicting a functioning deterministic core.
- Changed `app/gateway.py`, `app/remediate.py`; added `tests/test_gateway_readiness.py` and operator documentation in `docs/READINESS-GATEWAY.md`.
- Tests reproduce missing fields before implementation; actual loopback HTTP tests cover both adapters, clock-controlled expiry, no lazy initialization, and secret-free snapshots.
- Rollback: revert the feature commit; additive JSON fields only, no schema migration.
- `repos.md`: absent from both attachments and cloned repository. No catalog integration claimed. Existing parser connectors were not replaced with guessed dependencies.
- No real-human council or evaluator panel was convened. No signatures or independent acceptance were fabricated.

## Frozen baseline and measurements

Full suite before edits: **842 passed, 14 skipped, 0 failed, 151 subtests, 55.55 s** on Python 3.14. This differs from the supplied 843/13 because the browser reflow dependency was missing. Raw baseline and hash are preserved under `docs/evidence/readiness-2026-09-29/`.

| Local loopback load | Before | After |
|---|---:|---:|
| HTTP 200 requests | 100/100 | 100/100 |
| P50 | 46.1 ms | 90.9 ms |
| P95 | 70.2 ms | 110.5 ms |
| P99 | 75.7 ms | 133.4 ms |
| Throughput | 169.09 req/s | 96.17 req/s |
| Idle RSS | 38,624 KiB | 39,296 KiB |
| Reported peak RSS | 42,292 KiB | 41,988 KiB |
| Post-load RSS | 46,668 KiB | 46,968 KiB |

These are descriptive single runs with overlapping validation processes, not a controlled performance comparison. Latency increased; no improvement claim is warranted. Kernel memory sources disagree (peak below current RSS), so the reported peak is **not a trustworthy RAM ceiling**. Raw readings are retained rather than silently corrected. The harness uses eight workers and scales finding instances 1 to 100; it does **not** certify 100-fold production traffic capacity.

The 100 synthetic socket workflows (40 disconnects) passed before and after. After: zero captured thread exceptions, zero handler errors, zero surviving new threads; `/healthz` recovered in 1.40 ms and `/readyz` in 0.68 ms. This is local post-load probe latency, not an end-to-end provider recovery guarantee or coroutine-leak measurement. There were no human participants. Stress matrix: 15/15 passed, including 5,000 findings, injection, malformed input, determinism and tampered bundles.

## Final local regression

After installing Playwright Chromium, axe-core 4.11.0 and websocket-client to execute optional browser gates: **859 passed, 1 skipped, 0 failed, 153 subtests, 70.92 s**. Only exact production deployment validation is skipped (`ACCESSDOC_PRODUCTION_URL` unset). The increase over baseline includes four added tests plus thirteen previously skipped browser checks; it is not seventeen new feature tests. Targeted readiness/billing/health tests: **15 passed**, with two adapter subtests, under `-W error::ResourceWarning`.

An intermediate test incorrectly expected a gateway block in self-hosted `/healthz`; it was corrected to preserve liveness's existing contract. The final expanded suite above includes that correction. An initial release-verifier run overlapped tests and failed its stale-cache check; final clean verification is recorded separately, not silently counted as a pass.

## Fresh live provider gate — FAILED, do not auto-merge

The new supplied credential produced **11/12 real completions**. Prior account-wide billing denial is no longer the observed blocker. K3 returned one 504 at the configured 40-second budget. Three samples per model are descriptive order statistics, not statistically meaningful tail SLOs. Samples include failures.

| Model | OK | P50 ms | P95/P99 ms |
|---|---:|---:|---:|
| GLM-5.3 | 3/3 | 7,771.11 | 16,420.47 |
| GLM-5.3 Flash | 3/3 | 12,227.86 | 14,144.66 |
| Qwen 27B canonical route | 3/3 | 10,830.63 | 11,098.68 |
| Kimi K3 | 2/3 | 32,130.85 | 40,042.46 |

`gateway_bench.py` correctly exited with gate verdict 1. The three offline resilience probes passed, including injected outage fail-fast at 0.2 ms; those are fault-injection evidence, not live chaos guarantees. No budgets were inflated merely to turn the gate green; historical benchmark files remain untouched.

## Five-point premortem disposition

| Risk | Evidence / resolution | Remaining limit |
|---|---|---|
| Large-file memory exhaustion | Existing bounded-input paths retained; 5,000-finding stress and malformed/ceiling contracts passed | No oversized multi-format capacity certification; inconsistent RSS sources need follow-up |
| Worker deadlocks and cancellation leaks | 100 synthetic socket workflows passed; zero surviving new threads | Threaded server evidence is not proof of coroutine-leak freedom or 100 real personas |
| OCR/parsing hangs | Malformed documents rejected; existing parser gates unchanged | This product imports accessibility evidence, not a generic OCR service; no new OCR timeout proof |
| Gateway 429/5xx/billing cascades | Existing resilience probes pass; passive degraded billing telemetry and retry hint added | Live K3 504 keeps the full provider gate closed |
| Unsafe release / missing integration evidence | Baseline frozen; real results preserved; no merge with failed live gate | Missing `repos.md`, independent reviews, named approvals and practitioner acceptance |

## Launch decision

**HOLD.** This increment improves operational visibility, not launch certification. Required next actions: resolve and remeasure the K3 timeout without erasing failed samples, provide `repos.md`, reconcile RSS telemetry, complete exact-artifact deployment/rollback verification and named technical/security/accessibility/release approvals, and collect genuine practitioner evidence. Credentials must be rotated because they were shared in the conversation; no supplied credential is stored in source or evidence.
