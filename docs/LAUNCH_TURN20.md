
# LAUNCH TURN 20 - Real-Human Stress Re-Verification & Leverage-Repos Audit (2026-09-16)

Independent fresh-run reproduction of every launch gate on `main @ 1d0ec58`
(squash-merge of PR #64), plus a new messy-human chaos suite and a live
four-model Melious probe. Evidence-only turn: no source changes, 0/5
remediation cycles consumed.

## 1. Frozen baseline gates (fresh, this session)
| Gate | Command | Result |
|---|---|---|
| Release gate | `scripts/verify_release.py` | 10/10 PASS; 760 tests OK (12 skipped) in 43.4 s |
| Stress gate | `scripts/stress_test.py` | 15/15 PASS (XSS/YAML escaping, 5000-violation build, tamper, determinism) |
| Concurrency torture | `scripts/concurrent_bench.py` (100 workers x 200 mixed/oversize/corrupt) | 134x200 / 33x413 / 33x422; 0 unexpected 5xx; 0 contract violations; 0 transport errors; 0 admission retries |

Bench deltas vs Turn 19: P50 7649.8 ms (was 10500), P95 18058.0 ms (was 20500),
P99 18921.2 ms (was 21500); RSS floor 42.1 MB / ceiling 304.1 MB / after-recycle
189.5 MB; wall 23.97 s; throughput 8.34 rps; `fault_recovery: PASS`.

## 2. Messy real-human journey suite (new this turn, `human_chaos` evidence)
Emulated against the self-hosted adapter with host/rate guards configured as in prod:
| Journey | Result |
|---|---|
| 25 rapid sequential uploads (paste-spam) | 25x200, p50 7.3 ms / p99 14.5 ms |
| Double-click payload re-submission | 2x200, byte-identical `receipt.json` (determinism holds) |
| 12 abrupt mid-upload socket aborts (tab-close RST) | server survives; `/healthz` 200 in 1.6 ms post-chaos |
| Malformed structures (truncated JSON, wrong Content-Type, empty body, non-axe string) | 4x422, 0 unexpected 5xx |
| 100-request mixed burst @ 50 workers (incl. corrupt re-submits) | 86x200 / 14x422, 0 unexpected 5xx |
| Post-chaos readiness | `/readyz` 200 in 1.0 ms (sub-second recovery bound met) |

## 3. Live production boundary re-verification (`https://access-doc.vercel.app`)
- Malformed JSON -> 400 in 83 ms.
- 11 MB oversize body -> 413 in 196 ms (`FUNCTION_PAYLOAD_TOO_LARGE`, edge-enforced).
- Valid axe-core sample -> 200 in 80.5 ms, `application/zip`, 7168 bytes.
- Immediate re-submission of same payload -> 200 in 70.9 ms, byte-identical bundle.
- `/healthz` 200 (1.05 s cold) and `/readyz` 200 (0.10 s); commit `1d0ec58` reported.
- `/readyz` still reports `gateway.configured:false` - hosted `MELIOUS_API_KEY`
  env var remains unset (operator action, unchanged since Turn 13).

## 4. Melious frontier gateway live probe (production bearer token)
All four chain models answered live via `api.melious.ai/v1/chat/completions`:
| Model | HTTP | Latency |
|---|---|---|
| glm-5.3 | 200 | 546.3 ms |
| glm-5.3-flash | 200 | 849.5 ms |
| qwen-3.8-27b | 200 | 675.4 ms |
| kimi-k3 | 200 | 995.1 ms |
All under the 25-30 s per-model read windows; breaker/failover/cancellation
behaviour covered by the 760-test matrix (test_gateway_*.py) incl. sub-200 ms
failover and 429/5xx circuit-breaking.

## 5. Leverage-repos (repos.md) integration audit
Source: `Kartik24Hulmukh/frontier-oss-ideas` -> `docs/LEVERAGE_REPOS.md` (cloned fresh).
| Leverage asset | AccessDoc usage | Status |
|---|---|---|
| GitHub REST + Octokit patterns | Autonomous PR/merge loop, immutable action refs | Adopted |
| zod-style validation | Strict schema/MIME boundary validation (app/models.py, limits.py) | Equivalent adopted (Python) |
| vitest/node:test discipline | 760-test matrix + verify_release claims gate | Adopted |
| OpenTelemetry ecosystem | app/telemetry.py + OTLP exporter, trace/span ids in JSON logs | Adopted |
| MCP servers pattern | mcp/ adapter exposing scan/remediate to agents | Adopted |
| Upstash/Vercel KV cache | Deferred - stateless bounded demo API by design | Deferred (P1) |
| Exa/Firecrawl deep-web pass | Not core (rule F: no ToS-breaking scrapers) | Rejected per policy |
| Heavy multi-agent frameworks | Rejected per rule F (thin adapters only) | Rejected |

## 6. Council premortem status (unchanged, no regressions)
Large-file memory exhaustion: mitigated (chunked reads, 2 MiB ceiling, RSS recycled
304.1 -> 189.5 MB). Async worker deadlock: mitigated (0 transport errors @100 workers).
OCR/parse timeouts: out of scope (evidence-bundle tool); bad input fails fast
400/413/422. Frontier 429/5xx cascade: breaker/failover green in tests, live upstream
healthy, hosted wiring still off. Overclaiming: claims gate 10/10 PASS; same honest
caveat retained.

## 7. Operator actions (non-code blockers, unchanged)
1. Rotate the GitHub PAT and Melious key pasted in task text (compromised by exposure).
2. Set `MELIOUS_API_KEY` on the Vercel project so `/readyz` flips to configured:true.
3. Edge WAF/rate limiting + spend kill switch in front of the gateway.
4. Wire OTLP exporter to a real collector; named security/accessibility/legal sign-off;
   practitioner adoption evidence (per STATE.md).
