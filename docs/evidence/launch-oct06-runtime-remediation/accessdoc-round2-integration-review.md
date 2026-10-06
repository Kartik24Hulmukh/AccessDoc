# AccessDoc round 2: independent integration review (read-only)

## Decision

**One blocker in the hosted request-scope snapshot: stale prior-request headers are reused for a runtime-owned header-parser rejection on keepalive.** This carries the previous request's traceparent into a distinct rejected request. Exactly-once completion and cleanup still work; this is not double accounting or demonstrated credential/body disclosure.

**Scoped acceptance of the self-hosted early-header drain change** at the hash below: policy order, capacity ownership, bounded drain, valid-upload admission and deadline behavior are preserved in the reviewed code and focused tests. Not a deployed or whole-suite approval.

Lead was notified immediately with the causal reproduction. No source/test edits, checkout operations, commits, provider/remote calls, actual credentials, or full-suite run by this reviewer. Only separate `/data` probe/evidence/report files were written.

## Exact hash snapshot

Review began with HEAD `3519ab789ea3e8fd7077078f07bda4332cfe1b85` plus owner working-tree changes. HEAD independently advanced during review to `4c8ab314c3168bb0322d8a73426828544a0057d8` and the working tree became clean; reviewer did not commit anything. All four reviewed SHA-256 values remained identical before/after focused tests, the independent probe and final inspection:

| File | SHA-256 |
|---|---|
| `api/handler.py` | `1c1a3d489ac634d0efb83b243cadf8457e375c35b61335f5519feaaecb606b56` |
| `app/main.py` | `b453fdd98196234c7864a41ee9dcfe5c7d3641ce2862cd77ca36169c09db6b16` |
| `tests/test_vercel_runtime_lifecycle.py` | `7c6324e7238ad756a2330791bbb95df2fc9ebfecfb5da115fad1f381e4ec702e` |
| `tests/test_main_header_admission.py` | `7681bbef4533e9bd5413565383e3626a7a371a3b5b8f3ae990e5ab3a471be0e5` |

Any later owner refinements are outside this snapshot and require verification against the final hashes.

## Blocker B1: runtime header rejection inherits stale traceparent

### Deterministic real-socket reproduction

Use each existing test runtime shape, on the same keepalive socket:

1. GET `/healthz` with synthetic W3C trace ID `11111111111111111111111111111111` and parent span `2222222222222222`; receive 200.
2. Send GET `/private-parser-canary` with 101 ordinary headers and **no traceparent**. Stdlib `parse_headers` raises the header-count exception; receive 431.
3. Inspect the second SERVER span and completion cleanup.

| Runtime | Second-request trace ID | Parent | Result |
|---|---|---|---|
| `RuntimeInline` (parser envelope bypass) | prior `111…111` | prior `222…222` | FAIL: stale parent reused |
| `RuntimeDelegated` (delegated bypass dispatch) | prior `111…111` | prior `222…222` | FAIL: stale parent reused |
| `StdlibKeepAlive` (normal outer envelope) | fresh root | null | PASS: negative control |

All three emitted exactly two total SERVER spans, rejected status 431, route `/[unmatched]`, and completion states `(False, None, None)` after both requests. The private path was not reflected. An independent check asserted `[True, True, False]` for stale-parent reuse and verified those accounting/cleanup controls.

### Cause

Python `BaseHTTPRequestHandler.parse_request` resets `command` first, then assigns the **new command/path before parsing headers**. If `parse_headers` raises `HTTPException` or `LineTooLong`, its assignment to `self.headers` never completes, leaving headers from the earlier request in a runtime bypass that did not clear them before parsing.

`api/handler.py:253-258` only clears stale headers/path when `command is None`. In this rejection, command is already GET, so that branch does not execute. Decorated `send_error` creates the new scope and request ID, but `_trace` (`:347-349`) adopts the old `self.headers['traceparent']`.

The normal outer `handle_one_request` scope resets headers before parsing, so its control behaves correctly. The new lifecycle tests exercise malformed request-line rejection on fresh sockets and valid keepalive requests, but miss **header-parser failure following a successful keepalive request**. Passing those tests does not cover this causal schedule.

### Required owner refinement

Prevent parser-rejection scopes from adopting unvalidated/stale header state, not merely from carrying `_trace_ctx`. Clearing thread-local context alone is insufficient: the stale headers mint a new context with the old parent.

A narrow owner fix should distinguish parser errors such as 431 from the valid parsed-method rejection path (501), or establish current-request header freshness before trusting `headers`. Do not erase valid inbound traceparent for a fully parsed unsupported method or break nested HEAD ownership. No code prescription is treated as tested here.

Add a regression using this two-request real-socket sequence in **both bypass runtime forms** plus the stdlib control. Require a fresh root/null parent on the header rejection, fresh request ID, one rejection completion, cleared contexts/active flag, finite route vocabulary and no reflected canary. Also cover an oversized single header (`LineTooLong`) if using the same rejection logic. Preserve a valid traced 501 and the existing traced GET → untraced HEAD tests.

This blocker concerns the supported bypass shapes; actual Vercel runtime reuse behavior was not inspected live here. It is not proof of the preview's reported invocation failure or unauthorized access.

## Hosted lifecycle: other checks accepted within scope

- The instance `_request_scope_active` branch makes stdlib parser envelope + decorated dispatch + nested HEAD share one owner. No reset/finalization for nested GET under HEAD; body suppression uses HEAD correctly.
- Runtime-owned dispatch initializes request ID, trace context, status and header state; normal errors/POST completion use that same correlation context.
- `finally` clears thread-local telemetry, `_trace_ctx`, and the active flag even if completion processing raises. Normal telemetry logging/export functions themselves isolate their I/O failures.
- Request/error counters and one completion span match response paths in the matrix; POST capacity release remains in its existing `finally`. No doubled generation release or extra reports counter from adding the scope decorator was established.
- Normal idle stdlib keepalive resets parse fields before waiting and does not re-account the previous request. Scope flag/context cleanup passes in all tested dispatch forms.
- Auth/operation denials remain before POST admission/body reads. The decorator does not introduce request-body reads or emit header secrets. HEAD/OPTIONS/unsupported methods remain within the existing route policy.
- Actual Vercel parser replacement, readonly filesystem behavior and deployment startup still require the lead's live preview verification. The new scope uses no filesystem writes. No deployed success inferred from local emulation.

## Early-header admission: scoped acceptance

`app/main.py:245-259` preserves host/route checks (preceding range), auth, origin, operator disable, readiness and rate limits **before** header validation/drain. A malformed or oversized body cannot evade a policy denial by obtaining the earlier drain path. Policy-denial tests confirm no generation admission and no drain for their conflicting headers.

- `_validate_body_headers` recognizes Content-Type, unsupported encoding/framing and invalid/multiple lengths before generation acquisition. Invalid framing now returns the intended 422 even with saturated generation slots, rather than incidental BUSY.
- Known oversize is drained **outside the generation pool but inside the existing connection pool**. `_drain` retains 64-KiB chunks, 16-MiB drain cap, `collect=False` and a single absolute deadline. POST closes; byte-cap/deadline exhaustion does not begin another drain. Header-only 413/422 paths never increment/decrement `ACTIVE_GENERATIONS` or release an unacquired generation permit.
- Valid bodies are not pre-buffered. They still acquire generation capacity, increment active count, read/parse/render/write, then decrement/release exactly once. Two declared-valid quiet uploads block a third healthy request until their release, as intended for memory bounds.
- Valid headers are checked twice: pre-admission and again in `_read`. The pre-admission valid deadline is discarded; the read's deadline starts after bounded queue acquisition, just as before this change. No extra valid-body read, restarted drain or weakened existing upload deadline was identified. This is redundant checking, not a release blocker.
- The two-oversize test uses actual `Server` connection capacity, production 15-second budget and an event barrier. A healthy bundle is received while both drains are still pending, then offenders are explicitly half-closed. It proves the improvement without relying on a shortened timeout or hoping uploads finished first.
- Tracked connection/generation accepted/released counts, active generations and quiet/error paths recover. Existing real-socket quiet/dripping/deadline/oversize tests also pass.

Residual connection-pool saturation by many slow clients remains bounded by the existing connection cap and deadline; this change promises render-slot isolation from known rejection, not immunity to all slow clients. Hosted upload admission remains unchanged by this self-hosted patch.

## Focused validation and evidence

Executed once using existing venv Python 3.13.14, empty inherited environment, bytecode/cache disabled, `/data` temporary root, and non-loopback socket connections blocked:

- `test_vercel_runtime_lifecycle.py`
- `test_main_header_admission.py`
- `test_hosted_lifecycle.py`
- `test_http_body_deadlines.py`
- `test_hosted_boundary.py`
- `test_reporter_table_linefold.py`

**40 passed, 56 subtests passed in 8.59 s.** This is focused integration validation, not the full commit gate. The independent B1 probe is intentionally outside the owner test modules and demonstrated the missing case despite this PASS.

Separate files under `/data`:

- `accessdoc-round2-integration-tests-run.py`, `accessdoc-round2-integration-tests.log`: focused protected runner/result.
- `accessdoc-round2-parser-rejection-probe.py`, `accessdoc-round2-parser-rejection-results.json`, `accessdoc-round2-parser-rejection-probe.log`: causal B1 reproduction and clean control.
- `accessdoc-round2-integration-review.md`: this hash-scoped review.

**Release handoff:** owner corrects B1 and adds its focused regression; recheck final file hashes and run the lead's full commit gate, then live preview verification. Do not treat these scoped tests as resolving the Vercel invocation or macOS CI issues.
