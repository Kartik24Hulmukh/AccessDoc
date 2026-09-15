# Evidence 2026-09-15 — gateway wired into product (`/api/remediate`)

Reproduce: `python3 scripts/concurrent_bench.py .`, `MELIOUS_API_KEY=... python3 scripts/gateway_bench.py .`
(credential from env only). All artefacts here were produced against `main@3d46783` + this branch.

## Honest audit findings that drove this change
1. `app/gateway.py` (PR #39) was fully tested but **not referenced by any product path** — dead code to users.
2. Reasoning models (GLM-5.3, Qwen 3.8 27B) returned HTTP 200 with **empty `content`** at `max_tokens=256`:
   438 tokens billed, zero output, would have shipped as a silent 200/"" to customers.
3. One `/api/remediate` call could hold a `GENERATION_CAPACITY` slot (default 2) for minutes (4 models x 4 attempts x 10s).
4. Read timeouts were retried on the same model, burning the whole budget (observed: 46s wall to static-KB).
5. `normalize_model("Qwen 3.8 27B")` missed (no whitespace folding) -> 422 on human-typed model names.

## Fixes
- New `app/remediate.py` + `POST /api/remediate` (self-hosted adapter); `/readyz` gateway breaker snapshot; `/metrics` counters.
- `extract_text()` handles string / multi-part / reasoning-only replies; empty completion == failed attempt (advances chain).
- `GATEWAY_MAX_TOKENS` (1024), `GATEWAY_READ_TIMEOUT_SECONDS` (15), `GATEWAY_BUDGET_SECONDS` (40) hard wall-clock ceiling.
- 504 -> immediate fail-over (no same-model retry). Dedicated `MAX_CONCURRENT_REMEDIATIONS` pool (8).
- Prompt boundary: <=25 violations, <=300 chars/field, control chars stripped, untrusted-data instruction.

## Results (this machine)
| Probe | Result |
|---|---|
| concurrent_bench 100 workers / 200 mixed reqs | 0 contract violations, 0 unexpected 5xx, P50/P95/P99 5,360 / 8,964 / 10,487 ms, RSS 37.2 -> 298.3 MB, **fault_recovery PASS** |
| gateway_bench live Melious (3 calls/model) | GLM-5.3 p50 2,137 ms · Flash 8,778 ms (1 real 504 recovered on retry) · Qwen 3,094 ms · Kimi K3 16,543 ms — 12/12 OK |
| 429 storm / outage / static-KB probes | PASS / PASS (228 ms fail-fast) / PASS |
| live `/api/remediate` E2E (post-fix) | GLM-5.3: 1,206-token plan in 4.6 s; Qwen: 1,210 tokens in 11.1 s; Flash & Kimi K3 timed out at 15 s on the 1024-token prompt -> budget-bounded static-KB, breakers OPEN, HTTP 200 (never 5xx) |
| unittest discover | 662 tests, 0 failures, 0 errors, 12 skipped (playwright-gated) |
| scripts/stress_test.py | 15/15 |

## Known limits (do not over-claim at launch)
- GLM-5.3 Flash and Kimi K3 are unreliable on long prompts through Melious today (repeated 15 s read timeouts). The chain absorbs this; keep GLM-5.3 primary.
- `/api/remediate` is self-hosted only; the Vercel serverless adapter (`api/handler.py`) does not expose it yet.
- Static-KB fallback is generic guidance, flagged `fallback: true` — UI must label it as such.
