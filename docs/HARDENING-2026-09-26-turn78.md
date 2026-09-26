# Hardening receipt — 2026-09-26 (turn 77 merge + turn 78 fix)

All numbers measured on this host (Linux, fresh clone). Nothing projected.

## PR #77 merge
- All 11 checks on `f88a07e` verified green via the Checks API (test x2, lint x2,
  accessdoc-evidence, portability windows + macos x2, GitGuardian, Vercel) before
  squash-merge to `main` as `613376e`.

## Post-merge baseline (frozen before any change)
- `pytest tests -q`: **797 passed / 13 skipped**, 141 subtests, 54.7 s.
- `scripts/version_lint.py`: PASS (0.7.0-beta.7).
- Load gate (`--output`): **pass** — 100/100 HTTP 200, p50 72.7 ms / p95 102.2 ms /
  p99 106.6 ms, 107.2 rps, 1 unique bundle digest, 0 failures.
- Chaos gate (zero-arg, post-#77): **pass** — 100 workflows, 40 disconnects,
  recovery /healthz 1.31 ms + /readyz 0.69 ms, 0 unhandled thread exceptions,
  0 leaked threads.
- Stress matrix: **15/15 checks, 0 failures**.

## Defect found & fixed this turn
`scripts/hardening_load.py` rejected a positional report path with an argparse
error (exit 2) while `scripts/disconnect_chaos.py` (fixed in #77) accepts one —
the two torture gates had contradictory CLIs and the natural invocation
`hardening_load.py load_report.json` failed before doing any work. Fixed by
extracting `parse_args()` with an optional positional OUTPUT (flag wins when
both are given; default unchanged). Guard: `tests/test_hardening_load_cli_guard.py`
(4 tests, in-process, <1 s).

## repos.md
Still not supplied in any turn; no connectors integrated or claimed.
