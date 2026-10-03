# Turn 5 — read-only SRE / architect council audit

**Repository:** `/data/AccessDoc`, commit `78736f2`.
**Verdict:** Three reproducible launch-blocking resource/budget gaps remain. Passing body-reader, billing-hold, breaker-epoch and readiness regressions does not establish hard cancellation or a hard cumulative token ceiling. Severity here is operational launch severity, not a security CVSS claim.

No repository files were changed. No provider calls, deployments, private credential files, or private tool-result files were used. All injected HTTP traffic went to numeric loopback with a synthetic key; child commands ran with an empty inherited environment. Bytecode and pytest cache writes were disabled. The user's independently running baseline was not stopped, inspected or rerun in full. The previously reported live Kimi result (gate 11/12 failing at 40 seconds) remains unresolved; this review supplies no replacement live evidence. Do not widen that budget or remove/downshift the model to make the gate green.

## Evidence and reproduction

External, non-repository audit artifacts:

- `/data/accessdoc-turn5-faults.py`: executable local fault-injection harness.
- `/data/accessdoc-turn5-measurements.json`: measurements from the final controlled run.
- This report: `/data/accessdoc-turn5-council-sre.md`.

Run the harness with the existing environment:

```bash
env -i PATH=/data/accessdoc-venv/bin:/usr/bin:/bin HOME=/data \
  PYTHONDONTWRITEBYTECODE=1 \
  /data/accessdoc-venv/bin/python /data/accessdoc-turn5-faults.py
```

The harness imports the actual gateway and uses its real Requests/urllib3 transport. Only the first fault replaces the system resolver with a bounded Event-controlled stall. Other HTTP faults use a real loopback server. Gateway logging is muted to keep measurements isolated from stdout and exporters. The server closes completed responses in the final run to make resolver admission deterministic on every new connection; an earlier exploratory keep-alive run bypassed some resolver calls through reuse and is not the quantitative basis below. Every injected gateway thread was drained after releasing the fault; final remaining hedge threads: **0**.

### Scoped existing regression run

**47 passed, 6 subtests passed in 6.40 seconds.**

```bash
cd /data/AccessDoc
env -i PATH=/data/accessdoc-venv/bin:/usr/bin:/bin HOME=/data \
  PYTHONPATH=/data/AccessDoc PYTHONDONTWRITEBYTECODE=1 \
  /data/accessdoc-venv/bin/python -m pytest -p no:cacheprovider -q \
  tests/test_gateway_budget_boundaries.py \
  tests/test_gateway_strict_cancellation.py \
  tests/test_gateway_error_deadlines.py \
  tests/test_gateway_breaker_epochs.py \
  tests/test_gateway_response_bounds.py \
  tests/test_gateway_readiness.py \
  tests/test_hosted_admission.py \
  tests/test_http_body_deadlines.py \
  tests/test_idle_keepalive_telemetry.py \
  tests/test_process_telemetry.py
```

These results are scoped local regressions, **not** a new full-suite or live-provider certification.

## 1. Winner/deadline cancellation does not stop pre-socket work or late dispatch

**Critical invariant violated:** a completed/cancelled request must not later initiate paid upstream work; upstream resource ownership must remain bounded until work really terminates.

### Files and lines

- `app/gateway.py:344–348`: one shared Session; `HTTPAdapter(pool_connections=25, pool_maxsize=100)` uses the default `pool_block=False`; finalization is not an explicit cancellation/drain lifecycle.
- `app/gateway.py:616–619, 624–649`: each lane starts a new daemon thread, with only per-chat in-flight limits; a relative remaining duration is passed into the lane.
- `app/gateway.py:678–683, 688–695`: dispatcher sets an Event and returns, without cancelling a socket, joining lanes or retaining a capacity permit until terminal I/O.
- `app/gateway.py:700`: each lane recreates its deadline from its own start time instead of sharing the dispatcher's absolute deadline.
- `app/gateway.py:739–762`: cancellation is checked only before `_post`; `ready.set()` occurs before socket opening, so it does not mean the HTTP request is actually in flight.
- `app/gateway.py:407–425`: Session.post can enter blocking name resolution/connect/header parsing; there is no cancellation check between that work and request transmission.
- `app/remediate.py:20–33`: singleton shares the pool and breakers, but exposes no explicit shutdown/drain hook.
- `app/main.py:249–263, 293–296, 310–313`; `api/handler.py:548–564`: admission permits and active-request bookkeeping cover handler lifetime, not detached gateway lanes.

### Reproduction and measured result

Shared gateway, two canonical models, **300 ms** chat budget, **30 ms** hedge delay, four sequential chats. For each chat, block the first `socket.getaddrinfo` call; let the fallback resolve and reply immediately. After all chats return, wait another **400 ms**, then release the blocked resolvers.

- All four chats returned a non-fallback `glm-5.3-flash` success in **40.47, 33.54, 36.69 and 39.26 ms**.
- Before releasing DNS, only the four fallback requests had reached the server.
- After waiting beyond every chat's deadline: **4 live `gateway-hedge` threads** remained.
- Releasing DNS caused **4 primary HTTP POSTs** to arrive **402.00–404.70 ms after the last chat had already returned**—after all four 300 ms deadlines, despite cancellation.
- Actual installed adapter configuration: `pool_maxsize=100`, **`pool_block=False`**.

This is not merely an already-billed in-flight request continuing. The primary had no socket yet; it transmitted only after the sibling won and the deadline expired. The thread subsequently discovers the body deadline, but that is too late to prevent dispatch. No real billing occurred; the paid-work consequence is inferred from production use of the same POST path.

### Impact and narrow native fix proposal

Repeated fast hedged successes can release HTTP admission slots while slow/uninterruptible losers accumulate. The per-chat limit of two does not bound process-wide live workers/connections. `pool_maxsize` is an idle-connection retention limit under `pool_block=False`, not a socket admission ceiling. A shared Session alone does not establish safe resource lifecycle.

1. Add a **process-wide `BoundedSemaphore`** for upstream attempts, retained until the actual worker terminates, not until its dispatcher/HTTP handler returns. Use a fixed worker pool with bounded submission admission; `ThreadPoolExecutor` alone has an unbounded work queue.
2. Store each attempt's Future/owned transport handle. Use `Future.cancel()` for genuinely queued work, and check the same cancel Event plus **absolute monotonic deadline** after admission and immediately before sending. Pass the absolute deadline into every lane; do not recreate it from stale relative duration.
3. Running I/O needs an owned abort mechanism and drain. **`Event.set()`, `Future.cancel()` on a running task, daemon threads, or `Session.close()` are not hard cancellation of libc DNS.** If retaining blocking Requests/system DNS while promising hard worker termination, use a bounded supervised worker-process boundary (process-owned reusable Sessions, terminate/join/replace on expiry). Socket shutdown can abort owned connected I/O, but not a resolver that has not produced a socket.
4. Add explicit gateway shutdown/drain and call it during service shutdown. Keep connection-pool capacity aligned with upstream admission; do not just flip `pool_block=True`, because Requests' pool wait also needs deadline-aware bounded admission.

**Regression gate:** block DNS beyond deadline; let a sibling win; release DNS afterwards. Assert **zero late POSTs**, bounded live upstream tasks across repeated calls, queued cancelled work never executes, and shutdown drains/terminates all owned workers. Test pool saturation independently of HTTP-handler admission. Merely asserting a fast winner is insufficient.

## 2. Absolute response deadline starts enforcing too late: slow-drip headers bypass it

**Critical invariant violated:** the deadline must bound status/header parsing as well as response bodies, in both supported serial and hedged paths.

### Files and lines

- `app/gateway.py:415–425`: an absolute deadline is calculated, but Session.post must return a response before it is enforced. Connect/read timeouts are inactivity windows, not a full-request wall-clock limit.
- `app/gateway.py:450, 472–537`: `_read_bounded` re-arms the socket deadline **only after response headers have been parsed**.
- `app/gateway.py:579–588`: negative hedge delay is a supported operator setting selecting serial execution.
- `app/gateway.py:660–675, 688`: hedged dispatcher allows an unconditional 250 ms reporting grace and returns without terminating blocked header I/O.

### Reproduction and measured result

Real loopback HTTP server consumes the POST, sends `HTTP/1.1 200 OK\r\nX-Drip: `, then sends one header byte every **20 ms**, for 30 bytes, before finishing headers and a valid JSON body. No interval approaches the inactivity timeout. One model, **150 ms** total budget.

| Path | Configured budget | Measured chat duration | Result | Live hedge threads at return |
| --- | ---: | ---: | --- | ---: |
| Supported serial (`GATEWAY_HEDGE_DELAY_MS=-1`) | 150 ms | **614.35 ms** | Static fallback | 0 |
| Hedged (`GATEWAY_HEDGE_DELAY_MS=30`) | 150 ms | **400.46 ms** | Static fallback | **1** |

Serial execution exceeded budget by **464.35 ms**. Hedged execution returned at budget plus its 250 ms grace, but its header-reader thread remained live. The later body check does reject the answer; it does **not** reclaim the preceding wall time or cap header I/O. The proof uses a finite 600 ms drip; sustained header dripping was not run indefinitely and its production duration is not measured here.

### Impact and narrow native fix proposal

Recent deadline fixes protect success bodies and 429 billing peeks, not the status line/headers. In serial mode, a legal operator configuration loses its total latency bound. In hedged mode, response latency and worker lifetime diverge; this compounds finding 1 even without DNS faults.

Enforce the same absolute deadline through **DNS/connect/TLS/request write/status line/headers/body**. For a Requests-compatible transport, a timeout argument alone cannot provide that guarantee. A deadline-aware connection/parser must recompute the remaining deadline before blocking reads, including header reads; alternatively the native supervised-process boundary from finding 1 can enforce the outer hard timeout across the whole blocking call. Keep the existing bounded decoded body reader. The hard caller deadline should not silently gain 250 ms for accounting: process terminal accounting separately, or explicitly document any distinct drain grace without treating it as request-budget compliance.

**Regression gate:** real-socket slow-drip **status line and headers**, both serial and hedged modes, with a finite independent cleanup deadline. Assert caller return within the stated budget/tolerance and no worker/socket still alive beyond the bounded drain contract. Also test pre-response connection/DNS stalls. Do not widen model read windows or total budgets.

## 3. Cumulative token ceiling is not a hard spend budget

**Critical invariant violated:** reservations must bound all possible billable tokens before dispatch; missing usage must not restore spend capacity, and prompt tokens cannot be omitted from a budget described as cumulative total tokens.

### Files and lines

- `app/gateway.py:31–33`: contract claims a cumulative token ceiling across every model/retry.
- `app/gateway.py:421–422`: `max_tokens` limits completion output, not prompt plus completion total.
- `app/gateway.py:609, 630–639`: hedged reservations cover maximum **completion** only, excluding duplicated prompt input across lanes.
- `app/gateway.py:699–703, 716–737, 759–762`: serial attempts use reported spend to decide the next completion authorization; they do not reserve each attempted completion before dispatch.
- `app/gateway.py:776–781`: absent/malformed usage becomes zero.
- `app/gateway.py:789–796`: success is returned even when reported cumulative usage exceeds the ceiling.

### Reproduction and measured result

Both use real local HTTP with production gateway parsing; response usage is intentionally controlled by the local fixture, not measured from a model tokenizer or live provider.

**A. Missing usage, empty completion followed by success:** serial mode, two models, token budget **100**, maximum completion **100**. First response is HTTP 200 with empty content and no usage; second is HTTP 200 with `ok` and no usage.

- Captured outgoing `max_tokens`: **[100, 100]**.
- Cumulative completion authorization: **200 against a ceiling of 100**.
- Gateway returns success and reports **0 tokens**.

This proves a 2x authorization gap, not that a real provider actually billed 200 tokens. The first empty response could have spent hidden reasoning or its response could have lost usage metadata; the caller cannot establish zero cost from absent usage.

**B. Total usage includes input:** hedged path with one model, budget **100**, outgoing `max_tokens=100`, and a long input prompt. The fixture returns valid usage metadata: prompt **100**, completion **1**, total **101**.

- Gateway returns non-fallback success with **101 reported tokens**, above its **100** ceiling.
- Even a provider honoring `max_tokens` can exceed the total ceiling because input tokens are additional; discarding an overspent answer afterwards would not undo billing.

### Impact and narrow native fix proposal

The existing reservation test establishes at most one hedged completion reservation when the ceiling fits one completion. It does not prove a total-token ceiling. Serial fallback on missing usage can reauthorize the same full amount, while hedged lanes duplicate unreserved input cost.

Use a single per-chat **lock-protected reservation ledger** shared by lanes and retries. Before every dispatch, reserve a trusted per-model prompt-token count plus a bounded completion allowance; derive the allowance from remaining total budget. Count chat framing/system input as well as user input. Reject/degrade before dispatch when prompt input cannot fit. Use the pinned model's trusted tokenizer or a documented conservative bound; without one, fail closed for the hard-budget contract rather than assume prompt cost is zero. Do not rename the existing total ceiling to an output-only limit or widen it as a cosmetic fix.

Retain reservations for failed, empty, timed-out, cancelled, or missing/malformed-usage attempts unless trustworthy usage proves a safe reconciliation. A retry requires a new reservation. Validate returned usage and surface a contract violation if it exceeds the reserved amount, but prevention must happen before dispatch. The ledger must include losing hedged attempts even when a winner's result is returned; winner-only `GatewayResult.tokens` is not aggregate spend.

**Regression gate:** missing usage, malformed usage, empty/reasoning-only completion, retry/fallback and losing lanes; assert total authorization plus prompt reservations never exceeds the ceiling. Include prompt-only exhaustion and successful returned usage above the reserved bound. Existing negative-usage and small-remaining-completion tests should stay unchanged.

## Readiness, telemetry and coverage disposition

- **Recent fixes retained:** billing error-peek deadline enforcement, passive account-wide billing hold, and epoch-bound breaker outcomes all passed the selected regressions. None of the findings requires rolling these back.
- **Readiness is not claiming a healthy provider:** `app/remediate.py:98–114` deliberately returns `unknown` for configured/unprobed AI and `degraded` for missing configuration or billing hold. Both adapters preserve core readiness during optional AI degradation. Keep that behavior; do not add paid readiness probes to fabricate a green status.
- **Configured transport qualification:** `app/remediate.py:102, 211–213` examines the environment key rather than the effective instance key/transport. The local test-hook gateway with an explicit synthetic key and successful injected transport still reports `configured=false`, `degraded/not_configured` when the environment is empty. This is a real definition mismatch for injected/explicit-key gateways, but **not counted as a fourth critical finding**: production singleton construction is environment-based and `configured` does not mean reachable. Prefer a consistent, secret-free effective-transport/configuration predicate if these paths are supported; keep reachability `unknown` until evidence exists.
- **Telemetry reviewed:** `app/telemetry.py:54–76, 80–119, 122–132` uses thread-local trace context, synchronous flushed JSON logging and best-effort span export. No independently reproduced critical telemetry fault is claimed. Fault measurements mute gateway logging, so blocked stdout/export behavior and cross-thread trace continuity are not certified by this run. `gateway.health()` (`app/gateway.py:862–873`) reports breaker/budget state, not owned live lanes; a successful/returned handler count cannot demonstrate worker drain.
- **Existing coverage gap:** body deadline tests begin after headers; hedged success tests check first-success latency/arrival order, not that losing workers terminate; budget tests trust usage and bound completion only; hosted admission tests bound handler capacity/handoff rather than orphaned upstream work. Add narrowly targeted tests for the invariants above, not another broad research or cosmetic benchmark pass.

## Release decision

**Hold the hard resource/time/token-budget claim and live-model gate.** The three concrete gaps are: detached/late-dispatch work, pre-body deadline escape, and unreserved cumulative spend. Native admission, owned cancellation/drain, an end-to-end absolute deadline, and a conservative shared reservation ledger are required. Faster static fallback or a fast hedge winner is not evidence that outstanding work stopped or spend stayed within budget.
