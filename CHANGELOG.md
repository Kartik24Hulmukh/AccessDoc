# Changelog

## [0.7.0-beta.6] - 2026-09-15 - launch-critical hardening: token budgets, W3C tracing, chunked I/O (PR #43)

- Gateway: cumulative per-request token budget (GATEWAY_TOKEN_BUDGET, default 6000) across the whole fallback chain; per-call max_tokens is clipped to the remaining budget and an exhausted budget routes to the deterministic static-KB instead of burning more frontier tokens. Exposed in the /readyz gateway snapshot.
- Observability: new app/telemetry.py - W3C traceparent adoption/minting on the hosted and serverless adapters, traceparent echoed on every response and propagated to Melious; OpenTelemetry tracer used automatically when opentelemetry-api is installed, zero-dependency fallback otherwise; every log line (http_request, gateway_call, gateway_skip, span) is a single JSON object with level/trace_id/span_id.
- Ingestion: request bodies are read in bounded 64 KiB chunks on both adapters (no single oversized allocation, early abort on client disconnect).
- 11 new tests (tests/test_launch_hardening.py). Suite: 687 tests green.

## [0.7.0-beta.6] - 2026-09-15 - serverless remediation parity + launch hardening (PR #41, PR #42)

- POST /api/remediate is now served by the Vercel serverless adapter (api/handler.py) with the same contract as the self-hosted server: bounded body, JSON-only errors, X-Request-ID, security headers.
- Dedicated MAX_CONCURRENT_REMEDIATIONS admission pool with a bounded REMEDIATION_QUEUE_TIMEOUT_SECONDS queue so slow model round-trips never starve or shed PDF/evidence generation.
- GET /, /readyz, /healthz expose a gateway/circuit-breaker snapshot and the endpoint list; GET /api/remediate returns a usage descriptor.
- Missing MELIOUS_API_KEY returns 503 GATEWAY_UNAVAILABLE + Retry-After, never a 500, and never affects /api/bundle.
- UI: "Get AI remediation plan" button in the report result panel; fallback:true responses are labelled as static-knowledge-base guidance and all plans are labelled advisory.
- 13 new tests (tests/test_serverless_remediate.py). Suite: 676 tests green.
- Vercel function maxDuration raised to 60 s (worst observed remediation wall under 2.5x load is 21.3 s; the platform must never cut off the bounded queue). vercel.json migrated from legacy builds to the functions block.
- Version metadata aligned across VERSION, pyproject, SBOM, adapters, README, launch copy and the production-smoke workflow; dated engineering receipts are now excluded from version-lint so history is never rewritten.


## 0.4.0-beta.4 — Vercel source candidate

- Added a stateless Vercel Python handler at `api/bundle.py`.
- Added one-request ZIP delivery with PDF, standalone semantic HTML, receipt, and integrity manifest.
- Added Vercel configuration, Python pin, no-store controls, serverless tests, cold-start and concurrency checks, and deployment/Gumloop runbooks.
- Preserved local/container mode and the legacy token API for compatibility.


## [Unreleased]

### Security
- `eaa-evidence.md`: user-controlled fields (client name, target URL, rule ids, sources) are now HTML-entity-escaped (`& < >`) and Markdown-escaped (`` ` * _ [ ] # ~ ``) in addition to the existing `|`/newline neutralisation. Previously a hostile `client_name` such as `<script>...</script>` was written verbatim into the Markdown pack, which most renderers (GitHub, Notion, procurement portals) pass through as live HTML. Found by live red-team of the production `/api/bundle` endpoint on 13 Sept 2026; `report.html` and `vpat-draft.html` were already escaped.

### Fixed
- OpenACR `evaluation_methods_used` no longer reads `Automated (axe-core axe-core)` when the scanner input carries no engine version; it now reads `Automated (axe-core version unknown)`.
- Serverless adapter: `POST`/`GET` on `/api/generate` and `/api/v1/generate` return a 404 whose JSON `error` tells the caller to use `/api/bundle` (the token/download flow only exists on the self-hosted adapter). Previously a bare `Not found` sent integrators following `docs/API_V1.md` down a dead end.

### Verified
- Live production red-team receipt: `docs/REDTEAM-PROD-2026-09-13.md` (hostile payload matrix, header audit, 24-way concurrency burst, bundle integrity re-verified offline).

### Fixed
- Both hosted adapters now route stdlib `send_error` (400/414/431/501 parse rejections) through the JSON error contract: security headers, `X-Request-ID`, no HTML, no reflection of the client request line, no Python/BaseHTTP server banner. Self-hosted request logs record the real status instead of 500 for these rejections.
- Serverless adapter exposes `GET /limits` (parity with self-hosted) including `api_key_required` and `max_concurrent_requests_per_process`.

## [0.4.0] - 2026-07-21

### Added
- Cryptographic evidence receipt in API, UI and PDF.
- Evidence-first launch overlay, 10-project base rate, competitor matrix, practitioner protocol, 20 direct outreach drafts, persona simulation and kill rules.
- War Room Gumloop prompts, claims/privacy/operator notes and issue templates.
- Mechanical banned-word, placeholder, stale-file and immutable-Action gates.

### Changed
- Public framing from assessment to accessibility evidence report.
- PDF/UA limitation moved beside download.
- Browser evidence paths made repository-relative.
- Workflow Actions pinned to immutable commits.

### Fixed
- Removed stale release evidence and cache files from the release candidate.
- Aligned runtime, package and evidence versions.

## [0.3.0] - 2026-07-19

- Open-source beta baseline with deterministic mappings, bounded memory lifecycle and community files.
