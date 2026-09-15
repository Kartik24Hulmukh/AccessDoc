# Launch turn 16 - production remediation blocker closed

**Window:** 2026-09-15 UTC, hard launch 16-17 Sep 2026.
**Baseline audited:** `main @ 357da6b`, 0 open PRs, production serving `357da6b`.

## Live production probe that changed the launch decision

| Probe | Before | After code change |
|---|---|---|
| `POST /api/bundle` (axe fixture) | `200`, 8,447-byte ZIP, 6 members, receipt schema 1.2 | unchanged |
| `POST /api/remediate` | **`503 GATEWAY_UNAVAILABLE`** - `MELIOUS_API_KEY is not configured for this deployment` | `200` deterministic offline WCAG plan, `X-AccessDoc-Mode: degraded-offline-kb` |
| `/readyz` | `gateway.configured: false` | unchanged (still needs an operator key for model-backed guidance) |

The previous turns recorded `gateway.configured=false` as an operator task.
Probing the actual product surface showed it was worse than that: the flagship
AI remediation endpoint answered **every** production request with a 503, so
100% of remediation traffic on launch day would have failed - a launch-day
churn and credibility event, not a config footnote. The repository already
contained a static knowledge base that was unreachable on this path.

## Fix

* `app/remediate.py`: `OFFLINE_RULES` (curated axe-core rule -> WCAG 2.2
  criterion + concrete fix + S/M/L effort + verification step), `offline_plan()`
  (impact-then-instance-count priority ordering) and `remediate_offline()`.
* `api/handler.py` and `app/main.py`: a missing credential or an exhausted
  chain now degrades to `200` with `degraded: true`, `model: offline-kb` and
  header `X-AccessDoc-Mode: degraded-offline-kb`, instead of a 503.
* `ACCESSDOC_STRICT_GATEWAY=1` restores the fail-closed 503 for operators whose
  policy requires it; both original 503 tests now pin that mode.
* New metric `accessdoc_gateway_remediate_offline_total` for alerting.
* Input validation is unchanged in every mode (`422` on empty/invalid input).

## Validation on this branch

| Gate | Result |
|---|---|
| `python3 -m unittest discover -s tests` | **741 tests, 0 failures, 0 errors**, 12 optional Playwright skips (baseline was 732; +9 new) |
| `scripts/verify_release.py` | **10/10 PASS** |
| Degraded-mode stress, 50 workers x 500 requests | `degraded_mode_stress.json`: 497x `200`, **zero 5xx**, p50 5.3 ms, determinism PASS (one guidance hash across 497 responses) |

The 3 non-200 results are `ConnectionResetError` from the local stdlib test
harness accept backlog, not application responses - the serverless platform
routs one request per instance. Recorded rather than hidden.

## Premortem re-run (launch day, 16-17 Sep 2026)

| # | Failure vector | Verdict |
|---|---|---|
| 1 | Key not installed in Vercel before launch | **Closed in code** - users get real, actionable guidance anyway; the key becomes an upgrade, not a dependency |
| 2 | Model provider outage mid-launch | **Closed** - chain -> static-KB -> offline plan, never a 5xx |
| 3 | Users mistake KB output for model output | **Closed** - `degraded`/`fallback` flags, `notice` string, response header, UI label |
| 4 | Operator wants fail-closed semantics | **Closed** - `ACCESSDOC_STRICT_GATEWAY=1`, tested |
| 5 | Silent degradation goes unnoticed | **Closed** - `accessdoc_gateway_remediate_offline_total` + `/readyz.gateway.configured` |

## Still owner-only (cannot be done from the repository)

1. Install a rotated `MELIOUS_API_KEY` in Vercel for model-backed guidance.
2. Rotate/revoke the credentials that were passed in plaintext task text.
3. Point `OTEL_EXPORTER_OTLP_ENDPOINT` at a real collector and alert on
   `failed_batches`, queue depth, error rate, spend, and the new offline counter.
4. Rollback rehearsal and named release/security/legal/accessibility sign-off.
