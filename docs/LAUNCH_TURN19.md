# AccessDoc — Turn 19 Launch Hardening Evidence (Independent Re-Verification)

**Run date:** 2026-09-16 (session continuation) | **Audited commit:** `main @ c246f56efcead9ba5a123364aca4e0bb38011041` (PR #63, unchanged since Turn 18) | **adapter_version:** `0.7.0-beta.7`

## 1. Zero-drift confirmation
Fresh clone of `Kartik24Hulmukh/AccessDoc` resolves to `c246f56`, identical to live `/readyz` production commit. No local modifications existed prior to this evidence commit.

## 2. Full release gate (fresh run, this session)
- `scripts/verify_release.py`: **10/10 PASS** (compile, 760 tests / 12 skipped in 42.9s, secret patterns, claims, placeholders, stale files, immutable action refs, non-publishing workflows, required files, version consistency).
- `scripts/stress_test.py`: **15/15 PASS** (XSS/YAML injection escaping, 5000-violation build, tamper detection, unicode/emoji, determinism, null/unknown fields).

## 3. 100x local concurrency torture (fresh run)
`scripts/concurrent_bench.py`, 100 workers x 200 mixed/oversize/corrupt requests:

| Metric | Value |
|---|---:|
| Status histogram | 134x200 / 33x413 / 33x422 |
| Unexpected 5xx / contract violations / transport errors | 0 / 0 / 0 |
| Throughput | 7.14 rps |
| P50 / P95 / P99 / max latency | 10500.2 / 20534.9 / 21525.0 / 21532.3 ms |
| RSS floor / ceiling / after-recycle | 41.7 / 292.9 / 198.5 MB |
| Recovery probes | /healthz 200, /api/bundle 200 -> fault_recovery PASS |

## 4. Live production black-box verification
Base: `https://access-doc.vercel.app`

| Probe | Result |
|---|---|
| GET /readyz | 200, commit c246f56 (zero drift) |
| POST /api/bundle malformed JSON | 400 in 156 ms |
| POST /api/bundle 11 MB oversize body | 413 in 181 ms |
| POST /api/bundle valid axe-sample.json (client/agency/date metadata) | 200 in 303 ms, application/zip, 7199 bytes |

All boundary and happy-path contracts hold exactly as documented in Turn 18.

## 5. Melious frontier gateway — live 4-model probe (production key, this session)
Direct calls to `https://api.melious.ai/v1/chat/completions` with the supplied bearer token:

| Model | HTTP | Latency |
|---|---:|---:|
| glm-5.3 | 200 | 0.67 s |
| glm-5.3-flash | 200 | 2.56 s |
| qwen3.8-27b | 200 | 2.73 s |
| kimi-k3 | 200 | 1.34 s |

All 4 models in the routing chain are confirmed live and healthy at the upstream. However, production `/readyz` still reports `"gateway":{"configured":false,...}` — the Vercel deployment does not have `MELIOUS_API_KEY` set as an environment variable, so the hosted gateway falls back to static remediation rather than calling these models. This is an **operator/infra action** (set the env var + redeploy), not a code defect; the repository-side breaker/failover/token-budget logic is exercised and green in the 760-test suite.

## 6. Council premortem status (re-validated, no regressions found)
1. Large-file memory exhaustion — bounded chunked reads, 2 MiB ceiling, RSS recycled 292.9 -> 198.5 MB. Mitigated.
2. Async worker deadlock — 200 req / 100 workers, 0 transport errors, 0 admission retries. Mitigated.
3. OCR/parse timeouts — out of current product scope (evidence-bundle tool, not OCR); malformed/oversize bodies fail fast (400/413/422). Pass for stated scope.
4. Frontier 429/5xx cascade — breaker/failover code covered by tests; live upstream healthy; production wiring still open (see §5).
5. Overclaiming — `verify_release.py` claims gate 10/10 PASS; this report keeps the same honest gateway caveat as Turn 13/18.

## 7. Remediation cycles used: 0/5
No source defects were found this turn. All 760 unit/integration tests, 15/15 adversarial checks, and fresh 100x/production/gateway probes passed without code changes. This is an evidence-only commit, consistent with the Turn 18 precedent.

## 8. Outstanding operator actions (unchanged from Turn 13/18, still open)
1. Rotate the GitHub PAT and Melious API key that were pasted into the task text — both must be treated as compromised regardless of this evidence.
2. Set `MELIOUS_API_KEY` on the Vercel production project so `/readyz` reports `configured:true` and live model routing activates end-to-end.
3. Add edge WAF/rate limiting and a spend kill switch in front of the Melious gateway before enabling it in production.
4. Wire the existing OTLP exporter to a real collector; complete named accessibility/security/legal sign-off; gather practitioner adoption evidence per `STATE.md`.

## 9. Launch verdict — September 17-18, 2026
**CODE: GO** (unchanged) — 100% green gates, zero regressions, live 4-model upstream confirmed healthy this session. **HOSTED GATEWAY: STILL BLOCKED ON OPERATOR ACTION** (env var not set) — identical honest caveat carried forward from Turn 13 and Turn 18. No new code defects were discovered, so no PR was required this turn beyond this evidence log.
