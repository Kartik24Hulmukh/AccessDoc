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
