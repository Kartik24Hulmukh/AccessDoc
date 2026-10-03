# Vercel deployment and authenticated pilot runbook

## Actual architecture

`vercel.json` uses the legacy `@vercel/python` build for `api/handler.py` and routes every path to that handler. The handler serves the report UI and embedded static assets, JSON health, and the bounded bundle endpoint. `POST /api/bundle` returns a ZIP directly in the request; this hosted adapter does not provide server-held capability downloads. The separate local/container transport (`python -m app.main`) uses process-local, expiring capability downloads that are neither durable nor tenant-bound. Do not apply its report-retention behavior to the Vercel adapter; provider and browser/log retention require their own review.

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

## Independent operation shutdown and telemetry controls

Both adapters accept `ACCESSDOC_GENERATION_ENABLED` and
`ACCESSDOC_REMEDIATION_ENABLED`, each defaulting to `true`. Only `true` and `false`
(case-insensitive, surrounding whitespace ignored) are accepted. A missing
variable preserves the default; an empty or invalid value disables that operation
and adds a fixed configuration error to readiness. No raw environment value is
published. Provision environment changes through the hosting control plane and
activate them by restart/redeployment; this is not a remotely mutable API.

Authenticated disabled POSTs return 503 and `Retry-After: 30` **before reading the
body or acquiring a pipeline permit**. Authentication remains enforced first.
Generation and remediation can be disabled separately. Disabling generation
makes `/readyz` fail; intentionally disabling optional remediation does not.
`/healthz` stays live, and HEAD uses the same readiness status as GET. These gates
refuse new work, not already accepted work. The remediation gate disables both
paid and offline guidance; it is not a provider monetary ceiling. Preserve
account/WAF limits and a separate provider-side kill procedure.

Hosted request completion now emits one structured `http_request` log and one
SERVER-kind span for GET, HEAD, POST, OPTIONS and rejected requests. Response
`X-Request-ID` and `traceparent` correlate ZIPs and errors as well as JSON/static
responses. Route labels use a finite vocabulary; arbitrary paths, query strings,
capability tokens and client addresses are omitted. Do not infer that proxy/CDN
logs have the same redaction.

The bounded OTLP exporter uses the existing native transport, a single sender,
and shared absolute export/flush/shutdown budgets. HTTP 200 JSON acknowledgements
are required; partial rejection is not success and is not retried. Readiness
exposes cumulative exported/rejected/failed/dropped counters and fixed error codes,
never collector response text. An empty later flush is not recovery of earlier
losses. Collector work shares process-wide native admission with model requests;
collector saturation may consume a slot, so validate this interaction in staging.
Expired shutdown returns failure while owned native cleanup remains scheduled;
no extra blocking grace is added. Local collector proofs do not establish a
working central collector, retention policy or delivered alert.
