# Launch Turn 17 - hosted UI + developer docs served in production (2026-09-15)

**Verdict:** the largest remaining launch gap was not code quality but *reachability*: the product had no human-facing surface in production.

## Finding

`vercel.json` routes `/(.*)` to `api/handler.py`. The handler only knew JSON routes, so on https://access-doc.vercel.app:

| Path | Before | After |
|---|---|---|
| `GET /` (browser) | 370-byte JSON readiness blob | `public/index.html` report builder (Accept negotiation, `Vary: Accept`) |
| `GET /` (curl / monitors / SDK) | JSON | JSON, unchanged - production-smoke and 741 existing tests untouched |
| `/static/app.js`, `/static/app.css`, `/static/report.css` | 404 | 200, correct MIME, `nosniff` |
| `/sample/axe-sample.json` | 404 | 200 |
| `/docs`, `/openapi.json` | 404 | 200 (new: curl recipes + OpenAPI 3.1) |
| `Permissions-Policy`, COOP, CORP | absent | present on every response |
| `X-Request-ID` on GET/HEAD | absent | present |

## Stress / premortem checks executed

- Traversal (`/static/<up>/api/handler.py`, `%2e%2e`, `/docs/<up>/VERSION`), unlisted files (`/.env`, `/public/index.html`, `/openapi.yaml`), directory paths, POST to static paths: all 404 JSON with `request_id`. The allowlist never joins user input into a filesystem path.
- 512 KiB read cap on static assets; assets live in the deployment bundle (`public/` is not in `.vercelignore`).
- Page CSP is `script-src 'self'` with no `unsafe-inline`; API JSON CSP remains `default-src 'none'`.
- OpenAPI `info.version` == `VERSION`; `max_http_body_bytes` const == 2,097,152 - a test fails if the limit contract drifts again.
- Claims policy: OpenAPI + docs page scanned for `100% compliant` / `legal defense` / `guarantee`; `verify_release.py` claims gate PASS.

## Evidence

- `python -W error::ResourceWarning -m unittest discover -s tests` -> **751 tests, OK (12 skipped)** (baseline 741).
- `scripts/verify_release.py` -> all gates PASS (secret_patterns, claims, placeholders, stale_files, immutable_action_refs, non_publishing_workflows, required_files, version_consistency).
- `scripts/version_lint.py`, `scripts/config_lint.py` -> OK.
- production-smoke workflow gains Check H (UI, assets, docs, OpenAPI, traversal, Permissions-Policy) on every deploy and daily.

## Still open for the 16-17 Sept window (operator actions, not code)

1. Revoke the `ghp_` token that was pasted into the task prompt; replace with a fine-grained PAT or GitHub App token.
2. Enable `ACCESSDOC_REQUIRE_AUTH=true` + Vercel WAF rate rule before paid amplification.
3. Point OTLP export at a collector and alert on `degraded-offline-kb` rate, 5xx, p95.
4. Five-practitioner assistive-technology session on the live report builder now that it is reachable.
