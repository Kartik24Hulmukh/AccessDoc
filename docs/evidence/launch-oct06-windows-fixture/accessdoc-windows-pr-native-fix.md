# Windows PR retirement fixture correction — authorized and frozen

## Scope / exact handoff

- Base published revision: `5290e553976cdb26dc9540656a4ae6ce8826ca3e`; local `7fed78d` had the identical tree `5c29443a5787f9303d3a996b9fb29477df3cc20f`.
- Leader authorized a narrow TEST-ONLY correction after the independent read-only review in `/data/accessdoc-windows-pr-native-review.md`.
- **Only `tests/test_otlp_cleanup_ownership.py` edited: 62 insertions, 7 deletions.** No production edits, deadline enlargement, skipped tests, acceptance retries, source changes, full-suite reruns, paid/provider calls, commits, or pushes. Preview authentication remains lead-only.
- Final test SHA-256: **`b7718d15626b275c449de2fe4c0bbde34d731809a1b689147e44271d8f42cc78`**.
- Unchanged source SHA-256 (`app/otlp_export.py`): `f5020886ba637616d9ed5c8f17b9247e70878314ab51c40488eb4d286af9877d`.
- Lead owns diagnostic test-hash updates, final baseline/Windows acceptance, commits, and pushes. Reviewer edits are frozen.

## Original evidence retained, not superseded

Public job `112423977014`, PR run `37508725155`: full pytest failed at original test line 54, `active_calls == 0`, actual 1. The delayed-task hook and latency assertions had passed. Load and first-export diagnostic stages were skipped; no preview or hardening_load cause is inferred.

Public evidence unchanged:

- `/data/accessdoc-evidence/windows-pr-annotations.json` — complete specific traceback.
- `/data/accessdoc-evidence/windows-pr-job.json` — exact SHA, stages/conclusions.
- `/data/accessdoc-evidence/windows-pr-run.json` — PR event/run metadata.
- `/data/accessdoc-evidence/windows-pr-job-html.html` — public job HTML; full logs require sign-in. Logs API returned 403.

Original unchanged target single invocation passed once (0.39 s), preserved in `/data/accessdoc-evidence/windows-pr-original-target.log`; that did not replace the failed hosted result. Existing pending-contract target independently passed once (0.35 s), `/data/accessdoc-evidence/windows-pr-pending-contract.log`.

## Causal old-fail / new-pass under the IDENTICAL controlled schedule

Driver unchanged: `/data/accessdoc-windows-pr-retirement-repro.py`. It intercepts the real finish callback captured by the test and simulates 20 ms of selector callback pressure AFTER the fixture's unchanged 30 ms delayed retirement timer fires. The real finish runs after this pressure; no production or assertion budget is altered.

| Measurement | Original fixture | Corrected completed fixture |
| --- | --- | --- |
| Native work deadline | 105.002 ms | 105.002 ms |
| Delayed callback begins | 135.632 ms | 34.992 ms |
| Real retirement completes | 155.835 ms | 55.140 ms |
| flush(False) returns | 140.101 ms | 55.247 ms |
| Actual active_calls / cleanup_pending at return | 1 / 1 | 0 / 0 |
| Original zero-ownership assertion | FAIL (`1 != 0`) | PASS |

Old result: `/data/accessdoc-evidence/windows-pr-controlled-retirement.log`.
New result: `/data/accessdoc-evidence/windows-pr-controlled-retirement-after.log` (test duration 0.076 s).

The old fixture allocated only nominal 5 ms of dispatch/accounting slack: a 30 ms retirement timer after the ~105 ms work cutoff inside a 140 ms caller budget. A timer callback need not execute punctually. Its False return with retained ownership matches the explicit bounded incomplete-cleanup contract. The corrected completed case fails a real native connection earlier so the same timer/pressure fits without relaxing any bound. This proves a causal fixture schedule, not the unavailable exact hosted Windows dispatch timeline.

## Implemented test-only correction

### Completed cleanup case — current lines 23–66

Keep the original named test and all its acceptance assertions:

- `flush(.14)` must be False, elapsed < `.24`.
- The failed-task callback still uses exactly `call_later(.03, finish, ...)` and must run.
- active_calls==0 and cleanup_pending==0 remain mandatory.
- Exactly three attempts, exactly two exported spans, exactly one failed span, useful exports, queued-unsent spans, fewer than ten collector requests remain mandatory.

Only the failure arrangement changes: first two real loopback HTTP requests succeed. Third real native `_perform` receives a loopback URL whose port is reserved by a bound, NON-LISTENING socket. The native connector therefore fails a real TCP connection earlier instead of waiting to the work cutoff. The socket remains reserved during the test so an unrelated listener cannot convert the intended failure into a success. No fake response, forced-success accounting, synthetic native exception, or production phase timeout is injected.

The legacy test name's “late final batch” refers to the later batch in the flush; this completed case no longer claims arbitrary OS dispatch will always fit in <5 ms after a near-cutoff timer. Distinct cutoff and pending-ownership cases prove those boundaries explicitly.

### Deterministic held-late retirement — current lines 68–116

New `test_global_budget_keeps_late_retirement_owned_until_release`:

1. Start a REAL native HTTP request against the held loopback collector; require the collector's real started Event within `.2` BEFORE measuring drain behavior. This excludes cancellation-before-start as an alternative explanation.
2. Register the actual call in this exporter's real retirement group using the existing `.5` fixture setup timeout; enqueue two separate spans.
3. Gate failed-call `_finish` dispatch by retaining the actual callback/handle, not by estimating a timer duration.
4. Require `flush(.14)` False within the unchanged `.24` bound, actual registered active_calls=1 and cleanup_pending=1, and queued spans untouched.
5. Require a second `flush(.03)` False, ownership still 1, queue still intact, and collector received only the original held request. No second admission, dequeue, retry, or false success is allowed while retirement is gated.
6. Release the REAL callback on the existing selector, require actual call.done within existing `.5` fixture cleanup bound, drain its group with `.03`, and require zero actual ownership.
7. Release the collector, then a separate `flush(.14)` exports the TWO previously queued spans and leaves the queue empty. This is not a retry of the failed tracked request; it admits new queued work only after actual retirement.

The gate remains closed across the original caller deadline, so retained ownership is deterministic rather than scheduler-luck. Cleanup after explicit release is a separate test lifecycle step, not additional grace added to the earlier caller latency. No new worker or production deadline change.

### Global-cutoff coverage preserved

`test_work_cutoff_between_successful_batches_needs_no_cancellation` is unchanged (now starts line 118); `tests/test_otlp_deadlines.py::ExportDeadlineTests::test_many_batches_share_one_flush_budget` is untouched and included in focused/order validation. Completion headroom must not substitute for those whole-flush cutoff proofs.

## Validation — all runs reported, no retry-to-green

| Invocation | Result | Evidence |
| --- | --- | --- |
| Identical controlled retirement-pressure driver after correction | 1 PASS, 0.076 s | `windows-pr-controlled-retirement-after.log` |
| Entire ownership module + unchanged many-batch budget + deferred-accounting regression | **19 PASS, 2.83 s** | `windows-pr-fixed-focused.log` |
| Explicit held-first → completed → between-success cutoff → many-batch budget order | **4 PASS, 0.488 s** | `windows-pr-fixed-order.log` |

All logs are under `/data/accessdoc-evidence/`.

```sh
cd /data/AccessDoc
PYTHONDONTWRITEBYTECODE=1 /data/accessdoc-venv/bin/python -B -m pytest -q -p no:cacheprovider \
  tests/test_otlp_cleanup_ownership.py \
  tests/test_otlp_deadlines.py::ExportDeadlineTests::test_many_batches_share_one_flush_budget \
  tests/test_native_deadline_races.py::NativeDeadlineRaces::test_deferred_export_accounting_and_shutdown_owned_by_existing_sender
```

`git diff --check -- tests/test_otlp_cleanup_ownership.py` passes. `git diff --exit-code -- app/otlp_export.py app/gateway_transport.py app/deadline.py` confirms no production-source diff. Linux focused passes are not a claim of Windows acceptance. Lead should update only the diagnostic test hash to the exact handoff value, then run normal acceptance without hiding the preserved original failure.
