# Remediation boundary and handoff integration receipt

Date: 2026-09-29. Branch: `harden/accessdoc-v1-launch`, based on local `7df7219` atop draft PR #95. No hosted deployment or customer acceptance is claimed.

## Frozen baseline before edits

- Python 3.13 with browser dependencies restored: **862 passed, 1 skipped, 153 subtests**, 71.29 s. The first attempt failed 7 browser checks because Playwright's executable cache had disappeared between sessions; restoring the browser and rerunning the unchanged tree isolated that environment defect. The one persistent skip requires `ACCESSDOC_PRODUCTION_URL`.
- Eight-worker, 100-request loopback: 100/100 HTTP 200; p50/p95/p99 **54.5/74.9/78.4 ms**; **140.21 req/s**; idle/peak/post-load RSS **34,604/45,036/44,548 KiB**.
- Reproduction with one malformed numeric axe rule ID: hosted `/api/remediate` returned **200 and dispatched one model call**, while self-hosted returned **422**. A gateway spy and two actual loopback HTTP servers captured the discrepancy. The new parity regression failed before the fix.

## Change and integration decision

- Shared `remediation_body()` now validates both scanner evidence and a supplied bare `violations` list through the existing axe parser/limits, including the case where both are present. Unknown keys are removed before dispatch. Hosted `api/handler.py` now invokes the same boundary *before* checking the provider credential or dispatching a model; it maps size errors to 413 and malformed evidence to 422. Self-hosted behavior is aligned. This prevents invalid scanner input from receiving plausible guidance or consuming provider calls. No public response shape for valid input changed.
- Supplied `repos.md` was reviewed. **Selected:** `microsoft/playwright` and `dequelabs/axe-core`, already optional/pinned in this project, and used for one real, locally authorized Chromium/axe → bundle → verifier handoff test plus `examples/agency-handoff/README.md`. This closes a demonstrability gap without adding a new production dependency or a hosted crawler. **Not imported:** general OCR/RAG agents (the product ingests structured accessibility evidence, not arbitrary documents); agent orchestration and browser-autonomy stacks (SSRF/credential/scope risk and unproven buyer need); GRC/payment frameworks (no repeat-usage proof); new telemetry/security stacks without a verified gap. Existing OpenTelemetry-compatible instrumentation and local axe tests were retained. No claim that the whole catalog was integrated.
- The attached strategic materials conflict: the August Forge/AAI concept proposes autonomous coverage and cryptographic claims that are hypotheses, while the September founder/agency decisions emphasize an accepted practitioner handoff and repeat use. The latter is the bounded commercial experiment. No AI advisory session was represented as independent human review.
- Rollback: revert the two boundary files and the test/example commits; no migration. The old hosted route would again accept invalid evidence, so rollback is not a release recommendation.

## After, measured locally

- Browser-enabled pytest **864 passed, 1 skipped, 155 subtests**, 74.89 s; focused integration/boundary tests **29 passed, 2 adapter subtests**. One production-target check still skipped. Strict release verifier **10/10 local gates PASS** (unittest: 848 tests, 1 skipped).
- Eight-worker 100-request loopback: 100/100 HTTP 200; p50/p95/p99 **47.6/65.2/66.1 ms**; **165.02 req/s**; idle/peak/post-load RSS **34,636/44,992/44,964 KiB**. These are single uncontrolled runs, **not** a throughput improvement, RAM-capacity certification, or 100-fold traffic result.
- Adversarial stress **15/15**; synthetic socket chaos **100 workflows** including **40 disconnects**, zero captured unhandled thread exceptions, server errors or surviving new threads; post-chaos `/healthz` **1.22 ms**, `/readyz` **0.73 ms**. Not 100 real users, not an async coroutine-leak proof, and not a provider recovery measurement.
- Raw local baseline/final logs and load/chaos JSON are in `docs/evidence/remediation-handoff-2026-09-29/`. No supplied credential was used or written to evidence.

## Five-point premortem and release boundary

1. **Malformed evidence is laundered into model advice/cost:** closed for the paired hosted/self-hosted endpoints by the shared validator and zero-dispatch tests; signed source-truth remains outside the parser's ability to prove.
2. **Large-file memory exhaustion:** 2 MiB HTTP bound, parser limits and 413 regression exercised; no certification for arbitrary multi-format/OCR ingestion or sustained hosted memory.
3. **Worker deadlocks, cancellations or client disconnects:** local 100-workflow chaos passed with no captured thread leak; no full async/external-provider cancellation guarantee.
4. **OCR/parsing hangs and gateway 429/5xx/504:** no general OCR ingestion exists. Existing offline resilience tests pass, but PR #95's previous live Kimi K3 **504** is still a red live gate; no new credential-injected 4-model benchmark was run.
5. **False adoption/release claims:** neither a paid client acceptance nor 100 real evaluators, exact-SHA hosted canary, rollback drill, named security/legal/accessibility approval, or credential rotation was performed. The companion handoff test establishes mechanics only.

**Decision: HOLD the hosted launch and automatic merge.** PR #95 remains draft with failing `accessdoc/live-gateway`; the new local commits must be pushed and hosted CI rerun before review. Rotate the credentials disclosed in chat and inject replacements through a secret manager; identify an exact deployed target and complete independent human/practitioner gates. Do not describe this as fully launched or 100x traction.
