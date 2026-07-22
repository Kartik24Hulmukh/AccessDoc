# AccessDoc — WCAG 2.2 Automated Audit Report Generator

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://python.org)
[![WCAG 2.2](https://img.shields.io/badge/WCAG-2.2-green.svg)](https://www.w3.org/WAI/WCAG22/quickref/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.5.0--beta.1-orange.svg)](VERSION)

> **AccessDoc** turns raw [axe-core](https://github.com/dequelabs/axe-core) JSON output into a professional, procurement-ready accessibility audit bundle — PDF report, HTML report, JSON receipt, OpenACR YAML, in-toto attestation, and SHA-256 manifest — in a single ZIP.

---

## What makes AccessDoc different

| Feature | AccessDoc | axe-html-reporter | Generic A11y dashboards |
|---|:---:|:---:|:---:|
| PDF report | ✅ | ❌ | partial |
| OpenACR YAML export (Section 508 / EN 301 549) | ✅ | ❌ | ❌ |
| in-toto supply-chain attestation | ✅ | ❌ | ❌ |
| SHA-256 manifest of every bundle file | ✅ | ❌ | ❌ |
| WCAG 2.2 SC mapping (65+ axe-core rules) | ✅ | partial | partial |
| Vercel serverless deploy | ✅ | ❌ | ❌ |
| GitHub Action CI gate with severity threshold | ✅ | ❌ | ❌ |
| Peer-cited coverage disclaimer (30–57%) | ✅ | ❌ | ❌ |

AccessDoc is the only open-source tool that pairs an automated WCAG 2.2 scan with a **signable supply-chain attestation** and a **procurement-ready OpenACR export** — the two things enterprise and government buyers actually ask for.

---

## Bundle contents (6 files)

| File | Format | Purpose |
|---|---|---|
| `report.pdf` | PDF | Human-readable audit for stakeholders |
| `report.html` | HTML | Machine-readable, embeddable in CI dashboards |
| `receipt.json` | JSON | Structured receipt (schema v1.1) |
| `openacr.yaml` | YAML | OpenACR / VPAT-compatible export, EN 301 549 mapped |
| `attestation.intoto.json` | JSON | Unsigned in-toto v1 DSSE envelope |
| `manifest.json` | JSON | SHA-256 manifest of the other 5 files |

---

## Quick start

### 1. Vercel (serverless)

```bash
git clone https://github.com/your-org/accessdoc
cd accessdoc
vercel deploy
```

```bash
curl -X POST https://your-deployment.vercel.app/ \
  -H 'Content-Type: application/json' \
  -d '{"scanner_input": "<axe-json-as-string>", "client_name": "ACME", "audit_date": "2026-07-23"}' \
  --output bundle.zip
```

### 2. Local

```bash
python3 -c "
import json
from app.service import build_artifacts
from app.bundle import build_bundle
axe = json.load(open('fixtures/axe-sample.json'))
body = {'scanner_input': json.dumps(axe), 'client_name': 'Test', 'audit_date': '2026-07-23'}
open('bundle.zip','wb').write(build_bundle(build_artifacts(body)))
print('bundle.zip written')
"
```

### 3. CI gate

```bash
python scripts/ci_gate.py --axe-json axe-results.json --fail-on critical
```

Or use the reusable GitHub Action at `.github/workflows/accessdoc-action.yml` via `workflow_call`.

---

## Coverage limitations (honest, peer-cited)

Automated tools detect approximately **30–57% of WCAG issues**:
- Deque Systems Accessibility Report 2022 — up to 57% automated coverage
- UK Government Digital Service (2017) — 30–40% of real issues found by automated tools

AccessDoc embeds this disclaimer in every report and receipt.

---

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Expected: **84 tests, 0 failures**.

---

## Project structure

```
accessdoc/
├── app/          # catalog, parser, reporter, openacr, intoto, bundle, service
├── api/          # Vercel serverless handler
├── tests/        # 84 unit tests
├── scripts/      # ci_gate.py
├── fixtures/     # sample axe-core JSON
├── .github/workflows/accessdoc-action.yml
├── gumloop/      # Gumloop system + chat prompts for the launch PR
├── vercel.json
├── requirements.txt
└── VERSION
```

---

## Roadmap

- [ ] axe-core browser extension direct integration
- [ ] Playwright / Cypress plugin
- [ ] SARIF output format
- [ ] VS Code extension
- [ ] Per-rule remediation guidance templates
- [ ] Audit trend dashboard
- [ ] NVDA / VoiceOver manual-test checklist generator

## License

MIT
