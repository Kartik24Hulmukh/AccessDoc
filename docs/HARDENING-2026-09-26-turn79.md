# Hardening receipt: 2026-09-26, turn 79

Start: `main` @ `2f84728` (#78). Linux, Python 3.14, fresh clone. All numbers measured this turn.

## Frozen baseline (main `2f84728`, before any change)
- pytest: 805 passed / 13 skipped / 0 failed, 53.25 s
- `gateway_bench.py` with `MELIOUS_API_KEY` **unset**: exit **0** after 12/12 failed samples (0.1 s), and it overwrote the tracked `gateway_bench.json` with the failure data. The gateway bench could never fail a gate.

## Defect fixed
`scripts/gateway_bench.py` had no verdict. Fix: `parse_args()` (positional root kept, `--output`, `--probes-only`), a pure `exit_code()` gate (0 pass, 1 any resilience probe failed, 2 live mode without a credential, nothing written), and a `verdict` block in the report. CI now runs `gateway_bench.py --probes-only` as an offline gate for 429 failover, 503 fail-fast and static-KB last resort.

Guard tests: `tests/test_gateway_bench_gate.py` (4 tests; functions pulled out with `ast`, subprocess runs have no credential, so no live calls happen).

## After (branch)
- pytest: 809 passed / 13 skipped / 0 failed, 54.51 s (+4 guards)
- no-key live mode: exit 2, no report written; `--probes-only`: exit 0, 3/3 probes pass
- `hardening_load.py`: pass, 100/100 HTTP 200, p50 69.3 / p95 91.4 / p99 96.6 ms, 114.7 rps, 1 bundle digest
- `disconnect_chaos.py` (100 workflows, 40 disconnects): pass; /healthz 1.19 ms, /readyz 0.60 ms; 0 unhandled exceptions; 0 leaked threads
- Live Melious (`gateway_bench.json` refreshed): all 4 models 3/3 OK, breakers closed. Samples in ms: GLM-5.3 4193/3589/3717; GLM-5.3 Flash 6098/5211/4811; Qwen 3.8 27B 11038/10799/10778; Kimi K3 19687/22908/19166. 429 storm fails over on attempt 1; outage fails fast in 0.2 ms; static-KB works.

No product code path changed, so no latency gain is claimed. `repos.md` has still not been supplied, so no connectors were integrated.

## CI-surfaced defect (fixed in the same PR)
The first CI run of this PR failed `portability (macos-latest)` in `tests/test_gateway.py::BreakerLifecycleTests::test_opens_after_threshold_half_open_then_closes` with `AssertionError: True is not false` at line 45. That code predates this PR. The test drove the breaker with `time.sleep(0.25)` against a 0.4 s window, and the loaded macOS runner overslept past the window. Fix: `CircuitBreaker(clock=...)` takes an injectable monotonic clock (the default is still `time.monotonic`, so production behavior is unchanged), and the test uses a fake clock with no sleeps. Local results: 2000 deterministic lifecycle iterations with 0 failures; full suite 809 passed / 13 skipped (53.99 s); chaos gate pass (/healthz 1.50 ms, /readyz 0.83 ms).
