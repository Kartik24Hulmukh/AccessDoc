# Zero-spend pilot boundaries

## Decision and supported scope

Paid hosting and model/API spending are not approved. The current safe route is
supervised local deterministic generation, supplied-evidence GitHub Action
preparation and local stdio MCP evaluation using existing resources. This is
not production approval and does not establish customers, adoption or traction.
Keep required checks, named operator/human reviews and exact-target acceptance
separate. A free preview is not a substitute for those gates.

AccessDoc already includes a local `scan` CLI with optional Playwright/axe.
Do not expose it as an unrestricted public URL-scanning service. Automated
findings are partial; checksums/attestations establish generated-byte integrity,
not authenticated scan occurrence, completeness, compliance or legal clearance.

## Local evaluation without paid model calls

Use sanitized synthetic evidence and existing fixture/CLI/Action examples.
No upstream provider credential is needed for deterministic bundle generation.
Do not enable a provider, analytics SaaS, paid runner, domain, paid database or
billing account merely because a third-party research file calls it free.
Direct CLI/MCP/custom gateway calls are not controlled by HTTP admission flags;
exclude provider credentials from these local evaluation environments too.

The existing HTTP controls, configured privately before startup, are:

```text
ACCESSDOC_REQUIRE_AUTH=true
ACCESSDOC_GENERATION_ENABLED=true
ACCESSDOC_REMEDIATION_ENABLED=false
```

Supply a fresh private `ACCESSDOC_API_KEY` through a secrets manager or the
provider's secure input; never in Git, this file or chat. Required auth without
a key fails closed. The single-key mode expects `Authorization: Bearer ...`,
not the legacy `X-API-Key` mode. It is shared pilot authentication, not tenant
isolation. Remediation-off rejects new HTTP remediation (including offline
remediation); it does not cancel accepted jobs or cap a whole fleet/account.
Generation can remain ready with optional remediation off and valid auth.

Do not set invented knobs such as `ACCESSDOC_GATEWAY_DISABLED` or assume a
per-request token ceiling or billing cooldown is a daily/monthly dollar cap.
No live-model success is implied by an implemented route or readiness HTTP 200.

## Prospective Render example — not a deployed service

`render.yaml` now explicitly selects service compute `plan: free`, keeps
`autoDeploy: false`, requires operator-supplied hosts/origins and a private
pilot key, and disables new HTTP remediation. This is configuration preparation
only: no account/service was created, migrated or tested by this file.

Before even a protected synthetic preview, verify all of these:

1. Actual workspace/platform plan is $0, no payment method or paid add-ons,
   no automatic upgrade, and current exhaustion behavior cannot create charges
   within the approved experiment. A free compute field alone proves none of
   those account facts. Stop if no-charge entitlement is not established.
2. Intended use/data is allowed by current provider terms. Do not route
   commercial work through Vercel Hobby; labelling it a demo does not exempt an
   actually commercial workflow.
3. Exact-source required checks and independent review pass. Fill public hosts,
   origins and private auth before exposing the service; no wildcard bypass.
4. Fixed non-sensitive request/time/resource bounds and an owner stop procedure
   are agreed. Verify auth rejection, useful generation, disabled remediation,
   cold start, restart/download expiry, usage exhaustion and rollback on that
   target. No customer evidence or provider traffic in this experiment.

Render says free services are not for production, idle after 15 minutes and can
take about a minute to restart. Files are ephemeral; quota exhaustion can
suspend service/builds. With a payment method, bandwidth/build overages can be
billed. Do not evade sleep with artificial keep-alive traffic or call a warm
probe a cold-start SLA. Koyeb likewise documents one 512 MB / 0.1 vCPU free instance
and warns against production use. Neither is an accepted production route here.

Cloud Run's free allowance can be exceeded and billed.
A budget alert is not a spending cap.
Do not enable its billing or a $1 alert under a $0 authorization.

## Retention and output boundaries

Docker/local `/api/bundle` returns a ZIP directly. `/api/generate` also retains
capability-addressed PDF/HTML/receipt reports in process-local storage: default
TTL 30 minutes, 100 items, 50,000,000 combined bytes. Possession of the capability
URL authorizes downloads; it is not tenant isolation. Restart, eviction, sleep
or another replica can invalidate links. State these limits rather than calling
the whole container stateless. Browser downloads, logs, proxies and optional
collectors are separate retention domains; TTL is not secure erasure.

The PDF is an untagged convenience copy, not PDF/UA certification; VPAT and
other claims-sensitive outputs remain drafts requiring practitioner review.
Do not publish real evidence in public CI logs/artifacts or call synthetic
persona trials real practitioner acceptance.

## Finite release gate

No main merge or production promotion follows from this document or a free
plan. Required macOS and useful-export checks remain required. A research
recommendation for a 72-hour exception is not approval to weaken them.
An accepted target needs current terms/no-charge entitlement, owner scope,
source/build identity, auth/privacy, resource/retention, cold-start/functional
behavior, telemetry/rollback and genuine human acceptance receipts. Stop at
any unresolved gate; don't hop providers until something looks green.

References: [Render free limitations](https://render.com/docs/free),
[Koyeb instance limitations](https://www.koyeb.com/docs/reference/instances),
[Cloud Run pricing](https://cloud.google.com/run/pricing),
[Google budgets](https://docs.cloud.google.com/billing/docs/how-to/budgets),
[Vercel Hobby](https://vercel.com/docs/plans/hobby).
