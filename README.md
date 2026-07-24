# AccessDoc v0.6.0-beta.1

**The receipt printer for accessibility.** AccessDoc turns raw automated scan
output (axe-core JSON) into a defensible, tamper-evident **evidence bundle** in
the formats regulators and procurement actually accept - a PDF report, an
EN 301 549-mapped OpenACR YAML, SARIF for CI, a VPAT draft, an EAA evidence
pack, and an in-toto attestation whose digests cover every file.

> AccessDoc documents *what a scan found*, with explicit coverage limits. It
> never claims conformance. Automated tools detect only ~30-57% of WCAG issues
> (Deque 2022); manual + assistive-technology testing is required for a
> conformance claim. Not legal advice.

## What's new in v0.6.0-beta.1
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
python3 -m unittest discover -s tests -p 'test_*.py'   # 170+ tests
python3 scripts/stress_test.py                          # 15 adversarial checks
```

## Limitations

AccessDoc is an evidence tool, not a certification. Read the
[Threat Model](docs/THREAT-MODEL.md) for a full security analysis.

- **Automated coverage ceiling:** axe-core detects ~30-57% of WCAG issues
  (Deque 2022). Every bundle states this limit.
- **Unsigned attestation:** The in-toto attestation is currently unsigned.
  It detects accidental corruption and naive tampering, but does NOT prove
  origin against a motivated attacker. See [Signing Plan](docs/signing-plan.md).
- **PDF is not accessible:** The generated `report.pdf` is an untagged PDF
  without PDF/UA compliance. It has a meaningful title, language (`/Lang=en`),
  and author metadata, but no structure tree for screen reader navigation.
  The HTML companion (`report.html`) IS accessible (axe-core-audited, zero
  violations). An experimental WeasyPrint path (`--pdf-engine=weasyprint`)
  can produce a tagged PDF/UA-1 but is not byte-reproducible. See
  [PDF/UA Plan](docs/pdf-ua-plan.md).
- **VPAT output is DRAFT:** The VPAT generator produces a draft input for
  human review, not a certified VPAT.
- **Not legal advice:** Nothing AccessDoc produces is legal advice or a
  declaration of conformity.

## Self-audit

AccessDoc's own HTML outputs (report.html, vpat-draft.html) are audited with
axe-core in a permanent regression test. See
[Self-Audit Report](docs/self-audit.md).

## Bundle members
`report.html` (accessible, axe-core-audited), `receipt.json`, `openacr.yaml`,
`attestation.intoto.json`, `manifest.json` (always). Optional when requested:
`report.pdf` (untagged — see [PDF/UA Plan](docs/pdf-ua-plan.md)),
`findings.sarif.json`, `vpat-draft.html`, `eaa-evidence.md`, `trend.json`.

> **The HTML report is the accessible artifact.** The PDF is a convenience
> copy and is currently untagged (no PDF/UA structure tree). Screen reader
> users should use `report.html`.

Live demo API: `https://access-doc.vercel.app` (GET = health, POST axe JSON = zip).
