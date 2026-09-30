# Turn 5: independent native gateway review

## Outcome

Two concrete lifecycle/deadline defects were reproduced in the initial uncommitted gateway. Both ceased reproducing after concurrent changes by the parent. The final scoped run passed **25 tests**. **No remaining severe defect was established in the reviewed cases.** This is a limited local engineering review, not a deployment, production, provider-billing, or human-review certification.

I did not modify, stage, or commit repository files. All review scripts/results were written under `/data`, outside `/data/AccessDoc`. Imports/tests used `PYTHONDONTWRITEBYTECODE=1` and pytest cache was disabled. The source changed during this review; initial findings and subsequent rechecks are distinguished below.

## Confirmed findings and recheck

### 1. Hedge readiness wait could escape the absolute chat deadline — fixed in recheck

Initial location: `app/gateway.py`, `_chat_hedged.launch`, formerly `ready.wait(hedge)` (around line 607).

A lane that encounters an open circuit returns before setting `ready`. The dispatcher nevertheless waited the entire hedge interval, rather than the lesser of that interval and the remaining absolute budget. This is a real deadline failure; it requires no upstream request and is not scheduler overshoot.

Reproduction in `/data/accessdoc-turn5-native-repro.py`:

- Native `ModelGateway`, synthetic key, one canonical model, `budget_seconds=0.03`.
- Trip its circuit before `chat()`.
- Set `GATEWAY_HEDGE_DELAY_MS=500`.
- Initial elapsed: **0.5010 s**, versus **0.030 s** authorization. Static fallback, zero I/O calls.

At the final reviewed source, readiness wait is clamped using `max(0.0, min(hedge, deadline - time.monotonic()))`. The same repro returned in **0.0024 s**, because the lane now also signals readiness on completion. The new `test_circuit_skip_does_not_wait_past_absolute_deadline` passed.

Impact before fix: operator-selected long hedge delays or sufficiently small request budgets could exceed the promised wall-clock bound without any HTTP activity.

### 2. A cancelled hedge loser could remain in uninterruptible 408 retry sleep — fixed in recheck

Initial locations: `app/gateway.py`, `_chat_serial` retry backoff (formerly `time.sleep` around line 857), and winner cleanup joins in `_chat_hedged` (around lines 640–643).

An HTTP 408 with `Retry-After: 2` put the primary lane to sleep. A successful fallback cancelled the request event and native I/O, but that event did not interrupt the ordinary thread sleep. Winner cleanup therefore waited for the sleeping loser until its backoff ended or the common deadline expired.

Reproduction uses a `ThreadingHTTPServer` bound exclusively to `127.0.0.1`, serving a 408 for the primary and a small valid JSON response for the fallback. `GATEWAY_HEDGE_DELAY_MS=30`, `base_backoff=0`, `max_sleep=2`, `max_retries=1`; no provider contacted.

Initial results:

- With a 3 s budget, fallback arrived at **34.2 ms**, but chat returned the fallback at **2.0050 s**.
- With a 200 ms budget, fallback arrived at **33.2 ms**, but chat returned at **200.3 ms** with **one `gateway-hedge` thread still alive**. It had ended by the next 80 ms observation.
- The native transport had zero active calls/inflight work at return. **No late POST was observed.** This was a sleeping owned-lane leak/latency defect, not evidence of detached network transmission.

At the final reviewed source, the hedged path uses `cancel.wait(delay)` and retains ordinary sleep only when no cancellation event exists. Rechecks returned at **34.0 ms** and **34.2 ms**, respectively, with zero hedge threads at return. The new `test_408_retry_wait_is_cancelled_when_sibling_wins` passed.

Impact before fix: healthy fallback latency could be dominated by the losing attempt's retry backoff, defeating prompt cancellation and the intended low-latency hedge behavior.

## Tests and reproduction

Runtime: existing `/data/accessdoc-venv/bin/python`; installed aiohttp **3.14.3**. The system Python lacked aiohttp/pytest; no dependency installation was performed.

Commands:

```sh
cd /data/AccessDoc
PYTHONDONTWRITEBYTECODE=1 /data/accessdoc-venv/bin/python -m pytest \
  -q -p no:cacheprovider \
  tests/test_gateway_native_ownership.py \
  tests/test_gateway_budget_boundaries.py \
  tests/test_gateway_hedged_failover.py

PYTHONDONTWRITEBYTECODE=1 /data/accessdoc-venv/bin/python \
  /data/accessdoc-turn5-native-repro.py
```

Evidence files:

- `/data/accessdoc-turn5-scoped-tests.txt`: initial **23 passed in 4.93 s**.
- `/data/accessdoc-turn5-native-repro.py`: standalone deterministic reproduction harness.
- `/data/accessdoc-turn5-native-repro.json`: initial failing observations.
- `/data/accessdoc-turn5-native-recheck.json`: post-change successful observations.
- `/data/accessdoc-turn5-scoped-recheck.txt`: final **25 passed in 5.06 s**.

The synthetic harness clears HTTP/HTTPS/all proxy settings and uses `NO_PROXY=*`. It uses only a literal synthetic API key and loopback HTTP, or a circuit-open case with no request. Scoped ownership tests use a synthetic resolver for the cancellation test.

## What was checked

- Absolute admission, header, response-body deadlines and cancellation drain.
- Global upstream slot acquisition/release and reusable per-owner aiohttp sessions.
- Cancellation checks around admission/submission and request start.
- Owner cancellation and close paths.
- Shared ledger reservation/reconciliation across fallback, retries and hedge losers.
- Missing/malformed usage, positive reported overspend, small budgets, and decoded/wire response bounds.
- Existing fake-DNS ownership test and installed aiohttp resolver routing: with `use_dns_cache=False`, `_resolve_host` awaits the supplied resolver directly rather than using aiohttp's shielded cache-resolution task.

The tested cases maintained bounded reservations and did not report provider overspend as a successful answer. That statement applies only to the supplied synthetic usage metadata; it does not establish actual tokenization or provider charges.

## Explicit limits

- No external provider/network access, live credentials, git credential helpers, browser actions, staging, or commits were used for this review. No production or human-review claim is made.
- The DNS test replaces the resolver. It establishes cancellation of that await and absence of a late loopback POST, **not** complete teardown of a real c-ares DNS query under every OS/network failure. Real DNS/connect/TLS and proxy fault injection were not performed.
- Concurrent close versus submit, process fork/reload, Windows selector behavior, long-duration soak, and pathological decompression/CPU scheduling were inspected only partially or not exercised. No severe finding is asserted without a reproduction.
- Native client construction uses `trust_env=True`. Installed aiohttp contains executor-backed environment/netrc/proxy discovery. Therefore the review cannot support a broad claim that this transport never uses executor threads at all; it supports the narrower tested absence of detached Requests POST workers. Those dependency discovery paths were not intentionally fault-injected or credential-inspected.
- Deadline cleanup reserves at most 10 ms inside the HTTP budget. Passing these tests is not a mathematical guarantee of zero tasks at return under arbitrary event-loop blocking or cancellation-resistant callbacks.
- This is a working-tree review. Parent edits occurred concurrently, so any subsequent source changes need another scoped rerun.

## Source fingerprints captured with passing recheck (SHA-256)

```text
4dc2d415a91aadf250afdf913f9a7e69d2edd56ba985cfff87556d932a291029  app/gateway.py
dc4a3d7ab9a0a5d3c4169ced692b352f6e3c74bccc805148bd1592ff7c524d40  app/gateway_transport.py
9fdac49a04d17edb9cf2eb4be9710c82d753a2fd34a1d58165c70a3169e03fad  app/gateway_budget.py
682a5ea334b720d48a52ba8b7163d8e8527c7cf1727359e9bfc955ed2b06ed23  tests/test_gateway_native_ownership.py
```

Source-drift note: a later read after the report was drafted returned gateway.py SHA-256 `7cccf763f0d983d4a349312368b3a64d56021ef0169a77518091addad2da3293`; the other three fingerprints remained unchanged. This later version was not covered by the recorded 25-test run. Rerun the scoped command against the release candidate.
