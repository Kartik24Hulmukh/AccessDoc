# Windows PR CI failure — independent read-only native review

## Exact revision and scope

- Public head: `5290e553976cdb26dc9540656a4ae6ce8826ca3e`.
- Local HEAD: `7fed78d`; both local and public commits resolve to tree `5c29443a5787f9303d3a996b9fb29477df3cc20f`. Working tree was clean before and after this review.
- Windows PR job/check: `112423977014`; run `37508725155`, event `pull_request`, portability (windows-latest), conclusion failure.
- Read only: no repository edits, source/test/hash changes, commits, pushes, preview provisioning, providers, secrets, or full-suite reruns. Reproduction scripts/evidence were saved outside the repository.

## Independently retrieved public evidence

Public GitHub REST API requests without credentials succeeded for:

- `https://api.github.com/repos/Kartik24Hulmukh/AccessDoc/check-runs/112423977014/annotations` → `/data/accessdoc-evidence/windows-pr-annotations.json`
- `https://api.github.com/repos/Kartik24Hulmukh/AccessDoc/actions/jobs/112423977014` → `/data/accessdoc-evidence/windows-pr-job.json`
- `https://api.github.com/repos/Kartik24Hulmukh/AccessDoc/actions/runs/37508725155` → `/data/accessdoc-evidence/windows-pr-run.json`

Public job page saved as `/data/accessdoc-evidence/windows-pr-job-html.html`:
`https://github.com/Kartik24Hulmukh/AccessDoc/actions/runs/37508725155/job/112423977014`.

The public job logs API returned HTTP 403; job HTML explicitly says “Sign in to view logs.” No sign-in/secrets requested. The annotations contain the complete specific test traceback, sufficient to identify the failure; full job timing internals were not obtained.

**Actual failed stage:** Full test suite (step 7). The first-export phase observation AND hardening_load contract gate were skipped. The no-load-artifact warning is downstream of that skip, not the cause. This is not evidence of a preview or load-test failure.

## Specific failure

`tests/test_otlp_cleanup_ownership.py:54`,
`CleanupOwnershipTests.test_global_reserve_drains_late_final_batch_retirement`:

```text
self.assertEqual(ex._session.snapshot()['active_calls'], 0)
AssertionError: 1 != 0
```

Earlier assertions passed: flush(.14) returned False, elapsed < .24, and the failed-task delayed-retirement hook ran. The later cleanup_pending==0 assertion and exact useful-export assertions were not reached in the hosted failure; do not claim their hosted values are known.

This is DIFFERENT from prior reserve-test failure (no third failure task) and prior Mac finalizer-start failure. Those startup fixtures are already corrected in the exact published tree. This failure occurs after cancellation/failure and concerns native retirement completion.

## Causal accounting and deadline evidence

Relevant exact source/test lines:

- `tests/test_otlp_cleanup_ownership.py:23-61`: first two loopback requests succeed; third is held until work timeout. At lines 41-44, the fixture deliberately schedules failed task retirement with `engine.loop.call_later(.03, finish, engine, call, task)`.
- `app/otlp_export.py:302-306`: 140 ms caller budget has a maximum 35 ms total cleanup reserve, leaving approximately 105 ms for work.
- `app/otlp_export.py:318-331`: single attempts stop after failure; final group drain uses ORIGINAL caller deadline, not an extra grace.
- `app/gateway_transport.py:99-110`: group drain requests cancellation once and retains unfinished handles if the absolute wait expires. It does not optimistically retire the slot.
- `app/gateway_transport.py:353-366`: only actual `_retire` removes the registered call/decrements capacity and publishes call.done.
- `app/gateway_transport.py:368-381`: `_finish` drives that actual retirement.

The fixture's 30 ms retirement timer consumes almost all of the 35 ms reserve. **Nominal remaining dispatch/retirement slack is at most 5 ms**, before any scheduler delay between task cancellation, `_finish` dispatch, timer dispatch, and accounting. `call_later(.03, ...)` specifies when a callback becomes eligible, not a guarantee that it runs by 35 ms after the work cutoff. Correct bounded failure may therefore return with a registered native handle still pending.

No actual Windows dispatch timings are exposed by the traceback; Windows timer quantization is a plausible mechanism, NOT an independently measured fact here. Controlled selector pressure below proves the causal schedule without attributing a precise OS mechanism to the hosted run.

## Controlled read-only reproduction

Driver: `/data/accessdoc-windows-pr-retirement-repro.py`.

It wraps the original `_Engine._finish` captured by the test. After the test's unchanged 30 ms failed-task timer fires, the wrapper holds the selector callback for an extra 20 ms (test-only simulated dispatch pressure), then calls the real original finish. It preserves the source's work/cleanup deadlines, original .14 flush budget, .24 assertion threshold, fixture's .03 timer, and all assertions. No retry or late caller grace is introduced.

Observed one controlled invocation, `/data/accessdoc-evidence/windows-pr-controlled-retirement.log`:

| Event | Time from caller start |
| --- | --- |
| Work/call deadline | 105.002 ms |
| Failed retirement callback begins after original fixture timer | 135.632 ms |
| flush returns False | 140.101 ms |
| At return | active_calls=1, cleanup_pending=1 |
| Actual real retirement completes | 155.835 ms |

The original test fails at the EXACT hosted `active_calls == 0` assertion (`1 != 0`). The already-completed native task's registered retirement handle is retained until real accounting completes; active_calls here does not prove a live socket or an interrupted async finalizer. Eventual retirement occurs without changing production.

An unmodified single isolated target invocation passed once (0.39 s), retained as `/data/accessdoc-evidence/windows-pr-original-target.log`. This is not acceptance replacing the failed hosted run and was not repeated until green.

The existing explicit contract test `test_expired_drain_remains_visible_and_next_flush_is_not_false_success`, lines 152-183, requires active_calls=1 and cleanup_pending=1 when retirement is gated beyond the caller's budget, then zero after real release. Ran that separate target once: PASS, 0.35 s (`/data/accessdoc-evidence/windows-pr-pending-contract.log`). It supports the interpretation that bounded incomplete retirement is a designed failure state, not automatically a production ownership regression.

## Narrow recommendation — authorization required before any patch

**Do not widen the 35 ms production reserve, .14 caller budget, .24 assertion, or fixture timer to make this green. Do not retry CI until a favorable schedule occurs. Do not optimistically decrement native ownership.** Evidence supports a fragile fixture completion assumption; it does not justify a production deadline/cancellation patch.

Recommended test-only restructuring for lead review:

1. Separate completed-within-budget and late-pending retirement cases with real callback ownership barriers. For the completed case, arrange the final batch failure EARLIER under the existing budget (rather than making it occur only at the work cutoff), preserve the original 30 ms retirement delay, .14/.24 bounds, zero-active/zero-cleanup assertions, exactly two useful exports, exactly one failed span, and queued-unsent checks. Do not merely drop those assertions or change them to accept either state. This tests useful multi-batch failure + owned cleanup completion with intentional causal headroom instead of an implicit <5 ms scheduler guarantee.
2. For genuine late-cutoff retirement, intentionally gate `_finish` beyond the ORIGINAL caller deadline. Require bounded False, truthful active_calls=1/cleanup_pending=1, no further dequeue/retry/false-success, then release the actual callback and require zero actual ownership after completion. Existing lines 152-183 cover this contract; strengthen/reuse its event-barrier pattern rather than relaxing the completed-case assertions.
3. Preserve a distinct whole-flush/multiple-batch absolute-budget check. Existing `test_work_cutoff_between_successful_batches_needs_no_cancellation` and `tests/test_otlp_deadlines.py::...test_many_batches_share_one_flush_budget` already cover that boundary. A completed-cleanup case with an earlier fault must not be presented as proof that every near-cutoff cleanup finishes within 5 ms of nominal timer due time.
4. Run the same controlled schedule against the explicitly gated pending path and the fixed completed path; retain old-fail/new-pass causal evidence. Lead must approve owned test scope/hash changes before editing, then run normal Windows push/PR acceptance. Local Linux passes do not constitute Windows acceptance.

## Integrity / handoff

`git diff --exit-code -- tests/test_otlp_cleanup_ownership.py app/otlp_export.py app/gateway_transport.py app/deadline.py` passes; repository status clean at handoff.

Unchanged hashes:

- test: `cbdccdf2d6b6bd6d9be5660515463503c535e3df6dce4217c7d1ee0e477a74f6`
- source: `f5020886ba637616d9ed5c8f17b9247e70878314ab51c40488eb4d286af9877d`

Evidence/recommendation frozen. No patch implemented or source change approval requested by this reviewer. Full job logs remain inaccessible publicly; exact hosted dispatch timeline remains unknown. Lead alone handles preview credentials/provisioning.

## Subsequent authorization

The read-only assessment above is preserved. Leader subsequently authorized a test-only correction; implementation, unchanged old evidence, same-schedule new results, frozen test hash, and validation are in `/data/accessdoc-windows-pr-native-fix.md`.
