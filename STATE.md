# AccessDoc state

- Release candidate: `0.7.0-beta.6`.
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
