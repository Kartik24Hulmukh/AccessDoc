# How to Read Your AccessDoc Evidence Bundle

## What you received

An AccessDoc evidence bundle is a ZIP file containing documentation of what an automated accessibility scan (axe-core) found. It is **evidence of a conformance effort**, not a declaration of conformity.

## Bundle contents

| File | What it is | How to read it |
|------|-----------|---------------|
| `report.pdf` | Human-readable PDF summary | Open in any PDF viewer |
| `report.html` | Accessible HTML version of the report | Open in a browser |
| `receipt.json` | Machine-readable scan metadata + summary | JSON viewer or `jq` |
| `openacr.yaml` | EN 301 549-mapped OpenACR (EU procurement format) | YAML viewer |
| `attestation.intoto.json` | in-toto attestation with SHA-256 digests | JSON viewer |
| `manifest.json` | File manifest with SHA-256 hashes | JSON viewer |
| `findings.sarif.json` | SARIF 2.1.0 for GitHub Code Scanning (optional) | SARIF viewer |
| `vpat-draft.html` | VPAT draft — DRAFT, not certified (optional) | Browser |
| `eaa-evidence.md` | EAA evidence pack (optional) | Markdown viewer |
| `trend.json` | Regression trend vs prior receipt (optional) | JSON viewer |

## Verifying the bundle hasn't been tampered with

```bash
# Using the CLI
accessdoc verify bundle.zip

# Or manually: check that every file's SHA-256 matches the manifest
python3 -c "
import zipfile, json, hashlib
with zipfile.ZipFile('bundle.zip') as z:
    manifest = json.loads(z.read('manifest.json'))
    for entry in manifest['files']:
        actual = hashlib.sha256(z.read(entry['path'])).hexdigest()
        status = 'OK' if actual == entry['sha256'] else 'MISMATCH'
        print(f'{entry[\"path\"]}: {status}')
"
```

If all files show `OK`, the bundle is intact. Any `MISMATCH` means the file was altered after generation.

## Understanding the coverage limit

Every bundle states: **"Automated scan detects ~30-57% of WCAG issues (Deque Systems 2022)."**

This means:
- A clean automated scan does NOT mean the site is accessible
- The bundle documents what the scanner found, not what it didn't check
- Manual and assistive-technology testing is required for a conformance claim

## Understanding provenance labels

Each finding in the report is labeled with a `source` field:
- `automated` — detected by axe-core
- `manual` — added by a human reviewer

This lets you see at a glance which findings are machine-detected vs. human-verified.

## The VPAT draft

The `vpat-draft.html` file is marked **"DRAFT — AUTOMATED EVIDENCE ONLY — NOT A CERTIFIED VPAT"** in red. This is intentional. A real VPAT requires manual testing and a qualified evaluator. The draft gives you a starting structure.

## The EAA evidence pack

The `eaa-evidence.md` file maps findings to EN 301 549 clauses (Chapter 9, Web) and includes fields for the provider to complete (compliance status, feedback mechanism, enforcement procedure). It is evidence for EAA compliance efforts, not a declaration of conformity.

## What this bundle is NOT

- It is NOT a conformance certificate
- It is NOT legal advice
- It is NOT a substitute for manual accessibility testing
- It does NOT claim the audited site is accessible

## What this bundle IS

- A tamper-evident record of what an automated scan found
- Documentation of a conformance *effort*
- A starting point for a full accessibility evaluation
- Verifiable evidence you can share with stakeholders
