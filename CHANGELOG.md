# Changelog

## [0.7.0-beta.7] - 2026-09-16 - launch turn 8: health-ranked gateway routing + timeout-weighted breakers (release PR)

- **Live finding (Melious bench, 2026-09-16 14:27 UTC, production key):** GLM-5.3 P50 5.8 s / 3/3 OK; **GLM-5.3 Flash 0/3 OK - three consecutive 25 s read timeouts (HTTP 504) before its breaker opened**; Qwen 3.8 27B P50 10.8 s / 3/3 OK; Kimi K3 P50 20.5 s / 3/3 OK. With the canonical chain, one slow second-tier model could spend 25 s of the shared 40 s request budget ahead of a healthy 11 s model.
- `CircuitBreaker.record_timeout()`: a read timeout is one real failure counted with weight 2 toward the open threshold (a timeout burns a full 25-30 s window; a fast 5xx costs milliseconds). Raw `failures`/`timeouts` counters stay truthful - the weight only accelerates ejection (2 timeouts open a threshold-3 breaker). `snapshot()` now reports `timeouts`.
- `ModelGateway.route_order()`: health-ranked fallback order. Models whose breaker is not CLOSED or that carry unresolved consecutive failures are demoted behind healthy models; the sort is stable so canonical priority is preserved within each tier and routing stays deterministic. Demoted models are still tried last (breaker allowing), never dropped. Recovery is immediate on the next success. Emits a `gateway_route` JSON event whenever the order differs from canonical.
- Token-budget ceilings, immediate 429/5xx failover, per-model read windows clamped to the remaining wall-clock budget and the offline-KB last resort are unchanged.
- Production verification (black-box, this turn): `/readyz` reports exact `main` commit `4b6dcc1` (drift from turn 7 resolved); `/healthz`, `/limits`, `/docs`, `/openapi.json`, `/index.html` all 200; hostile inputs 415/400/413; `POST /api/bundle` -> 200 ZIP, 6 members, receipt 1.2, independent `verify_bundle.py` PASS; hosted burst 48 req / 16 workers -> 48x200, 0 errors, p50 77 ms, p95 905 ms (cold starts); `/api/remediate` serves the deterministic offline plan because `MELIOUS_API_KEY` is not configured on the host (operator gate).
- 6 new tests (tests/test_gateway_health_routing.py). Suite: 760 tests green; verify_release.py all gates PASS; 15/15 adversarial stress PASS.

## [0.7.0-beta.7] - 2026-09-16 - launch security: GitHub Action template-injection fix (release PR)

- **Confirmed vulnerability closed:** the composite action interpolated `${{ inputs.* }}` expressions directly into Bash source, so a hostile `client-name` could run arbitrary commands in consuming workflows (sentinel file created in a reproduced run). All inputs now pass through intermediate environment variables with quoted arrays; `output-dir` rejects CR/LF before any write to GitHub's line-oriented `$GITHUB_OUTPUT`; `actions/setup-python` pinned to commit SHA `42375524e23c412d93fb67b49958b491fce71c38` (v5.4.0).
- Gate semantics: severity-gate failures (exit 1) still publish evidence paths; build errors (exit 2+) no longer publish stale artifact paths from previous runs.
- `scripts/ci_gate.py`: atomic artifact writes and deterministic output-dir handling aligned with the action contract.
- Validation: full release verifier re-run on the fixed tree - 751 tests green, 15/15 adversarial stress checks PASS, end-to-end smoke PASS, all release gates PASS (compile, secret patterns, claims, placeholders, immutable action refs, version consistency).

## [0.7.0-beta.7] - 2026-09-15 - launch turn 17: hosted UI + developer docs actually served in production (PR #56)

- **Production gap closed:** `vercel.json` routes every path to `api/handler.py`, so the report builder in `public/` was never reachable on https://access-doc.vercel.app - `/` answered raw JSON to browsers and `/static/*`, `/sample/*` returned 404. The serverless adapter now serves the UI with browser content negotiation (`Accept: text/html` -> `public/index.html`; probes, curl and SDKs still get the JSON readiness document, `Vary: Accept`).
- Strict static allowlist (`/index.html`, `/static/app.css|app.js|report.css`, `/sample/axe-sample.json`, `/docs`, `/openapi.json`): no path joins from user input, 512 KiB read cap, page-scoped CSP (`script-src 'self'`, no `unsafe-inline`), traversal / unlisted paths stay 404 JSON with `request_id`.
- Developer DX: new `GET /docs` (curl recipes, error contract, offline verification, honest scope) and `GET /openapi.json` (OpenAPI 3.1, `info.version` pinned to VERSION, `max_http_body_bytes` pinned to 2,097,152). `/readyz` and `GET /api/bundle` advertise them.
- Headers: `Permissions-Policy`, `Cross-Origin-Opener-Policy: same-origin`, `Cross-Origin-Resource-Policy: same-origin` on every serverless response; `X-Request-ID` now present on GET/HEAD as well as POST for support triage.
- UI copy: result panel names all six ZIP members and labels `report.html` as the accessible primary and `report.pdf` as the untagged convenience copy; footer links to `/docs`.
- production-smoke: asserts the hosted UI, static assets, `/docs` and `/openapi.json` on every deploy and daily.
- **Follow-up (PR #57):** the first production deploy proved Vercel strips `public/` from the Python function bundle (assets 404 while headers deployed). Allowlisted assets are now embedded as base64 + SHA-256 in generated `api/public_assets.py` (`scripts/embed_public_assets.py`, `--check` mode); the handler prefers disk and falls back to the embedded copy. A test fails if the module drifts from `public/`.
- 13 new tests (tests/test_hosted_surface.py). Suite: 754 tests green; verify_release.py all gates PASS.

## [0.7.0-beta.7] - 2026-09-15 - launch cut: listen-backlog fix, pypdf security bump, test hygiene (PR #45)

- Server: default kernel listen backlog raised 128 -> 512 (LISTEN_BACKLOG, clamped to a 128 floor). Root cause from the 100-worker torture runs: the 128-entry accept queue overflowed under burst and the kernel answered with RST before the server accepted the connection. 512 removed every reset; no deploy-env change is required any more.
- Dependencies: pypdf 6.17.0 -> 6.18.1 (dev/test verifier) picks up upstream parser hardening (FlateDecode recovery limits, font /Widths entry caps, bfchar token length caps) for corrupted-PDF inputs.
- Tests: file-handle leaks in tests/test_remediate_endpoint.py closed (clean under -W error::ResourceWarning); scripts/concurrent_bench.py now exercises the shipped backlog default. 3 new tests (tests/test_listen_backlog.py). Suite: 692 tests green.
- Release: version aligned to 0.7.0-beta.7 across VERSION, pyproject, SBOM, adapters, smoke workflow and launch docs.

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
