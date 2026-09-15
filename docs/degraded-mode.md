# Degraded mode for POST /api/remediate

AccessDoc calls a model gateway to produce remediation guidance. Before this
change, a deployment without `MELIOUS_API_KEY` answered **every** remediation
request with `503 GATEWAY_UNAVAILABLE` - the production deployment did exactly
that, so the AI surface was unusable for users even though the repository
already contained a deterministic WCAG knowledge base.

## Behaviour now

| Condition | Response |
|---|---|
| Gateway configured and healthy | `200` with model guidance (`degraded` absent) |
| Chain degraded but reachable | `200`, `fallback: true`, `model: static-kb` |
| No credential, or whole chain unreachable | `200`, `fallback: true`, `degraded: true`, `model: offline-kb`, header `X-AccessDoc-Mode: degraded-offline-kb` |
| Invalid input | `422` (unchanged, in every mode) |
| `ACCESSDOC_STRICT_GATEWAY=1` and no credential | `503` + `Retry-After: 5` (fail-closed, opt-in) |

## Offline plan contents

`app/remediate.py` maps the common axe-core rule ids to a WCAG 2.2 success
criterion, a concrete code-level fix, an S/M/L effort estimate and a
verification step. Findings are ordered critical -> serious -> moderate ->
minor, then by instance count. Rules with no curated entry still receive a
usable reproduce-fix-rescan instruction. The output is deterministic, so two
identical inputs produce byte-identical guidance - which is what an evidence
product needs.

Every degraded response carries `notice`, and the UI labels it, so nobody
mistakes knowledge-base output for model output.

## Operator guidance

* Set `MELIOUS_API_KEY` to enable model-backed guidance.
* Set `ACCESSDOC_STRICT_GATEWAY=1` if your policy is fail-closed instead.
* Alert on `accessdoc_gateway_remediate_offline_total` rising: it means the
  chain is unreachable, even though users are still being served.
