# Round 2 native-finalizer fixture correction — frozen handoff

## Scope

- Base checkout: published `3519ab789ea3e8fd7077078f07bda4332cfe1b85` (`3519ab7`), initially clean.
- Reviewer-owned edit: **only `tests/test_otlp_cleanup_ownership.py`**, 41 insertions / 2 deletions. No application/source edits; no commit/push; no full-suite rerun; no provider calls or credentials. Other workers' reporter changes were not touched.
- Python: `/data/accessdoc-venv/bin/python`; commands use `-B` / `PYTHONDONTWRITEBYTECODE=1`, pytest cache disabled.
- Final test SHA-256: **`cbdccdf2d6b6bd6d9be5660515463503c535e3df6dce4217c7d1ee0e477a74f6`**. Lead owns updating the diagnostic test hash.
- Unchanged `app/otlp_export.py` SHA-256: `f5020886ba637616d9ed5c8f17b9247e70878314ab51c40488eb4d286af9877d`. `git diff -- app/otlp_export.py app/gateway_transport.py app/deadline.py` is empty at handoff.

## Preserved hosted failure and causal distinction

`/data/accessdoc-evidence/round2-mac-failure.json` preserves the Mac push full-pytest assertion:

`CleanupOwnershipTests.test_native_finalizer_is_not_recancelled_by_retirement_drains`, original `tests/test_otlp_cleanup_ownership.py:231`, `self.assertTrue(cancelling.wait(.2))` False, after `ex.flush(.08)` returned False. The same published SHA's Mac PR pass is not evidence that the failure may be ignored.

The test arranges an async `_perform` whose `finally` signals `cancelling`; it had no proof that the coroutine started before the 80 ms caller budget expired. A flush returning False is not proof of a started native task or finalizer.

Production evidence (unchanged source):

- `app/otlp_export.py:302-306` reserves cleanup inside the existing budget; the 80 ms caller leaves approximately 53.3 ms for work.
- `app/gateway_transport.py:335-347`: submitted callbacks check cancellation/owner intent and expiry BEFORE creating `_NativeRequestTask`.
- `app/gateway_transport.py:392-401`: cancellation publishes intent; if task is still None when dispatch occurs, it retires the reservation without running a coroutine.
- `app/gateway_transport.py:644-674`: synchronous post submits then waits inside its absolute deadline; deadline expiry can request cancellation before selector dispatch creates a task.

Thus a valid late-start schedule has no `_perform`, no `finally`, and no `cancelling` event. That does not imply repeated cancellation interrupted a finalizer. The new fixture proves startup before testing the intended finalizer invariant. The exact Mac scheduling trace is not available; the controlled reproduction proves a causal path to the same assertion, not that every potential Mac scheduler/production issue was ruled out.

## Controlled reproduction, before and after (no retry-to-green)

Driver: `/data/accessdoc-round2-controlled-start.py`.

The driver delays each native submit callback by 90 ms through the EXISTING selector's `call_later` (fixture scheduling only). It does not enlarge flush/wait bounds, monkeypatch acceptance assertions, create a helper worker, alter production cancellation, or call providers. It observes actual request coroutine entry and actual call.task/retirement state.

1. Original target, one isolated invocation: **PASS**, 0.35 s (`/data/accessdoc-round2-original-single.log`). This is reported alongside, not substituted for, the hosted failure.
2. Original target under controlled 90 ms delayed-submit schedule: **FAIL at the exact original `cancelling.wait(.2)` assertion**, 0.263 s. Actual evidence: `request_coroutine_entries=0`, `task_created=False`, `cancel_requested=True`, `retired=True`. Log: `/data/accessdoc-round2-controlled-before.log`.
3. Corrected target under the SAME driver/schedule: **PASS**, 0.213 s. Actual evidence: `request_coroutine_entries=1`, `task_created=True`, `cancel_requested=True`, `retired=True`. Log: `/data/accessdoc-round2-controlled-after.log`.

There was no repeated original-test run until it passed and no assertion widened after observing a failure.

## Test-only change and preserved contracts

### Existing finalizer test: current lines 210-246

- Introduced `entered`, signaled by the REAL native `_perform` after its async release gate is created.
- Arrange/admit/register/submit a real `_Call` into this exporter's actual retirement group using the existing fixture `ex.timeout == .5` for SETUP, following the same native-owner pattern already used by the adjacent cancellation test (`281+`). Setup completion is gated by `entered.wait(.2)` before the operation under test.
- Removed the unused queued-span setup: this fixture now explicitly tests an existing native owner/finalizer rather than assuming the first timed flush must start a task. No existing assertion was removed.
- Keep **`flush(.08)`, `cancelling.wait(.2)`, no-recancel assertion, cleanup_pending=1, actual native inflight=1, `flush(.03)`, subsequent no-recancel assertion, and final cleanup_pending=0** unchanged.
- Keep existing finalizer gate release and `.5` cleanup drain in `finally` unchanged.

The setup call's `.5` deadline is explicit fixture preparation, not a widening of the asserted 80 ms / 30 ms flush budgets. After the started barrier, production `group.drain` cancels the known-existing task within the original caller budget; its finalizer deliberately remains suspended and owned. No source/work-cutoff/cleanup-reserve deadline computation changes. This test does not claim to test task-start latency; it tests prevention of recancellation while a real finalizer is already owned.

### New complementary pre-start test: current lines 248-279

`test_retirement_before_native_start_does_not_enter_a_finalizer` holds callback dispatch in a fixture-owned list, admits/registers/submits a native reservation, and requests group drain/cancellation with an unchanged short `.03` budget. It proves task=None, cancel intent=True, truthful cleanup_pending=1 while dispatch is gated. After releasing the actual callbacks on the existing selector, it requires call.done within `.2`, no `_perform` entry/task creation, completed group retirement, cleanup_pending=0, native inflight=0.

This captures the valid cancellation-before-start path separately; it does not skip cancellation/finalizer assertions or fabricate successful cleanup. It needs no scheduler sleeps or larger production deadlines.

## Validation

| Invocation | Result | Evidence |
| --- | --- | --- |
| Original target once, unmodified | 1 PASS, 0.35 s | `/data/accessdoc-round2-original-single.log` |
| Controlled original delayed-submit | Exact expected FAILURE, 0.263 s | `/data/accessdoc-round2-controlled-before.log` |
| Same controlled delayed-submit after barrier fix | 1 PASS, 0.213 s | `/data/accessdoc-round2-controlled-after.log` |
| Entire cleanup-ownership module + adjacent deferred-accounting regression | **17 PASS, 2.66 s** | `/data/accessdoc-round2-focused.log` |
| Explicit pre-start → finalizer → group/shutdown cancellation order | **3 PASS, 0.275 s** | `/data/accessdoc-round2-order.log` |

Focused command:

```sh
cd /data/AccessDoc
PYTHONDONTWRITEBYTECODE=1 /data/accessdoc-venv/bin/python -B -m pytest -q -p no:cacheprovider \
  tests/test_otlp_cleanup_ownership.py \
  tests/test_native_deadline_races.py::NativeDeadlineRaces::test_deferred_export_accounting_and_shutdown_owned_by_existing_sender
```

`git diff --check -- tests/test_otlp_cleanup_ownership.py` passes. The explicit different-order validation is reported separately, not treated as an acceptance retry. Full Linux baseline and hosted Mac push/PR acceptance are lead responsibilities; Linux focused passes are not a claim of Mac acceptance.

## Freeze and next action

Reviewer edits are frozen. Lead should update the exact test digest above, inspect the test-only diff, and run the normal acceptance matrix. No source change approval is requested because evidence supports a fixture precondition correction; native cancellation, work/cleanup budgets, and prior finalization fix remain untouched. Existing hidden Event/Future mutex audit findings remain documented in `/data/accessdoc-native-review.md` and were not refactored during this round.
