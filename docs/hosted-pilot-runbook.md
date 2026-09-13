# Hosted pilot boundary and launch gates

## Scope

This increment fixes the self-hosted `/api/generate` and `/api/v1/generate`
routes (they referenced removed parser/model/renderer symbols and returned 500).
They now share the evidence pipeline, return 201 plus expiring capability URLs,
and preserve the schema-1.2 receipt. The bundle API remains stateless.

Both HTTP adapters now reject CLI-only rendering/history options by allowlisting,
ignore the local oversized-input opt-out, and support an optional shared pilot
Bearer credential. The serverless adapter has **per-process**, nonblocking render
admission (default 2); overload returns 503 with Retry-After. Self-hosted already
had admission controls and an IP limiter. Neither is a distributed tenant quota.
Rejected POSTs close the connection so unread bodies cannot become new requests.
Duplicate Content-Length and unsupported transfer/content encodings are rejected.
Malformed Unicode/deep JSON are client errors, not 500s. Report storage permits
exact configured capacity; oversized items cannot evict an existing report.

## Authenticated pilot (operator action required)

1. Set `ACCESSDOC_REQUIRE_AUTH=true` and a random `ACCESSDOC_API_KEY` in the
   hosting secrets manager. Never put an API key in git, a URL, shell history,
   screenshots, or client source. Rotate on compromise. Use HTTPS.
2. No configured key + require-auth => 503 (fail closed). Configured key =>
   missing/wrong/duplicate Authorization is 401 even if require-auth is false.
3. POST using `Authorization: Bearer <pilot key>`. The self-hosted page has an
   optional password field kept in page memory only. This is one shared pilot
   credential: no per-tenant accounting, identity, revocation or billing.
4. Default remains unauthenticated for backwards-compatible local/demo use.
   **Deploying this commit alone does not enable production authentication.**
5. Configure provider/WAF request limits, max instances, CPU/memory ceilings,
   hard invocation timeout and spend alerts before public promotion. In-process
   semaphores do not bound total serverless replicas; thread timeouts do not kill
   CPU-bound render jobs. Place self-hosting behind a hardened reverse proxy.
6. Health stays public. Self-hosted download URLs are short-lived capabilities;
   treat them as secrets, avoid analytics/query logging, and use tenant-bound
   private storage if operating a multi-user service. AccessDoc now redacts these
   tokens from its own request logs, but proxy logs require operator redaction.

## Reproduce checks

```text
pip install -r requirements-dev.txt
python -W error::ResourceWarning -m unittest discover -s tests -v
python scripts/hardening_load.py --output hardening-load.json
python scripts/hosted_soak.py --seconds 60 --workers 8 --output hosted-soak.json
```

`hosted_soak.py` has no remote target option: it only creates loopback servers.
It sends authenticated requests with 100 finding instances, validates every
successful ZIP, measures successful p50/p95/p99 separately from expected 503s,
samples local RSS/CPU, and verifies recovery. This is a short closed-loop local
exercise, **not sustained staging, 100x throughput, or capacity certification**.
The older hardening script explicitly allocates 8 local render slots to measure
its 8-worker determinism/contract gate, not production-default overload behavior.

## Premortem and stop-ship criteria

| Failure | Control now | Remaining release gate |
|---|---|---|
| Runaway cost from public calls | Optional shared auth; local admission | Enable auth; global quotas/WAF; max instances; spend-alert drill |
| Big but valid input monopolizes CPU | Input bounds and admission | Process/provider hard deadline, bounded jobs, cancellation proof |
| Source capability leaks to logs | App download route redaction | Verify proxy/CDN logs and retention |
| Works on Vercel, fails in container | Real-socket tests for both adapters | Staging deployment on chosen platform, exact-SHA verification |
| Renderer advertised features are ignored | UI only offers axe JSON; unsupported color/logo disabled | Product review; no PDF/UA claim; real screen-reader review |
| Resource exhaustion/restart | Local rejection and recovery tests | Multi-hour staging soak with CPU/RSS/error curves and alerts |
| Bad deployment | Health SHA | Demonstrate rollback to immutable last-good image in <5 minutes |
| Evidence mistaken for compliance | Existing limitations and semantic HTML | Qualified review, independent validator/signing run evidence |
| Nobody needs generated handoff | Narrow evidence-to-handoff workflow | Five practitioner trials, 4/5 unassisted generation; 3/5 edit in 30 min |

## Release decision

Do not market as production-ready SaaS yet. Prefer an invite-only, authenticated
pilot or local/CLI beta while the above gates are completed. A September launch
is a target, not proof of readiness. No claim of legal certification, PDF/UA,
market traction, or 100x capacity follows from automated unit tests.

Serverless logs now emit a generated request ID, status and duration for POSTs;
the same ID appears in the response header. Payloads and Authorization are never
logged. A managed log sink, alert ownership, incident drill and rollback remain
operator tasks; they have not been provisioned by these code changes.

## Concurrent main integration (PR #35)

PR #35 was merged by another actor during this work. Its `/limits` endpoint,
API documentation and 11 regression tests are preserved. Legacy
`ACCESSDOC_API_KEYS` (comma-separated) with `X-API-Key` remains supported and is
now enforced by both adapters. If `ACCESSDOC_API_KEY` is also set, the single
Bearer key takes precedence; the legacy header cannot bypass it. The browser
pilot field uses Bearer auth, so configure the single-key mode for that UI.
Missing credentials with REQUIRE_AUTH always fail closed. No existing auth
configuration is silently removed. Final integration needs fresh CI.
