# AccessDoc state

- Release candidate: `0.7.0-beta.7`.
- Decision: controlled practitioner OSS beta only; broad hosted launch is blocked.
- Repository evidence: local tests/browser/PDF/grep gates passed; exact final ZIP receipt is external.
- Target evidence: RUN 13 Sept 2026 against `https://access-doc.vercel.app` at commit `a934582`; see `docs/REDTEAM-PROD-2026-09-13.md` (one Markdown-injection defect in the EAA pack found and fixed).
- Editorial/legal approval: BLOCKED — named counsel/reviewer approval not supplied.
- Adoption evidence: NOT_RUN — no practitioner attempt completed.
- Strongest wedge: deterministic, provenance-preserving, claims-limited evidence handoff.
- Weakest assumption: practitioners prefer it to their current template/model workflow.
- Next human gate: assign owners and apply `launch/WEDNESDAY_DECISION.md`.

## September 13 hardening candidate

See [hardening receipt](docs/HARDENING-2026-09-13.md): 600 tests (one live-target skip), 15/15 stress checks, local HTTP concurrency and accessibility evidence. Changes require PR review and exact-SHA preview deployment; hosted launch remains blocked.

## September 26 hardening turn (PR #76)

See [hardening receipt](docs/HARDENING-2026-09-26.md): fresh-clone baseline 795 passed / 13 skipped / 0 failed; local load gate 100/100 HTTP 200 (p50 66.2 ms, p95 83.2 ms, p99 88.7 ms, 123.0 rps, 1 bundle digest); adversarial stress matrix 15/15; live Melious completions HTTP 200 on all four canonical chain models. `repos.md` was again not supplied, so no external connectors were integrated. Hosted-launch human gates remain as recorded above.


## September 29 hardening turn (evidence-only)

See [hardening receipt](docs/HARDENING-2026-09-29.md): fresh-clone baseline re-verified 834 passed / 13 skipped / 0 failed (no regressions). Fresh live Melious 4-model bench attempted with the real key: the provider returned HTTP 429 on all four canonical models this turn (external rate limit, not an AccessDoc defect); the circuit breaker opened correctly after 1 failure per model and fail-fast on repeat attempts measured ~100ms (well inside the <200ms auto-recovery bar), and the offline 429-storm/outage/static-KB resilience probes all still pass. No new successful live latency sample exists to replace the last-known-good P50/P95/P99 in `gateway_bench.json`, so that file is unchanged; the fabricated alternative was rejected on integrity grounds. `repos.md` remains unsupplied in every session to date, so no external connector was integrated on a guessed catalog. Human sign-off, security/legal review, and practitioner acceptance remain the only launch blockers.

## September 29 continuation: passive gateway readiness

See [continuation receipt](docs/HARDENING-READINESS-2026-09-29.md). Baseline frozen at 842 passed / 14 skipped on this environment. Optional AI readiness now reports known billing degradation and remaining hold time without active probes or changes to core availability. Fresh live provider evidence: 11/12 completions; one K3 504, so the live gate failed and automatic merge remains prohibited. Local 100-workflow disconnect chaos and 15-case stress checks passed. No broad launch approval is implied. Missing integration catalog, independent reviews, named approvals and practitioner evidence remain outstanding.
