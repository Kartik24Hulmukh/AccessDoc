# AccessDoc turn 5 — read-only council red-team audit

**Audited checkout:** `/data/AccessDoc`, HEAD `78736f2`.
**Disposition:** three reproducible findings below. No fixes or deployments performed. These synthetic local observations do not clear any human-validation, tenant-isolation, provider, deployed, or launch gate. Existing holds remain in force.

## Scope and execution safeguards

Inspected `app/main.py`, `app/store.py`, `api/handler.py`, shared HTTP policy/parser/resource bounds, public privacy/API documentation, and focused public test excerpts. Did not investigate the lead's broad store-import fallback; none of these findings requires import failure.

Reproductions used `/data/accessdoc-venv/bin/python`, the real artifact builder, real `TTLReportStore`, actual self-hosted `Server`/`Handler`, and the hosted handler under a local stdlib HTTP server. No artifact/store mocks or source edits. A clean environment excluded inherited provider/auth/exporter configuration; a Python audit hook rejected non-loopback socket binds/connects. All test credentials and evidence were synthetic. No provider requests, deployment, credential-helper/private/tool-result file reads, or real human evidence were used. Python bytecode writes were disabled. All harnesses/evidence/output are outside the repo.

Reproduce all three:

```sh
env -i PATH=/usr/bin:/bin HOME=/data PYTHONDONTWRITEBYTECODE=1 \
  /data/accessdoc-venv/bin/python /data/accessdoc-turn5-repro.py \
  > /data/accessdoc-turn5-repro.log 2>&1
```

Structured evidence: `/data/accessdoc-turn5-results.json`. The harness closes both local servers and their serving threads. Each rerun overwrites the synthetic evidence/log; timestamps and request IDs will differ.

## 1. P1 — Real generation succeeds, but an undocumented 100 KB receipt storage cap rejects valid input as INVALID_INPUT

**Exact locations:** `app/store.py:32–34`, especially receipt size check at line 33; `app/main.py:264–278` builds artifacts before calling `STORE.put`; `app/main.py:285` converts its `ValueError` to generic HTTP 422. Public input ceilings are in `app/limits.py:19–24`.

**Actual reproduction:** one `color-contrast` violation with 500 distinct synthetic node selectors; short description; ordinary provenance metadata. Entire JSON request: **16,137 bytes**, well below 2 MiB and the 5,000-node-per-violation limit. No manual/human findings supplied.

- Real outputs: PDF **28,652 bytes**, HTML **240,473 bytes**, receipt **115,061 bytes**.
- Direct real-store insertion raises `ValueError: Generated output exceeds storage limit` because receipt >100,000 bytes, despite being far below the aggregate 50 MB budget.
- Authenticated `POST /api/generate` returns **422**, `INVALID_INPUT`, `Invalid input`.
- Store is still `{items: 0, bytes: 0}`: no report was stored.
- Identical authenticated `POST /api/bundle` returns **200**, a **56,989-byte ZIP**.
- A one-node control generates/stores successfully with **201**.

**Impact:** a modest, parser-valid scan cannot use the documented generate/download workflow. The response blames input validity and hides the actual output-storage failure after rendering costs have already been incurred. Success with a mocked artifact, a tiny receipt, or only the bundle endpoint cannot establish real report-storage success. The inspected store tests (`tests/test_hosted_boundary.py:147–159`) use three-byte artifacts; this audit does **not** claim a particular mock test falsely asserted this failing case succeeded.

**Action:** define a consistent, bounded output-budget contract; reject predictable expansion before expensive rendering where feasible. Separate storage/output-limit failures from malformed-input errors and expose an actionable safe code. Support realistic receipts within an explicit bounded budget or clearly declare the output ceiling and direct users to the supported bundle path. Add a non-mocked HTTP regression using this 500-instance payload, checking storage and downloads—not just renderer or bundle success. Do not simply remove the cap.

## 2. P1 — TTL expires download access, but does not enforce the stated memory-retention deadline during idle periods

**Exact locations:** `app/store.py:25–28` implements expiry; it is invoked only by `put` (`35–37`), `get` (`38–41`), or `stats` (`43–45`). No store-owned scheduled cleanup exists. `docs/PRIVACY.md:7` states default retention is 30 minutes in process memory.

**Actual reproduction:** construct the real store with `ttl_seconds=1`; insert a 44-byte synthetic PDF/HTML/receipt tuple; sleep **2.2 seconds** without calling `get`/`stats`/`put`. Inspect the backing mapping directly to avoid triggering cleanup.

- At age **2.2 seconds**, the entry is still in `_items`, `_bytes` is **44**, and synthetic PDF bytes remain reachable.
- Only the subsequent `get(token)` removes it, returns `None`, and drops `_bytes` to **0**.

**Impact:** an idle process can retain expired report payloads for as long as no store-touching operation occurs, rather than deleting logical references at TTL. `/healthz` and `/readyz` do not touch the store; incidental `/metrics` polling is not a guaranteed retention mechanism. This matters for private URLs/selectors and other sensitive content in generated artifacts. This is **not** evidence of downloading an expired report, unbounded store growth, or secure-erasure guarantees; the existing 50 MB/item ceilings still bound the retained store.

**Action:** implement a bounded, lifecycle-managed expiry sweep independent of user traffic, with explicit maximum expiry lag and shutdown cleanup, or change the privacy promise to accurately disclose lazy retention and provide an enforced deletion mechanism before sensitive deployment. Test idle expiry without invoking `stats`/`get` before asserting backing references have been removed. Do not confuse token inaccessibility with retention enforcement.

## 3. P2 — Both readiness endpoints are green when mandatory auth is unconfigured and every core POST is unavailable

**Exact locations:** `app/main.py:205` bases readiness solely on `READY`; `api/handler.py:485–489` unconditionally returns 200/`ok` for readiness. `app/http_policy.py:25–30` returns 503 `AUTH_NOT_CONFIGURED` when `ACCESSDOC_REQUIRE_AUTH=true` and both single/legacy key settings are absent. Hosted enforcement is `api/handler.py:577–581`; self-hosted enforcement is `app/main.py:239–241`.

**Actual reproduction:** in the clean synthetic environment set `ACCESSDOC_REQUIRE_AUTH=true`, with neither `ACCESSDOC_API_KEY` nor `ACCESSDOC_API_KEYS` configured. Supply the same valid one-node body that previously generated successfully.

| Adapter | `GET /readyz` | `POST /api/bundle` |
| --- | --- | --- |
| Actual local threaded adapter | **200**, `status: ready` | **503**, `AUTH_NOT_CONFIGURED` |
| Hosted handler on loopback | **200**, `status: ok` | **503**, `AUTH_NOT_CONFIGURED` |

**Impact:** routing/deployment automation can treat a non-serving core instance as ready. The condition is a hard configuration failure, not optional gateway degradation or an unprobed provider. No provider probe is needed to detect it. This reproduction is independent of the store fallback.

**Action:** make readiness fail with 503 and a non-secret reason for locally knowable mandatory configuration failures. Keep liveness independent and preserve existing optional-AI degradation policy. Add adapter-parity tests for required-auth-with-no-key, valid configured auth, and intentionally unauthenticated demo mode; never return credentials in readiness.

## Download, validation, and resource checks — bounded conclusions, not additional findings

- Known-token controls: after authenticated small-report generation, all three token URLs (PDF, HTML, receipt) return **200 without Authorization**. Exact path: `app/main.py:216–223`; the store has no owner/tenant field (`app/store.py:7–13`). Tokens are bearer capabilities, not tenant-bound authorization. `app/http_policy.py:1–5` explicitly describes a shared pilot credential, so this audit does not invent a multi-tenant contract or claim token guessing. This observation cannot clear a tenant-security gate; any sensitive/multi-tenant rollout still needs an explicit approved sharing/access model.
- `GET /static/../../app/main.py` returned **404**. The inspected self-hosted path uses resolved-public-root containment (`app/main.py:226–228`), and the hosted adapter uses an explicit asset allowlist (`api/handler.py:157–172`). No concrete repository-file traversal was established by the exercised request.
- Invalid scanner input containing a synthetic private-marker key returned **422**, a generic `INVALID_INPUT` response, with no marker reflected. This is one concrete control, not exhaustive proof of leak-freedom.
- Response bytes can arrive before the request thread's `finally` runs. The harness waited on `ACTIVE_CONDITION` for up to two seconds; generation accounting returned to zero. The exercised storage/validation failures did not establish an admission-slot leak. No unbounded load, broad RSS stress test, or external quota claim was made.
- The retention issue is the concrete remaining memory/cleanup failure established here; broader output amplification was not stress-tested and is not added as a fourth finding.

## Gate handoff

Remain **HOLD** for relevant unresolved report-storage, retention, readiness, and separately evaluated tenant/deployed/human requirements. Synthetic scans and an empty manual-findings field are not real human validation, real-user acceptance, production evidence, or certification. No holds were edited or released. The lead's import-fallback investigation remains separate.
