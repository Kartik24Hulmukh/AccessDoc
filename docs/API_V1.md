# API v1

`POST /api/v1/generate` (alias `/api/generate`) accepts `application/json` with `scanner_input` (raw axe-core JSON, required) plus optional `client_name`, `agency_name`, `audit_date`, `manual_findings`, `enrich`, `include_sarif`, `include_vpat`, `include_eaa`, `prior_receipt`. Success is `201` with a temporary download URL (`download_url`, `html_companion_url`, `receipt_url`), `finding_count`, `severity_counts`, `catalog_review_required`, `expires_in_seconds`, and the full `input_evidence_receipt`. Validation failures are `422`; cross-site requests `403`; unauthenticated requests are `401` when `ACCESSDOC_API_KEYS` is configured; rate limits `429`; capacity `503`. Every response carries `X-Request-ID`. CLI-only `pdf_engine` and `receipt_history` are not forwarded by HTTP. `detected_format` (axe) and `instance_count` are additive response fields.

`POST /api/bundle` accepts the same body and returns the complete tamper-evident ZIP (PDF, HTML, receipt, OpenACR YAML, in-toto attestation, and any opted-in SARIF/VPAT/EAA/trend exports) as `application/zip` directly, with no token/download step.

`GET /limits` returns the machine-readable ceiling values enforced on every input (`max_violations`, `max_total_nodes`, `max_string_chars`, ...) plus `api_key_required` and `rate_limit_per_minute`, so clients and operators can self-discover current bounds instead of guessing from 413/422 responses.

## Hosted abuse controls (optional, operator-configured)

By default `/api/generate`, `/api/v1/generate`, and `/api/bundle` require no authentication (suitable for local CLI use, CI, or a private/trusted deployment). For a public hosted deployment, set `ACCESSDOC_API_KEYS` to a comma-separated list of keys; every POST to a generation endpoint then requires a matching `X-API-Key` header or is rejected with `401 UNAUTHORIZED` before any parsing or capacity is consumed. Per-IP request-rate limiting (`RATE_LIMIT_PER_MINUTE`, default 30/min) and bounded concurrent generation (`MAX_CONCURRENT_REQUESTS`) apply regardless of whether API keys are configured.

Compatibility: additive response fields are allowed in v1; existing fields and meanings are not removed or changed without a new major API path. `/api/generate` is a compatibility alias during 0.x.

## Fixed 13 Sept 2026

Before this fix, `/api/generate` and `/api/v1/generate` referenced `Branding`/`AuditRequest`/`parse_input`/`generate_pdf`/`generate_html`, none of which exist in this codebase after the evidence-bundle refactor. Every call raised `NameError`, silently caught and returned as an opaque `500 GENERATION_FAILED` -- the documented core API was 100% non-functional. It now routes through the same `build_artifacts()` pipeline that powers the tested `/api/bundle` endpoint. See `tests/test_api_key_auth.py` and `tests/test_app_main_generate_endpoint.py` for regression coverage.

## Shared HTTP authentication

Both adapters support `ACCESSDOC_API_KEY` with `Authorization: Bearer <key>`.
This single-key mode takes precedence over legacy `ACCESSDOC_API_KEYS` /
`X-API-Key` if both are configured. `ACCESSDOC_REQUIRE_AUTH=true` without any
configured key fails closed with 503. The browser pilot-key field uses Bearer.
The Vercel adapter serves bundle/health endpoints, not self-hosted generate or
`/limits`. It has per-process concurrency admission, NOT the self-hosted IP
rate limiter or a distributed quota. Provider/WAF limits remain required.
