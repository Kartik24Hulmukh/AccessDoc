# AccessDoc v0.7.0-beta.7

**The receipt printer for accessibility.** AccessDoc turns raw automated scan
output (axe-core JSON) into a defensible, tamper-evident **evidence bundle** in
the formats commonly exchanged in procurement and regulatory diligence - a PDF report, an
EN 301 549-mapped OpenACR YAML, SARIF for CI, a VPAT draft, an EAA evidence
pack, and an in-toto attestation whose digests cover every file.

> AccessDoc documents *what a scan found*, with explicit coverage limits. It
> never claims conformance. Automated tools detect only ~30-57% of WCAG issues
> (Deque 2022); manual + assistive-technology testing is required for a
> conformance claim. Not legal advice.

## Hardening candidate

See [the September 13 engineering receipt](docs/HARDENING-2026-09-13.md) for
verified fixes, local load results, compatibility changes and deployment gates.

## What's new in v0.7.0-beta.7

- **Serverless AI remediation parity.** `POST /api/remediate` is now served by
  the Vercel adapter with the same bounded contract as the self-hosted server
  (Content-Length ceiling, JSON-only errors, `X-Request-ID`, security headers).
- **Bounded remediation admission.** Each HTTP adapter has a dedicated
  `MAX_CONCURRENT_REMEDIATIONS` pool. The local service uses
  `GENERATION_QUEUE_TIMEOUT_SECONDS` (default 0.05 s) for admission;
  the Vercel adapter uses `REMEDIATION_QUEUE_TIMEOUT_SECONDS` (default 10 s).
  Overload and timeout may shed work; historical burst observations are not a
  current-target capacity guarantee.
- **Platform duration requires operator verification.** A function duration is
  not declared by `vercel.json`. Verify the actual deployment ceiling and fit
  the application budget within it; queued calls may still be interrupted by
  the platform.
- **Passive gateway snapshots.** Health/readiness expose gateway state without
  probing a paid model. Missing `MELIOUS_API_KEY` can yield labelled degraded
  static guidance by default; `ACCESSDOC_STRICT_GATEWAY=true` instead returns
  `503 GATEWAY_UNAVAILABLE` with `Retry-After`. Bundle generation is independent
  of provider credential availability.
- **UI**: "Get AI remediation plan" button; static-KB fallbacks are labelled;
  every plan is labelled advisory (no conformance claim).

## Previously in the 0.7.0 beta line

- **Claims and documentation correction.** All overclaims removed: PDF/UA
  conformance language corrected to "experimental structural tagging path;
  no PDF/UA conformance claim until veraPDF passes." Due-diligence renderer
  no longer claims "signed-ready" or "hash chain" — attestation is unsigned
  by default, audit dates are caller-supplied, and the record is
  tamper-evident but does not prevent backdating by itself.
- **Threat model updated.** Signing status changed from "planned" to
  "implemented (Sigstore keyless via GitHub Actions)." Public API
  exhaustion, ZIP bombs, Action input injection, and scanner SSRF added to
  threat list.
- **Version metadata corrected.** Stress test version metadata aligned
  with the canonical `VERSION` file.

## Previously in the 0.7.0 beta line

- **End-to-end validated Sigstore signing workflow.** The signing workflow now
  downloads a real Evidence Gate artifact, verifies the AccessDoc bundle before
  signing, pins sigstore 4.4.0, performs keyless GitHub OIDC signing, verifies
  the certificate identity and issuer, and uploads the signed ZIP with its
  Sigstore bundle. No application behavior changed.

## Previously in the 0.7.0 beta line

- **Due-diligence record** (`due-diligence.md`) - proves *reasonable steps taken
  over time*, not just a point-in-time score. See `docs/DUE-DILIGENCE.md`.
- **Reproducibility actually verified.** Three separate sources of
  non-determinism found and closed (ReportLab timestamps, attestation wall
  clock, ZIP entry mtimes). Tested across a second boundary, not back to back.
  See `docs/REPRODUCIBILITY.md`.
- **Sigstore keyless signing workflow** - publicly verifiable evidence via the
  Rekor transparency log. See `docs/SIGNING.md`.
- Meaningful PDF metadata (`/Title`, `/Lang`, `/Author`, `/Subject`).

## Previously in the 0.7.0 beta line
- **Security hardening:** fixed 2 stored-XSS vectors (client name, URL, and
  violation fields now HTML-escaped) and 1 YAML-injection vector (OpenACR
  scalars are JSON-encoded). Regression-tested in `tests/test_security.py`.
- **SARIF 2.1.0 export** for GitHub Code Scanning.
- **VPAT draft** + **EAA evidence pack** generators.
- **Manual-findings merge** (CSV / Markdown / JSON), provenance-labeled.
- **Provenance-labeled enrichment** (deterministic KB; AI text always flagged).
- **Regression trend** vs a prior receipt.
- **Unified CLI** (`cli.py`), **stdio MCP server** (`mcp/server.py`), and a
  reusable **GitHub Action** (`action.yml` + `scripts/ci_gate.py`).

## AI remediation (`POST /api/remediate`, self-hosted **and** serverless)

**Never a dead surface.** If `MELIOUS_API_KEY` is absent or the whole model
chain is unreachable, the endpoint returns `200` with a deterministic offline
WCAG 2.2 plan (`degraded: true`, `model: offline-kb`, header
`X-AccessDoc-Mode: degraded-offline-kb`) instead of a 503. Set
`ACCESSDOC_STRICT_GATEWAY=1` to restore fail-closed 503 behaviour. See
[docs/degraded-mode.md](docs/degraded-mode.md).


AccessDoc can turn the violations in a scan into a prioritised WCAG 2.2
remediation plan using the Melious frontier-model gateway. The route is fully
fault-tolerant: an ordered chain `GLM-5.3 -> GLM-5.3 Flash -> Qwen 3.8 27B ->
Kimi K3` with per-model circuit breakers, `Retry-After`-aware bounded retries, a
hard wall-clock budget (`GATEWAY_BUDGET_SECONDS`, default 40; a model that times out is failed over immediately rather than retried) and a
deterministic static knowledge-base last resort. **It never returns a 5xx for
an upstream model failure and never returns an empty answer.**

```bash
export MELIOUS_API_KEY=...            # env only; never committed
python3 -m app.main &
curl -s -X POST localhost:8000/api/remediate -H 'Content-Type: application/json' \
  -d '{"scanner_input": '"$(cat fixtures/axe-sample.json)"'", "client_name": "Acme", "model": "GLM-5.3"}'
```

Response: `{"model", "fallback", "attempts", "latency_ms", "tokens",
"violations_considered", "guidance"}`. Either `scanner_input` (axe JSON, same
limits as `/api/generate`) or a bare `violations` list is accepted; at most 25
violations, 300 chars per field, control characters stripped, and the prompt
instructs the model to treat scanner text as untrusted data.

Operations: `/readyz` reports passive gateway state and whether a provider
credential is configured; a reachable route or readiness response does not prove
that a live model request succeeded. `/metrics` exposes
`accessdoc_gateway_remediate_{requests,fallbacks,errors}_total` and
`accessdoc_gateway_circuit_open{model=...}`.

Both the local HTTP service and Vercel adapter implement `POST /api/remediate`.
Each has a separate `MAX_CONCURRENT_REMEDIATIONS` admission pool. Queue timeout
is `GENERATION_QUEUE_TIMEOUT_SECONDS` in the local service and
`REMEDIATION_QUEUE_TIMEOUT_SECONDS` in the Vercel adapter. This is route/schema
parity, not a
claim that the current hosted deployment has funded or validated live models.
By default, missing/unavailable upstream models may return labelled static
knowledge-base guidance (`fallback: true`). Set `ACCESSDOC_STRICT_GATEWAY=true`
to return `503 GATEWAY_UNAVAILABLE` with `Retry-After` instead of degraded
fallback when the provider is unavailable.

For a zero-model-spend HTTP pilot, set `ACCESSDOC_REMEDIATION_ENABLED=false`
and do not configure an upstream provider credential. This rejects new
remediation work, including offline remediation, while deterministic bundle
generation can remain enabled. It does not govern direct CLI/MCP/custom gateway
calls, cancel previously accepted work, or cap account/fleet spending. Configure
required private pilot authentication separately. See
[Zero-spend pilot boundaries](docs/ZERO_SPEND_PILOT.md) before applying any
hosting example. No paid provider, hosting upgrade, production approval or
accessibility-conformance claim follows from these controls.

## Install
```bash
git clone https://github.com/Kartik24Hulmukh/AccessDoc.git
cd AccessDoc
python3 -m venv .venv
. .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -r requirements-dev.txt
python cli.py bundle fixtures/axe-sample.json --out dist/bundle.zip --sarif --vpat --eaa
python cli.py verify dist/bundle.zip
```

## CLI
```bash
python3 cli.py bundle axe.json --out dist/bundle.zip --sarif --vpat --eaa --enrich
python3 cli.py verify dist/bundle.zip     # exit 0 = intact, 1 = tampered
python3 cli.py catalog                    # rule catalog summary
```

## Test
```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/stress_test.py                          # 15 adversarial checks
```

## Bundle members
`report.html` (**the accessible artifact** - axe-core audited, zero violations
at critical/serious/moderate, tested at 320px reflow), `report.pdf`
(**untagged convenience copy - not screen-reader navigable**), `receipt.json`,
`openacr.yaml`,
`attestation.intoto.json`, `manifest.json` (always). Optional when requested:
`due-diligence.md` (via `--history`),
`findings.sarif.json`, `vpat-draft.html`, `eaa-evidence.md`, `trend.json`.

Live demo API: `https://access-doc.vercel.app` (GET = health, POST axe JSON = zip).
This is a **bounded demo API** — input size is limited; deployer-managed rate limiting is required. It is
not a production-grade hosted service.


## Limitations (read this before making any claim)

- **Automated scanning detects ~30-57% of WCAG issues** (Deque 2022; GDS 2017).
  Absence of findings is not evidence of conformance.
- **`report.pdf` is untagged.** No `/StructTreeRoot`, no table tagging, implicit
  reading order. Screen readers cannot navigate it semantically. `report.html`
  is the accessible artifact. Do not present the PDF to a client as
  accessibility conformance evidence.
- **Locally generated attestations are unsigned.** They are *tamper-evident*,
  not *signed*. Public verifiability requires the Sigstore workflow
  (`docs/SIGNING.md`).
- **VPAT output is a DRAFT.** It requires human review before issuance.
- Reproducibility requires pinning `--audit-date`. It is an input, not an
  observation.

