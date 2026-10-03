# Continuation receipt: coherent RSS and browser startup

Date: 2026-09-29. Branch: `harden/accessdoc-v1-launch` (draft PR #95). This is a scoped, local continuation; no deployment or release approval.

## Baseline frozen before edits

- Fresh clone at `1ae62eb6`; Python 3.13, declared dev dependencies: pytest **846 passed, 14 skipped, 153 subtests**, 55.55 s. Browser dependencies and exact deployed production target were absent.
- Eight-worker / 100-request loopback harness: 100/100 HTTP 200, p50 64.4 ms, p95 83.3 ms, p99 89.5 ms, 124.90 req/s. Idle/current/peak RSS 34,728 / 44,748 / 44,652 KiB. Peak **below** current: previous mixed-source telemetry was inconsistent. Raw input: `docs/evidence/rss-cdp-2026-09-29/load-before.json`.
- Existing PR's live gateway status: **failure**, because Kimi K3 had one 504 in the prior 12-call benchmark. No new live provider measurement was run here.

## Change and hypothesis

- `app/procstats.py`: read Linux `VmHWM` and `VmRSS` from one `/proc/self/status` snapshot, falling back to existing POSIX primitives where unavailable. `process_stats()` now requests a single snapshot. Regression tests pin coherent counter selection and fallback.
- `scripts/hardening_load.py`: fail the local load gate if post-load peak is below current RSS; the reported peak is process-lifetime, **not** a memory capacity limit or an isolated burst-only peak.
- `scripts/narrow_viewport_audit.py`: Chromium's `/json` can answer `[]` before its page target is ready. Wait for an actual page with a debugger URL or fail clearly if Chromium exits/deadline expires. Regression covers the empty-then-page startup sequence. This fixed the first strict verifier's `StopIteration` without suppressing its failure.
- Rollback: revert the RSS and CDP startup changes; no data migration or public API schema change.

## Measured outcome and boundary

- Focused tests: 9 passed for telemetry/portability, then 7 passed for startup, viewport and RSS.
- Eight-worker / 100-request loopback rerun: 100/100 HTTP 200, p50 54.5 ms, p95 70.0 ms, p99 82.3 ms, 143.43 req/s. Idle/current/peak RSS 34,708 / 44,832 / 44,844 KiB; the measured peak/current invariant now holds. Raw output: `docs/evidence/rss-cdp-2026-09-29/load-after.json`. Single uncontrolled runs do **not** establish a speedup or RAM ceiling.
- Stress matrix 15/15, synthetic 100 socket workflows (40 disconnects) passed; zero captured unhandled thread exceptions, handler errors, or surviving new threads. Post-chaos `/healthz` 1.64 ms, `/readyz` 1.10 ms. These are loopback probes, not 100 human evaluators or a coroutine-leak proof.
- Final browser-enabled pytest: **862 passed, 1 skipped, 153 subtests**, 74.13 s. Strict release verifier: **10/10 local gates PASS** (its unittest run: 846 tests, 1 skipped). The first strict verifier failed on the CDP race; the post-fix rerun passed. Exact deployed production validation still requires `ACCESSDOC_PRODUCTION_URL`.

## Five-point premortem

1. Large-file memory exhaustion: existing bounded-input checks and 5,000-finding stress passed; RSS telemetry is now coherent. Oversized multi-format capacity still unproven.
2. Worker deadlocks/cancellation: 100 synthetic socket workflows passed with no captured thread leak; not a general async proof.
3. OCR/parsing timeouts: malformed-input contracts passed; this evidence-import product has no general OCR pipeline or OCR timeout certification.
4. Gateway 429/5xx/504 cascades: prior offline probes pass; prior live K3 504 remains a failing live gate. No falsified replacement sample.
5. Release integrity: `repos.md` is not supplied in attachments or repository, so no guessed connectors are integrated. Independent security/legal/accessibility review, named sign-offs, real practitioner acceptance, exact deployment and rollback remain outstanding.

**Decision: HOLD.** Do not merge draft PR #95 or claim a hosted launch while its live-gateway gate is red and the human/deployment gates remain open. Credentials disclosed in chat must be rotated and supplied through a secret manager before further live testing.
