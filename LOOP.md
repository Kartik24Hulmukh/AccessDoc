# AccessDoc release loop

## Control loop

1. Read `STATE.md` and `ROADMAP.md`.
2. Verify source/archive hash and working-tree state.
3. Select the highest-priority unblocked gate.
4. Record hypothesis, files, test, and rollback in the mutation ledger.
5. Make the smallest change.
6. Run affected tests and full regression.
7. Capture evidence and update readiness score.
8. Stop on a hard gate, ambiguous target, secret exposure, or failed rollback.

## Autonomy levels

- **L1:** inspect and report.
- **L2:** modify a feature branch and produce evidence.
- **L3:** deploy or mutate external services only with immediate human approval.

## Completion rule

Production-ready requires every hard gate to pass, readiness ≥95%, exact tested/deployed artifact identity, successful rollback/restore drills, and named technical, security, accessibility, and release approvals.
