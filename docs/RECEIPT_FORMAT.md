# Receipt format

`receipt.json` is the machine-readable core of an AccessDoc evidence bundle. It
identifies the submitted scanner input and the generated report by SHA-256, and
records what was found, by which engine, against which rule catalog.

Machine-readable contract: [`schemas/receipt-1.2.schema.json`](../schemas/receipt-1.2.schema.json)

## What a receipt does and does not establish

| Property | Provided by | Not provided |
|---|---|---|
| The receipt has not been edited since generation | `finding_fingerprint` re-derivation + manifest digests | — |
| Every bundle member is byte-identical to what was attested | `manifest.json` SHA-256 over each member | — |
| The bundle was built by this project's workflow | Sigstore signature (signing workflow) | Unsigned bundles prove nothing about origin |
| The audit happened on the stated date | — | `audit_date` is **caller-supplied** and never independently timestamped |
| The submitter is who they claim | — | No submitter authentication exists |
| The site conforms to WCAG | — | Automated scans detect roughly 30-57% of WCAG issues |

A receipt is evidence of *what a scan reported*, bound to specific bytes. It is
not a conformance claim and not a legal opinion.

## Schema versions

| Version | Identity level | Contents |
|---|---|---|
| `1.0` | aggregate-only | Counts and summary only. No finding can be individually tracked. |
| `1.1` | rule-level | Adds `rule_ids`. You can say "`color-contrast` was detected then later absent", not "*this element* was fixed". |
| `1.2` | target-level | Adds `violations[]` with a normalized `target` and a `finding_fingerprint` per finding, plus `finding_fingerprint_version`. |

Older receipts stay readable forever. Verifiers never upgrade a receipt's
precision by guessing.

### Migrating from 1.1 to 1.2

Nothing is removed in 1.2; every 1.1 field is still present. To adopt it:

1. Regenerate with v0.7.0-beta.5 or later. Existing bundles do not need to be
   rebuilt and remain valid.
2. When comparing a 1.1 receipt against a 1.2 receipt, the comparison degrades
   to `rule-level` automatically and says so in `trend.json.warnings`. This is
   deliberate: mixing precision levels silently is how false remediation claims
   get made.
3. Once two consecutive audits are both 1.2, `trend.json` gains
   `remediated_findings`, `persisting_findings`, and `introduced_findings`.

## Comparison precision tiers

`trend.json.comparison_precision` and `accessdoc chain` both report the weakest
link, never the strongest:

- **`target-level`** — both receipts carry per-finding targets and verifiable
  fingerprints. Individual barriers can be tracked across time.
- **`rule-level`** — rule ids exist on both sides. Rules can be tracked; elements
  cannot.
- **`aggregate-only`** — counts only. No finding may be described as remediated,
  persisting, or introduced. Only totals moved.

## `finding_fingerprint`

Derivation (`finding_fingerprint_version` = `1`):

```
canonical = json.dumps({"rule": rule_id, "source": source, "target": target},
                       sort_keys=True, separators=(",", ":"), ensure_ascii=False)
fingerprint = sha256(canonical.encode("utf-8")).hexdigest()   # 64 chars, never truncated
```

**What it is.** A stable identity for one finding on one element from one source,
so the same barrier is recognisable across audits and so an edit to any of those
three values is detectable by recomputation.

**What it is not.**

- Not a secret, not a MAC, and not keyed. Anyone can compute it. It proves
  self-consistency, not authorship.
- Not stable across DOM restructuring. If a selector changes because the page was
  refactored, the fingerprint changes and the finding will be reported as
  introduced rather than persisting. Judgement is still required.
- Not meaningful for findings with fallback identity. When a scanner supplies no
  usable target, the deterministic value `<rule-id>:no-target` is used, which
  collapses that finding to rule-level identity even inside a 1.2 receipt.

### Target normalization

Selector chains are joined with `" > "`, control characters are stripped, the
result is bounded to 200 characters, and duplicate targets within one rule are
deduplicated. Normalization is deterministic, so the same scan input always
yields the same fingerprints.

## Verification

Strongest to weakest. Run all three for a full check.

```bash
# 1. Bundle integrity: structure, manifest digests, attestation subjects,
#    and receipt self-consistency in one pass.
python3 cli.py verify dist/bundle.zip

# 2. Receipt only: schema 1.2 structure plus re-derivation of every fingerprint.
python3 cli.py receipt-check receipt.json

# 3. Chain: self-consistency of each link, chronological order, and the
#    weakest defensible comparison precision across the whole history.
python3 cli.py chain audit-2026-01.json audit-2026-04.json --md due-diligence.md
```

A tampered receipt exits non-zero. Verify that for yourself before trusting a
pass — edit any `target` value and re-run `receipt-check`.

### Signature verification

Bundle integrity says the bytes are internally consistent. Only the signature
says this project built them:

```bash
pip install sigstore==4.4.0
python3 -m sigstore verify identity \
  --bundle signed-sample-bundle.zip.sigstore.json \
  --cert-identity "https://github.com/Kartik24Hulmukh/AccessDoc/.github/workflows/sign-evidence.yml@refs/heads/main" \
  --cert-oidc-issuer "https://token.actions.githubusercontent.com" \
  signed-sample-bundle.zip
```

## Legacy input receipt check

The original narrow check — does this receipt match the exact submitted text and
the generated PDF — is still available:

```bash
python scripts/verify_receipt.py receipt.json submitted-input.txt report.pdf
```

Use the exact UTF-8 text submitted to the API. Browser file decoding or newline
conversion can make an original file differ from the submitted text; that
difference must not be described as tampering.

## Bundle members

`report.pdf`, `report.html`, `receipt.json`, `openacr.yaml`,
`attestation.intoto.json`, `manifest.json` are always present. `manifest.json` is
always last and covers every other member. Optional members
(`findings.sarif.json`, `vpat-draft.html`, `eaa-evidence.md`, `trend.json`,
`due-diligence.md`) are inserted before the attestation so they are attested too.

SARIF results carry the same identity under
`partialFingerprints["accessdocFindingFingerprint/v1"]`, so code-scanning
platforms keep one alert per barrier instead of reopening every finding on every
scan.
