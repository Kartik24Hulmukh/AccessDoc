---
name: accessdoc
description: Generate tamper-evident WCAG accessibility evidence bundles (PDF report, OpenACR/EN 301 549 YAML, SARIF, VPAT draft, EAA pack, in-toto attestation) from axe-core JSON. Use when a user asks to produce an accessibility audit report, VPAT/ACR, EAA evidence, or to gate CI on accessibility findings.
---

# AccessDoc skill

AccessDoc turns raw automated scan output (axe-core JSON) into a defensible,
tamper-evident **evidence bundle**. It does NOT scan by itself and it never
claims conformance - it documents what was found, with explicit coverage
limits, in the formats regulators and procurement accept.

## When to use
- "Make an accessibility audit report / VPAT / ACR / EAA evidence pack."
- "Prove what our accessibility scan found" / "produce a receipt for this scan."
- "Gate our CI build on accessibility issues."
- An AI/agent auditor found issues and needs deterministic, signed output.

## Golden rules (trust model)
1. Automated tooling detects only ~30-57% of WCAG issues (Deque 2022). Always
   surface this limit; never state or imply full conformance.
2. Every finding is provenance-labeled: `automated` vs `manual`.
3. Any AI-generated prose must be labeled `AI-ASSISTED - verify`. The
   deterministic core never invents remediation.
4. All user-controlled text is escaped (HTML/YAML/Markdown safe).

## Quick start (CLI)
```bash
python3 cli.py bundle axe.json --out dist/bundle.zip --sarif --vpat --eaa --enrich
python3 cli.py sarif  axe.json --out findings.sarif.json
python3 cli.py vpat   axe.json --out vpat-draft.html
python3 cli.py eaa    axe.json --out eaa-evidence.md
python3 cli.py bundle axe.json --manual manual-findings.csv --out dist/bundle.zip
python3 cli.py trend prior-receipt.json axe.json --out trend.json
python3 cli.py verify dist/bundle.zip
python3 cli.py scan https://example.com --out axe.json   # optional: playwright
```

## MCP (for agents)
Run `python3 -m mcp.server` and call tools: `catalog_info`, `generate_bundle`,
`export_openacr`, `export_sarif`, `export_vpat`, `verify_bundle`.

## Bundle members
`report.pdf`, `report.html`, `receipt.json`, `openacr.yaml`,
`attestation.intoto.json`, `manifest.json` (always). Optional when requested:
`findings.sarif.json`, `vpat-draft.html`, `eaa-evidence.md`, `trend.json`.
The manifest + in-toto attestation cover the sha256 of every other member.
