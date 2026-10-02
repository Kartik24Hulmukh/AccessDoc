# Vercel deployment and authenticated pilot runbook

## Actual architecture

`vercel.json` uses the legacy `@vercel/python` build for `api/handler.py` and routes every path to that handler. The handler serves the report UI and embedded static assets, JSON health, and the bounded bundle endpoint. `POST /api/bundle` returns a ZIP in the request; generated capability downloads use process-local ephemeral storage and are not durable or tenant-bound. Local/container transport is `python -m app.main`.

Python is selected by `.python-version`. Runtime dependencies come from `requirements.txt`; the optional model transport uses pooled aiohttp and c-ares DNS. CI records dependency/security evidence. Neither this file nor a green CI job establishes provider limits.

**No function duration or memory ceiling is declared in the current `vercel.json`.** Earlier documentation claimed a 60-second setting that was absent. Do not infer fleet quotas from the default two per-process generation slots. Obtain the actual project/plan settings and test hard termination in protected staging before promotion. Do not mix unsupported modern function settings into the legacy builder without deployment validation.

## Protected pilot setup

1. Preserve Vercel deployment protection. A GitHub personal access token does not authorize Vercel project changes.
2. An authorized Vercel project operator provisions the project-scoped automation bypass through Vercel's supported automation-access mechanism, not browser cookies or disabled SSO.
3. In the hosting secret manager, enable `ACCESSDOC_REQUIRE_AUTH=true` and a fresh random `ACCESSDOC_API_KEY`. This is a shared invite-only pilot credential, not tenant identity or billing. A missing required key fails readiness closed.
4. In GitHub environment `accessdoc-pilot-verification`, provision `VERCEL_AUTOMATION_BYPASS_SECRET` and `ACCESSDOC_PILOT_API_KEY` (the latter must match the deployed application's key). Never put either value into a dispatch input, URL, issue, artifact, or source file.
5. The environment requires repository-owner review, forbids admin bypass, and allows only `main` and `harden/accessdoc-v1-launch`. The sole current repository collaborator can approve their own initiated verification job; this is operator authorization, **not independent security or release approval**. Add independent reviewers before claiming separation of duties.
6. Review the checked-out smoke code and exact commit-specific target before approving a secret-bearing job. Do not approve arbitrary forks or contributor-controlled verifier changes.

## Exact-target verification

Dispatch `production-smoke` on the reviewed candidate ref with its commit-specific AccessDoc preview origin and expected adapter version. The job compares the full deployed commit against the checked-out workflow commit before and after functional checks. It does not promote a deployment or merge a PR.

The smoke runner separates platform bypass from application Bearer auth, keeps app credentials off health/static GETs, rejects missing/wrong app auth while retaining platform bypass, verifies readiness and ZIP/receipt/error/UI contracts, and archives a redacted result. Credentials are sent only to verified AccessDoc project origins; loopback HTTP is allowed for synthetic tests. Cross-origin redirects are rejected and SSO redirects fail as authorization errors, not successful application checks.

A daily/main-ref smoke detects drift relative to that ref. An intentional rollback to an older commit will fail this comparison; do not mark it green by weakening full-SHA matching. Verify the rollback using the explicitly reviewed rollback ref/commit-specific URL and record both identities.

## Operator evidence still required

Record project/deployment ID, exact URL/SHA, timestamp, and actual settings (not desired values):

- Hard invocation duration, memory/CPU limits, edge body/connection limits, replica/fleet quotas or equivalent provider controls.
- Authentication enforcement, allowed origins, proxy/CDN log redaction, retention/access controls and capability secrecy.
- Provider monetary ceiling, alert recipients, disable/kill procedure and a spend-alert drill. Per-request token authorization is not an account spend cap.
- Collector receipt, error/latency/overload/export-drop alert delivery and a named incident owner. Local stdout/tracing tests do not prove central collection.
- Sustained staging resource/load evidence under approved costs; synthetic personas are not real users or measured production capacity.
- Immutable previous-good deployment/image, authorized rollback rehearsal and measured recovery below five minutes; verify restored health, output, auth, and observability.

See `docs/PILOT_TRIAL_OPERATIONS.md`, `docs/EVALUATION_PROTOCOL.md`, `docs/RELEASE_GATES.md`, and `docs/hosted-pilot-runbook.md` for genuine participant and human approval gates. Remain an experimental beta; do not promote a public upload service before these gates pass.
