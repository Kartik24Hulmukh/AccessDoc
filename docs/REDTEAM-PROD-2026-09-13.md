# Production red-team receipt — 13 September 2026

Target: `https://access-doc.vercel.app` (serverless adapter), deployed commit `a934582ffd11443b3da3d3c6bfa1cd048928161d`, adapter `0.7.0-beta.5`.
Method: black-box, unauthenticated, from an external network. Every request timed; every response body inspected.

## 1. Surface and headers

| Probe | Result |
|---|---|
| `GET /`, `/health`, `/readyz` | 200 JSON, exact commit SHA exposed for drift detection |
| `GET /limits` | 200, machine-readable ceilings (2 MiB body, 10k violations, 100k nodes) |
| `GET /version`, `/metrics`, `/robots.txt`, `/.env`, path traversal | 404 JSON with `request_id`, no stack trace, no server banner |
| `PUT` / `DELETE` | 405 |
| `OPTIONS` with hostile `Origin` | 204, **no** `Access-Control-Allow-*` (browsers cannot call cross-origin) |
| Security headers | HSTS 2y+preload, `CSP default-src none; frame-ancestors none`, `X-Frame-Options DENY`, `nosniff`, `Referrer-Policy no-referrer`, `Cache-Control no-store` |

## 2. Hostile payload matrix against `POST /api/bundle`

| Case | Expected | Observed |
|---|---|---|
| valid axe JSON | 200 `application/zip` | 200, 10.5 KB ZIP in 70 ms |
| truncated JSON `{` | 400 | 400 `Malformed JSON` |
| JSON array body | 422 | 422 `Request body must be a JSON object` |
| no body / no `Content-Length` | 411 | 411 |
| `Content-Type: text/plain` | 415 | 415 |
| 3000-deep nested `[[[...` in `scanner_input` | reject, no stack overflow | 422 in 50 ms |
| 2.5 MiB body | 413 before parse | 413 in 240 ms |
| 300 violations x 200 nodes (60k nodes) | 413/422 | 413 `Request body too large` |
| `__proto__` key + `pdf_engine: "; rm -rf /"` | ignored | 200, keys dropped by pass-through whitelist |
| NUL bytes in `client_name` | no crash | 200 |
| `<script>alert(1)</script>"onmouseover="x` as client name, URL and description | escaped everywhere | `report.html` and `vpat-draft.html` escaped; **`eaa-evidence.md` NOT escaped** (see 4) |

## 3. Concurrency burst

24 simultaneous `POST /api/bundle` from one client: 24 x 200, p50 0.75 s, [redacted] 1.22 s, zero 5xx. Per-process admission (`MAX_CONCURRENT_REQUESTS=2`) is absorbed by Vercel fan-out; a provider/WAF quota is still required for a public launch (unchanged recommendation).

## 4. Defect found and fixed

**Markdown/HTML injection in `eaa-evidence.md`.** `app.eaa._md()` neutralised only `|`, `\` and newlines. Any renderer that treats Markdown as HTML-permissive (GitHub, Notion, GitLab, most procurement portals) would execute `<script>` or `<img onerror>` injected via the client name or scanned URL — a stored XSS carried inside a signed, tamper-evident bundle. Fix: HTML-entity-escape `& < >` and backslash-escape Markdown control characters; regression tests in `tests/test_eaa.py`.

Also fixed: OpenACR `Automated (axe-core axe-core)` wording; serverless `/api/generate` now returns an actionable hint pointing to `/api/bundle`.

## 5. Offline re-verification of the production artifact

`scripts/verify_bundle.py` on the ZIP returned by production: size PASS, schema 1.1, structure PASS (9 members), integrity PASS, content PASS, signature DEFERRED (cosign bundle not attached by the hosted demo).

## 6. What this receipt does not prove

No authenticated paths were exercised (production has `api_key_required=false`). No load beyond 24 concurrent. No screen-reader pass on the returned HTML. Legal/editorial approval remains a human gate (see `STATE.md`).
