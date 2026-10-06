# Independent read-only review: Windows native cleanup TEST-ONLY correction

## Verdict

**Scoped acceptance. No critical correctness concern or weakened completion assertion found in this correction.** It separates an early real transport-failure/complete-retirement case from an actual started-HTTP/cancelled-task/retained-retirement case. The original Windows failure's near-cutoff scheduler assumption is no longer required for the completed case; genuine late ownership remains tested explicitly.

This is Linux loopback verification, not a Windows PR PASS or permission to change production. Lead owns the full verifier and hosted acceptance.

## Exact snapshot and scope

Reviewed `tests/test_otlp_cleanup_ownership.py` SHA-256:

`b7718d15626b275c449de2fe4c0bbde34d731809a1b689147e44271d8f42cc78`

Hash matched the requested snapshot at entry and after testing. Review began at HEAD `7fed78dd259421c6676faaf0d47fa932d2a376b3`; lead independently advanced HEAD to `2b79b3219b1120c8f461e2590105a773c2fc785e` during review. The reviewer did not edit, stage, commit, push or change checkout.

Comparison against the fixed **review-start commit**, not moving HEAD:

- Only existing test changed: `test_global_reserve_drains_late_final_batch_retirement`.
- Only new test: `test_global_budget_keeps_late_retirement_owned_until_release`.
- All **15 other original test-method source segments remain exactly identical**.
- `app/otlp_export.py`, `app/gateway_transport.py`, `app/deadline.py` are byte-identical to review-start commit. No production change was authorized or made by this reviewer.

Production hashes:

```
otlp_export.py       f5020886ba637616d9ed5c8f17b9247e70878314ab51c40488eb4d286af9877d
gateway_transport.py e45c6c2a7ad15e94d402c4e82e32d35d5b8fc0292739861ba5b6cd5e7c40c126
deadline.py          01f84d3108c59f55414312aeeb66df918abb20bce581e718d6bdfbd86874d208
```

## 1. Earlier completed-retirement failure is real, not a fabricated successful future

Code anchors: test `:23-66`, particularly `_perform` delegation `:34-38`, real port bind `:49-53`, unchanged delayed callback `:41-46`, and assertions `:55-66`.

- Third attempt redirects only `call.options['url']`; it still calls the actual captured `_Engine._perform` and therefore real aiohttp socket transport, registry ownership, native task and result/retirement machinery.
- The port is bound and held open throughout the assertion block but not listening. This is an intended kernel connection refusal, not a mock status or thrown fixture exception. Different destination port prevents reuse of the successful collector's connection.
- The native task's failure triggers the retained 30-ms callback delay. Actual `_finish` and `_retire` still publish `call.done`, remove registry ownership and decrement native capacity; the test itself does not retire/decrement anything to satisfy assertions.
- `flush(.14) == False`, elapsed `<.24`, delayed hook fired, `active_calls == 0`, `cleanup_pending == 0`, exactly three attempts, exactly two useful exports, one failed span and queued-unsent work are retained. A successful third request, no third task, immediate untracked fake failure, or optimistic cleanup accounting cannot simply turn these checks green.

**Important boundary:** this earlier failure is a native **connection error**, not deadline cancellation. The corrected completed case must not be described as proving that cancellation beginning at 105 ms always finishes in the remaining 35 ms. That is precisely the invalid former assumption. The added pending case and unchanged deadline/finalizer tests supply the separate cancellation evidence.

### Independent measurement under the former controlled pressure model

Captured original `_finish`, allowed the owner's unchanged 30-ms timer to fire, then added the same test-only 20-ms selector-callback pressure used in the prior failing reproduction. Caller budgets and all assertions were unchanged.

- Third real `_perform`: **ClientConnectorError**, registered=true, about **0.36 ms**.
- Failed-task original retirement dispatch became eligible/entered around **35.09 ms** from caller start; an additional 20-ms delay preceded actual `_finish`.
- `flush(.14)` returned False at **55.34 ms** with active=0, cleanup_pending=0, exported=2, queued=7.
- The complete test passed. This independently reproduces the owner's causal after-result, not a retry-until-green run.

Prior baseline evidence (read, not modified) documents the old schedule: return around 140 ms with pending=1; actual retirement around 155 ms. The restructuring grants causal headroom by moving the fault earlier, not by granting the caller extra production time.

## 2. New late-pending test establishes actual started HTTP and truthful ownership

Code anchors: `:68-116`, start barrier/registration `:82-92`, callback gate `:76-81`, bounded first flush `:94-100`, second no-send check `:101-105`, real callback release `:106-112`, and successful queued-span recovery `:113-116`.

- The `_Call` is acquired in the actual engine, added to the sender-owned retirement group and submitted to the actual native task.
- Collector `started` is set only after receiving the complete HTTP body (`tests/test_otlp_deadlines.py:24-36`). This rules out cancellation-before-native-start as an explanation for passing this case.
- The hold collector has not been released when the timed drain begins. The first flush cancels a live HTTP attempt; the patched callback gate retains its completed native task's registered handle until actual `_finish` is released.
- The initial flush must return False within `.24`; two unsent spans remain queued; cleanup_pending=1 and active_calls=1 must both remain truthful. A second `.03` flush must still fail without sending those spans; collector received remains exactly one.
- Only after explicit original-callback dispatch may `call.done` be set and both ownership counters become zero. Then actual held-collector release plus a `.14` flush exports the two queued spans.

Independent instrumented run confirmed **CancelledError**, native task `cancelled=True`, cancellation origin **owner**, registered=true/not retired before callback release. First flush returned False at **140.07 ms**, second at **30.09 ms**; both retained active=1/pending=1 and queued=2. After actual original retirement, recovery flush returned True in about **1.82 ms**, active/pending=0, queued=0, exported=2.

### What the callback gate does and does not prove

The gate holds **retirement accounting after task completion**, not an async coroutine finalizer suspended inside cancellation. It correctly tests retained ownership and no new sends/false-success while retirement remains outstanding. The unchanged `test_native_finalizer_is_not_recancelled_by_retirement_drains` (`:265-301`) separately gates a running async finalizer; cancellation-before-start and repeat-cancel/shutdown tests also remain intact. Do not conflate those separate mechanisms.

The seeded call is a prior native owner rather than a batch dequeued through `_send` during this flush. That is appropriate for the previous-owner barrier contract; useful-export/failure accounting for real exporter batches remains explicitly checked by the completed case and unchanged whole-budget tests.

## 3. Port reservation and remaining non-blocking caveats

- Holding the bound non-listening loopback socket is substantially better than “allocate ephemeral port, close it, then connect.” The connection refusal was independently observed; no provider, proxy or remote endpoint was involved.
- **Windows qualification:** default bind without `SO_EXCLUSIVEADDRUSE` is not an absolute guarantee against another process deliberately binding the same port with Windows reuse semantics. The comment `:47-48` should not be treated as proof of strict exclusive ownership on every OS. There is no evidence of such interference here; a successful third HTTP request would break the delayed-hook/exact-export assertions rather than silently pass. If hardened further, it belongs only to an owner-authorized fixture improvement, not production.
- Arbitrary descheduling can still delay even an early failure beyond 140 ms; no wall-clock test can guarantee scheduling on an indefinitely stalled host. This correction removes the former ~5-ms implicit slack assumption and preserves the bounded failure assertions; it does not claim immunity to host stalls.
- The new pending test supplies `.03` to the second flush and validates retained ownership/queued work, but has no separate elapsed-time assertion for that second call (`:101`). The independently measured return was 30.09 ms, and existing absolute-budget tests remain. A second-call elapsed check or explicit `call.cancel_requested`/task-cancel-state assertion would be optional strengthening, not a critical blocker given the existing complementary coverage and observed real cancellation.

## Independent focused verification

Existing `/data/accessdoc-venv/bin/python`, Python 3.13.14. Empty inherited environment, bytecode/cache disabled, temporary root `/data`, no actual secrets. Focused pytest runner blocks non-loopback socket connections.

- Two corrected targets under controlled 20-ms callback pressure: **2 ran, 0 failures, 0 errors**.
- Unmodified focused ownership + deadline modules: **34 passed, 3 subtests passed in 3.95 s**. No full suite or hosted job retry.
- Independent assertions verified real connection-error/owner-cancellation outcomes, zero/pending/zero ownership progression, useful exports and queued work; original source-method and production-byte checks passed.

Evidence under `/data`:

- `accessdoc-windows-correction-independent-probe.py`
- `accessdoc-windows-correction-independent-probe.log`
- `accessdoc-windows-correction-independent-results.json`
- `accessdoc-windows-correction-focused-run.py`
- `accessdoc-windows-correction-independent-focused.log`
- `accessdoc-windows-test-correction-review.md`

**Handoff:** accept the test-only restructuring at the reviewed SHA for the lead's normal full verifier and Windows PR gate. No production deadline/reserve/cancellation/ownership change is justified by this fixture failure. Do not describe local Linux evidence as Windows acceptance.
