# Existing Action quickstart — supplied evidence

Use **AccessDoc Evidence Gate** to convert supplied axe JSON into a reviewable bundle and optional SARIF, then gate on reported severity. It does not scan URLs, invoke remediation, certify accessibility or prove scanner authorship.

Place authorized scanner JSON at `fixtures/axe-sample.json` in the consuming repository. The example below uses AccessDoc’s shipped **synthetic fixture**, not customer evidence. This snippet is preparation, not a Marketplace listing or production workflow approval.

```yaml
- uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
- name: Generate supplied accessibility evidence
  id: evidence
  uses: Kartik24Hulmukh/AccessDoc@d34a04d23bf6380c065d91cc07a219d055b2674a
  with:
    axe-json: fixtures/axe-sample.json
    fail-on: critical
    client-name: Synthetic fixture only
    output-dir: ./accessdoc-out
    sarif: "true"
```

The immutable Action pin identifies the reviewed candidate, **not an approved release**. Its committed tree matches local `6e024238803245e7ba3662d012fd8abe29e3c9ed`; the Action, gate script, fixture and verification CLI bytes were checked against that pin. Do not substitute a moving branch or outdated default version tag.

## Local equivalent and verification

From an existing AccessDoc checkout with its existing Python environment, write outputs outside the repository:

```bash
OUT="$(mktemp -d)"
set +e
python scripts/ci_gate.py --axe-json fixtures/axe-sample.json \
  --output-dir "$OUT" --client-name "Synthetic fixture only" \
  --audit-date 2026-10-03 --fail-on critical --sarif
gate_status=$?
python cli.py verify "$OUT/accessdoc-bundle.zip"
verify_status=$?
if [ "$verify_status" -ne 0 ]; then exit "$verify_status"; fi
exit "$gate_status"
```

Actual output basenames are `accessdoc-bundle.zip` and `findings.sarif.json`. The Action exposes `bundle-path`/`sarif-path` on generation exit0 or1, not build-error2.

Gate meanings: **0** no supplied findings at the configured threshold; **1** threshold exceeded, evidence still produced; **2** input/build/write error. `fail-on: none` explicitly disables severity gating; it is not proof of no violations.

The single authorized local example used an environment allowlist with **no provider keys, upstream configuration or enrichment**: gate **1** for the fixture’s critical finding; actual bundle verification **0**, `valid:true`, empty errors. This is successful generation/integrity verification, not a passing severity gate.

Manifest/in-toto validation checks generated-byte consistency, not scan truth, completeness, human approval or conformance; local attestations are unsigned. No artifact upload, new dependencies, Marketplace listing, registry submission, signup, outreach or adoption claim is included. Strict$0 and all existing release checks remain controlling.
