# Supply-chain snapshot scope and replay

## What the checked-in SBOM represents

`sbom.json` is a **local Linux x86_64 CPython 3.13.14 dependency snapshot** for the measured 19-package application-runtime closure, derived from a frozen installed environment for source commit `16a527cccb6974d846a83de30fbfaf384dda13c3`. It is not a deployable-artifact, production, container, or all-platform SBOM.

Its application-root properties bind the exact `requirements.txt` and `pyproject.toml` bytes with SHA-256 and Git blob SHA-1, plus the exact pinned inventory input SHA-256. The component list records every measured dependency version, declared license evidence and the measured wheel distribution URL/hash. All 19 public PyPI wheel hashes were checked against version metadata. This is integrity consistency, not signed upstream provenance or proof against malicious code.

The SBOM was generated from the isolated environment with CycloneDX generator 7.5.0, license text gathering, reproducible output, and schema validation. Installer pip was then excluded from components and dependency references, scope/source/inventory properties were added, and the result was strictly validated against CycloneDX 1.6 JSON. No timestamp or random serial number is included. Determinism is scoped to the same measured inputs/tooling; it does not prove byte-identical builds or PDFs across platforms.

The exclusion of installer, dev/test, optional scanning and signing tooling is intentional and **does not** mean those components are absent from a deployment. Inventory/audit them separately.

## Replay the advisory check without resolving new versions

Use a separate audit-tool environment; do not install its dependencies into the candidate being measured. Extract exact pins from the checked-in dependency inventory:

```sh
python -m venv /tmp/accessdoc-audit-tools
/tmp/accessdoc-audit-tools/bin/python -m pip install --index-url https://pypi.org/simple \
  --require-hashes --only-binary=:all: --no-deps -r requirements-installer.txt
/tmp/accessdoc-audit-tools/bin/python -m pip install pip-audit==2.10.1
python - <<'PY'
import json
from pathlib import Path
bom = json.loads(Path('sbom.json').read_text())
rows = sorted((c['name'], c['version']) for c in bom['components'])
Path('/tmp/accessdoc-runtime-snapshot.txt').write_text(
    ''.join(name + '==' + version + '\n' for name, version in rows))
PY
/tmp/accessdoc-audit-tools/bin/python -m pip_audit --disable-pip --no-deps \
  -r /tmp/accessdoc-runtime-snapshot.txt --format json \
  --output /tmp/accessdoc-runtime-audit.json
/tmp/accessdoc-audit-tools/bin/python scripts/audit_dependency_snapshot.py \
  --snapshot /tmp/accessdoc-runtime-snapshot.txt \
  --audit-json /tmp/accessdoc-runtime-audit.json
```

A public advisory response is time-bound. Zero returned advisories applies to the queried exact versions and is not a package-wide “not vulnerable” claim. The validator rejects skipped/unqueryable packages, missing/extra/wrong-version coverage, malformed results (including duplicate JSON object keys and non-finite values), duplicate packages, unpinned inputs and any advisory records. It performs no installs or network calls itself. Raw pip-audit nonzero exits also fail CI.

## Portable installer bootstrap vs native dependency locks

`requirements-installer.txt` pins only pip 26.2.1 and the SHA-256 of the verified public PyPI `pip-26.2.1-py3-none-any.whl`. Its universal Python wheel tag is not a Linux-specific runtime wheel lock; interpreter-version compatibility still applies. The dependency-security Linux jobs bootstrap **both candidate and audit** venvs with `--require-hashes --only-binary=:all: --no-deps` before installing other packages, then retain the separate candidate installer inventory/audit. This does not alter the main test/platform matrix or the signing workflow.

The initial ensurepip/bundled installer necessarily performs the bootstrap, but only that verified hash-pinned wheel is authorized for the step. Full application runtime/dev native target locks and the audit tool environment's complete transitive/hash lock remain unresolved. Installer portability does not establish OS/browser/native-library or all-platform acceptance.

## CI inventories

The dependency-security job resolves runtime and dev inputs in **separate candidate environments**, snapshots the exact post-install inventories, and audits each from an isolated pip-audit 2.10.1 environment. It preserves the `dependency-audit.cdx.json` artifact path for each scope, and archives raw JSON plus a full `pip freeze --all` installed-environment inventory. Installer pip is queried/audited separately instead of silently disappearing from ordinary `pip freeze`.

These snapshots describe what those jobs actually installed; ranged input installation still varies over time. Separation is not a complete lock solution. The audit tool's direct version is pinned, but its own complete transitive/hash lock remains pending.

At initial inspection the parent environment's pip 24.2 returned six unique advisory IDs (12 raw duplicate advisory records); none were in the 19-package application closure. An explicitly authorized environment-only upgrade to public SHA-256-verified pip 26.2.1 changed only pip; a subsequent full 36-package snapshot advisory audit returned zero records/no skips and package consistency passed. This does not assert that CI runners or shipped images contain that installer version. No repository dependency version was changed by this correction.

## Local two-scope workflow replay

After the installer bootstrap correction, a fresh Linux host replay executed all six dependency-security run steps for each of the runtime/dev scopes using the actual workflow commands and separate fresh candidate/audit venvs. All 12 run-step invocations exited zero. The 19-package runtime and 30-package dev snapshots matched the initially measured versions; both separate installer snapshots were pip 26.2.1. Scope and installer JSON coverage checks returned zero advisories and zero skips. This was **not** hosted GitHub Actions execution, a Windows/macOS run, or Docker/container acceptance.

## Unresolved release gates

- **Native target locks:** no reviewed full transitive/hash runtime/dev lock is committed. The measured Linux-only wheel hashes are not valid universal macOS/Windows/ARM locks. Pytest 9.1.1 has a Windows-only colorama dependency absent from the Linux snapshot; older Python versions have further marker-dependent packages. Resolve and verify each actual supported target natively before adopting locks.
- **Container:** the Docker base remains a mutable tag; no base digest or complete OS/native inventory is bound here. Docker acceptance was not run in this inspection environment. A host wheel replay is not container build/start/health acceptance.
- **Signing:** the signing workflow still uses Python 3.12 and separately installs unpinned ReportLab/PyYAML with Sigstore 4.4.0. Its actual dependency closure is unmeasured here. The three-entry `requirements-release.txt` is not consumed by inspected workflows. A separately measured Python 3.13 legacy release-tool closure is advisory-clean but does not verify the Python 3.12 signing job. Signing workflow/interpreter are intentionally unchanged.
- **Native and browser components:** Python package advisory checks do not audit Pillow's vendored native libraries, CPython, OS packages or Chromium. Optional axe-core 4.11.0 has a separate single-package npm advisory result; that is not a full browser/toolchain scan. CDN content hashing, upstream GSA/openacr commit pinning and actual artifact provenance remain pending.
- **Licenses:** THIRD_PARTY_NOTICES identifies measured runtime versions, not blanket license approval. Preserve upstream texts/native-library notices and review applicable MPL-2.0/Apache/BSD/other redistribution obligations against the actual shipped artifact. Interpreter versions and final-image components must be measured, not inferred from this local snapshot.

Production readiness, all-platform equivalence, signing acceptance, exploitability, and secret-free certification remain outside these results.
