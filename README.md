# AccessDoc v0.7.0-beta.5

**The receipt printer for accessibility.** AccessDoc turns raw automated scan
output (axe-core JSON) into a defensible, tamper-evident **evidence bundle** in
the formats regulators and procurement actually accept - a PDF report, an
EN 301 549-mapped OpenACR YAML, SARIF for CI, a VPAT draft, an EAA evidence
pack, and an in-toto attestation whose digests cover every file.

> AccessDoc documents *what a scan found*, with explicit coverage limits. It
> never claims conformance. Automated tools detect only ~30-57% of WCAG issues
> (Deque 2022); manual + assistive-technology testing is required for a
> conformance claim. Not legal advice.

## What's new in v0.7.0-beta.3

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
- **Version metadata corrected.** Stress test version updated from
  v0.6.0-beta.1 to v0.7.0-beta.3.

## What's new in v0.7.0-beta.2

- **End-to-end validated Sigstore signing workflow.** The signing workflow now
  downloads a real Evidence Gate artifact, verifies the AccessDoc bundle before
  signing, pins sigstore 4.4.0, performs keyless GitHub OIDC signing, verifies
  the certificate identity and issuer, and uploads the signed ZIP with its
  Sigstore bundle. No application behavior changed.

## What's new in v0.7.0-beta.1

- **Due-diligence record** (`due-diligence.md`) - proves *reasonable steps taken
  over time*, not just a point-in-time score. See `docs/DUE-DILIGENCE.md`.
- **Reproducibility actually verified.** Three separate sources of
  non-determinism found and closed (ReportLab timestamps, attestation wall
  clock, ZIP entry mtimes). Tested across a second boundary, not back to back.
  See `docs/REPRODUCIBILITY.md`.
- **Sigstore keyless signing workflow** - publicly verifiable evidence via the
  Rekor transparency log. See `docs/SIGNING.md`.
- Meaningful PDF metadata (`/Title`, `/Lang`, `/Author`, `/Subject`).

## Previously in v0.7.0-beta.1
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

## Install
```bash
pip install -r requirements.txt   # reportlab (PyYAML only for tests)
```

## CLI
```bash
python3 cli.py bundle axe.json --out dist/bundle.zip --sarif --vpat --eaa --enrich
python3 cli.py verify dist/bundle.zip     # exit 0 = intact, 1 = tampered
python3 cli.py catalog                    # rule catalog summary
```

## Test
```bash
python3 -m unittest discover -s tests -p 'test_*.py'   # 540 tests
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
This is a **bounded demo API** — input size and request rate are limited. It is
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

