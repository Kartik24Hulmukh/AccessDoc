# Gateway Strict Wall-Clock Cancellation (2026-09-15)

## Failure reproduced
`ModelGateway._post` consumed provider bodies with `iter_content(chunk_size=16384)`.
`http.client` blocks inside that call until 16 KiB arrive or EOF, so a provider that
drips one byte per interval held a worker for `16384 x interval` regardless of the
admission deadline. Independent slow-drip probe (PR #47): 200 ms budget -> 1104 ms actual (FAIL).

## Remediation (first principles, not a patch)
`ModelGateway._read_bounded` now:
1. re-arms the live socket timeout to `min(remaining_budget, read_window)` before **every** read;
2. reads with `urllib3.HTTPResponse.read1`, which returns as soon as any bytes arrive;
3. checks the wall-clock deadline between reads and raises `504` -> breaker failure -> fallback;
4. keeps the decoded-byte cap (`GATEWAY_MAX_RESPONSE_BYTES`, gzip-expansion safe) and closes every response.
Non-urllib3 transports keep the chunked `iter_content` contract with identical guards.

## Evidence
* `tests/test_gateway_strict_cancellation.py` real-socket slow-drip server (1 B / 50 ms):
  300 ms budget -> fallback in < 450 ms; every attempt logged as 504. **PASS** (was FAIL).
* Gateway suites: 33 passed. Full suite: 705 passed, 0 failed, 12 skipped (unit + integration + E2E journeys).
* `bench-after-strict-cancel.json`: 100 workers / 200 mixed hostile requests -> 134x200, 33x413, 33x422,
  0 unexpected 5xx, 0 transport errors, recovery probes 200/200, **PASS**.
  P50/P95/P99 9156 / 17556 / 18145 ms (PR #47: 8344 / 18899 / 20207); 8.33 req/s (8.10);
  RSS floor/ceiling/after 42.4 / 329.2 / 211.8 MiB (42.3 / 316.8 / 200.8). Shared-CPU sandbox, descriptive only.
* `gateway-bench-live-2026-09-15.json` (live Melious, 25 s budget): Qwen 3.8 27B 3/3 200 (P50 10.9 s, 1075 tok);
  Kimi K3 1/3 (23.2 s, 1193 tok; two 504 at the 25 s window); GLM-5.3 and GLM-5.3 Flash 0/3 within their
  15 s / 25 s windows -> breakers OPEN after 3 failures as designed. A direct probe minutes later returned
  GLM-5.3 200 in 5.5 s (1073 tok) through the same gateway: upstream latency variance, not a client defect.
  429-storm fallback PASS, outage fail-fast PASS (222 ms), static-KB last resort PASS.

## Remaining owner gates (unchanged, explicit)
* Install `MELIOUS_API_KEY` in Vercel (production `/healthz` reports `gateway.configured=false`).
* With a 40 s budget, GLM-5.3 (15 s) + GLM-5.3 Flash (25 s) timeouts can exhaust the budget before Qwen is
  reached in a slow-upstream window; set `GATEWAY_BUDGET_SECONDS=60` or `GATEWAY_READ_TIMEOUT_GLM_5_3=10`
  in production until per-model chain reservation lands.
* RSS plateau on deployed capacity, OTel collector/alerting, provider quotas, design-partner traction.
