# Vercel deployment runbook — 0.4.0-beta.4

## Architecture

Vercel serves `public/` as static assets and invokes `api/bundle.py` for `POST /api/bundle`. The function creates a bounded ZIP in memory and returns it in the same request. It does not start `ThreadingHTTPServer`, create a token, or rely on cross-request memory. The existing `python -m app.main` local/container transport remains available.

## Before import

1. Push only the `repository/` directory as the GitHub repository root.
2. Run `python scripts/verify_release.py`.
3. Require the GitHub CI workflow to pass on the exact commit.
4. In Vercel, import the GitHub repository with framework preset **Other** and repository root `.`. Do not add a build command or output directory.
5. Keep the first preview protected and use sanitized evidence only.

## Configuration

- Python is pinned by `.python-version` to 3.13.
- Runtime dependency: `reportlab==5.0.0`.
- `vercel.json` sets the Python function maximum duration to 60 seconds and security headers.
- Optional `ACCESSDOC_ALLOWED_ORIGINS` is a comma-separated exact HTTPS origin allowlist. Same-host requests work without it.
- Do not store secrets in the repository, Gumloop prompt, or `vercel.json`.

## Preview smoke

Record the commit SHA, deployment ID, commit-specific URL, runtime, and timestamp. Check: `GET /`, `GET /sample/axe-sample.json`, valid `POST /api/bundle`, ZIP integrity using `python scripts/verify_bundle.py <zip>`, malformed JSON 400, oversized request 413, cross-site Origin 403, no-store headers, mobile/keyboard flow, no console errors, no private values in logs, and cold/warm generation below the configured duration.

## Production gate

Do not promote until protected-preview smoke, deployed security-header checks, privacy-log review, spend controls, distributed rate limiting or authentication, rollback target, ownership, security contact, name review, and independent accessibility/security review are complete. Local tests do not prove hosted behavior.

## Rollback / kill

Immediately disable generation or roll back for cross-request leakage, private evidence in logs, corrupt bundles, elevated 5xx/timeouts, abnormal spend, misleading claims, or a broken accessible companion.

Draft template - not legal advice - requires qualified counsel review before operative use.
