# Demo Bundle

This directory contains a pre-generated AccessDoc evidence bundle so you can
see the output format before installing anything.

## File

- `accessdoc-demo-bundle.zip` — a complete tamper-evident evidence bundle generated from `fixtures/axe-sample.json`

## How to inspect it

```bash
# Unzip and look at the contents
unzip accessdoc-demo-bundle.zip -d demo-output/

# Files you'll see:
#   report.pdf          — human-readable PDF summary
#   report.html         — accessible HTML version
#   receipt.json        — machine-readable scan metadata
#   openacr.yaml        — EN 301 549-mapped OpenACR
#   findings.sarif.json — SARIF 2.1.0 for GitHub Code Scanning
#   vpat-draft.html     — VPAT draft (marked DRAFT)
#   eaa-evidence.md     — EAA evidence pack
#   attestation.intoto.json — in-toto attestation with SHA-256 digests
#   manifest.json       — file manifest with hashes
```

## Verify it hasn't been tampered with

```bash
# Using the CLI (after installing AccessDoc)
accessdoc verify examples/demo-bundle/accessdoc-demo-bundle.zip

# Or manually with Python
python3 -c "
import zipfile, json, hashlib
with zipfile.ZipFile('examples/demo-bundle/accessdoc-demo-bundle.zip') as z:
    manifest = json.loads(z.read('manifest.json'))
    for entry in manifest['files']:
        actual = hashlib.sha256(z.read(entry['path'])).hexdigest()
        status = 'OK' if actual == entry['sha256'] else 'MISMATCH'
        print(f'{entry[\"path\"]}: {status}')
"
```

## What this bundle represents

The bundle was generated from a sample axe-core scan of `https://example.com`
with 5 violations (1 critical, 3 serious, 1 minor). It includes all optional
exports (SARIF, VPAT, EAA, enrichment).

**Coverage limitation:** Automated scanning detects ~30-57% of WCAG issues
(Deque Systems 2022). This bundle documents what the scanner found, not what
it missed. It is not a conformance certification.
