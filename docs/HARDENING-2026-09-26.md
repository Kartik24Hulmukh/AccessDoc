# Hardening receipt: 2026-09-26 turn (fresh clone of `main` after PR #75)

Environment: Linux (x86_64), Python 3.14, fresh `git clone` of `main`. Every number below was measured on this host during this turn; nothing is projected.

## Frozen baseline (before any change this turn)

- `pytest` from repo root (pinned `testpaths`): **795 passed, 13 skipped, 0 failed**, 141 subtests, 53.4 s.
- `scripts/verify_release.py --quick` exceeded the 40 s sandbox window while the suite ran concurrently; the unittest-based gate inside it is covered by the pytest run above.

## Load gate (`scripts/hardening_load.py`, loopback)

- 100/100 HTTP 200, 1 unique bundle digest, 0 failures.
- p50 66.2 ms, p95 83.2 ms, p99 88.7 ms, max 89.3 ms, 123.0 rps.
- Malformed-input contract probes all returned the designed 400/404/413/415/422/503 statuses (structured JSON logs recorded per request).

## Adversarial stress matrix (`scripts/stress_test.py`)

- 15 checks run, 0 failures: injection (HTML/YAML), tamper detection, 5000-violation bundle, unicode, determinism across runs.

## Live Melious gateway probe (bearer `$MELIOUS_API_KEY`, canonical chain)

| Chain slot | HTTP | Latency |
|---|---|---|
| chain[0] (primary) | 200 | 542.9 ms |
| chain[1] | 200 | 695.1 ms |
| chain[2] | 200 | 562.5 ms |
| chain[3] | 200 | 1943.5 ms |

All four canonical models answered a one-word completion with HTTP 200. Circuit-breaker, 429-storm and outage fail-fast behaviour is exercised by the existing gateway test modules in the suite above.

## Defect fixed this turn

- `STATE.md` still declared the previous beta as release candidate while `VERSION` had already moved to `0.7.0-beta.7`. `STATE.md` is deliberately excluded from `scripts/version_lint.py` (it records history), so nothing guarded its headline release-candidate line. Fixed the line and added `tests/test_state_doc_sync.py` to pin it to `VERSION` from now on.

## repos.md

- Still not supplied in this turn’s artifacts (a screen recording and two handoff reports). No connectors were guessed or integrated.
