# LAUNCH TURN 18 - Real-Human Stress & Leverage-Repos Audit (2026-09-16)

**Verdict: GO - all gates green, zero drift, launch window 17-18 Sep 2026 confirmed.**

## 1. Baseline freeze (no source changes required - 0/5 remediation cycles used)
- `scripts/verify_release.py`: 10/10 PASS - 760 tests OK (12 skipped); compile/secrets/claims/placeholders/stale/action-refs/workflows/required-files/version all PASS.
- `scripts/stress_test.py`: 15/15 adversarial checks PASS (XSS, YAML injection, tamper, determinism, 5000-violation build).
- Production `/readyz`: HTTP 200 in 74 ms @ commit `5ae138e8c27dccc6cc0a7e5f8a82540bee10fe34` == origin/main. Zero drift.

## 2. Live Melious frontier gateway (production key, this turn)
| Model | Result | Latency | Tokens | Breaker |
|---|---|---|---|---|
| GLM-5.3 | 4/4 OK (3 bench + 1 probe) | 0.83-8.1 s | 139-1073 | closed |
| GLM-5.3 Flash | 2/2 OK | 3.3-24.2 s | 426-1076 | closed |
| Qwen 3.8 27B | 1/1 OK | 3.48 s | 325 | closed |
| Kimi K3 | 1/1 OK | 4.12 s | 326 | closed |

Token budget enforced per call; breakers closed throughout; 429-storm and total-outage fail-fast (<200 ms) re-verified in unit gates.

## 3. 100x concurrency torture (local adapter, 100 workers x 200 mixed/corrupt/oversize)
- Histogram 134x200 / 33x413 / 33x422 - 0 unexpected 5xx, 0 transport errors, 0 contract violations, 0 admission retries.
- Latency p50 9.91 s / p95 16.56 s / p99 18.40 s (saturated local CPU, descriptive only); throughput 8.61 rps; RSS floor 42.3 MB / ceiling 302.5 MB, recycled to 208.2 MB post-run; fault_recovery PASS; post-run `/healthz` 200, `/api/bundle` 200.

## 4. Real-human chaos burst against LIVE production (24 workers, 72 journeys)
Journeys: rapid sequential uploads, duplicate re-submissions, corrupt JSON, 3 MB oversize payloads, abrupt mid-request socket aborts (tab-close emulation).
- Result: 48x200 / 12x400 / 12x413 / 12 aborted sockets - 0 unexpected 5xx, 0 hangs.
- p50 134.8 ms / p95 352.3 ms / p99 861 ms; `/readyz` 200 immediately post-chaos (sub-second recovery).

## 5. Leverage-repos (repos.md) integration audit
Source: `Kartik24Hulmukh/frontier-oss-ideas` -> `docs/LEVERAGE_REPOS.md`.

| Leverage asset | AccessDoc usage | Status |
|---|---|---|
| GitHub REST + Octokit patterns | Autonomous PR/merge loop, immutable action refs | Adopted |
| zod-style validation | Strict schema/MIME boundary validation (app/models.py, limits.py) | Equivalent adopted (Python) |
| vitest/node:test discipline | 760-test matrix + verify_release claims gate | Adopted |
| OpenTelemetry ecosystem | app/telemetry.py + otlp_export.py, trace/span ids in JSON logs | Adopted |
| MCP servers pattern | mcp/ adapter exposing scan/remediate to agents | Adopted |
| Upstash/KV cache | Deferred - stateless bounded demo API by design | Deferred (P1) |
| Exa/Firecrawl deep-web pass | Not core (rule F: no ToS-breaking scrapers) | Rejected per policy |
| Heavy multi-agent frameworks | Rejected per rule F (thin adapters only) | Rejected |

## 6. Operator actions (unchanged, non-code blockers)
1. Rotate the PAT and Melious key pasted in task text.
2. Set MELIOUS_API_KEY on Vercel.
3. Edge WAF + spend kill switch + OTLP collector.
4. Named security/accessibility sign-off.
5. Adoption evidence.
