# Due-Diligence Record — Supplied Evidence Summary

## Purpose and limits

`due-diligence.md` summarizes supplied receipts, dates and observation
counts. Its historical filename is retained; it is **not proof of due diligence**,
organisational knowledge, reasonable steps, remediation or reviewer approval.
It does not establish legal sufficiency or equivalence to a human assessment.

Matching supplied metadata permits only **limited observation differences**.
It does not authenticate browser state, tested scope, origin, source truth or
completeness. A finding not observed in later evidence is not a verified fix;
a finding present at both endpoints is not proof of continuous persistence;
a finding observed only at the end is not proof of a newly caused barrier.
Absence of findings is not evidence of conformance.

Neither the history summary nor trend generation verifies attestations,
signatures, manifests or receipt chains. There is no assumption that every
supplied receipt has an attestation. The summary is not an append-only or
independently authenticated record. A digest identifies supplied data, not
its truth, approval or legal acceptance.

## Usage

```bash
accessdoc bundle scan.json \
  --history q1-receipt.json q2-receipt.json q3-receipt.json \
  --out evidence.zip
```

The bundle path appends the newly generated receipt to the supplied history
and includes `due-diligence.md`. History receipts are sorted lexically by their
supplied `audit_date` (falling back to `date` when available), not by verified
chronology. Dates are caller-supplied and not independently timestamped;
missing or malformed dates do not become authenticated timestamps.

An empty history or a history containing no receipt dictionaries raises
`ValueError` in `build_due_diligence`. If some entries are not dictionaries,
valid timeline rows are retained but comparative results are suppressed.

## Comparison status and exact compatibility rules

Both outputs expose:

- `comparison_basis: "supplied-metadata-only"`.
- `comparison_status: "limited"` when the checks below permit comparison;
  otherwise `"not-comparable"`. There is no verified/authenticated status.
- `comparison_precision` and `warnings`. Precision describes available identity,
  **not** permission to compare: inspect status as well as precision.

A pair is not comparable if **any** of these checks fails:

1. Each supplied receipt must declare supported `schema_version` `"1.1"` or
   `"1.2"`. Missing or unsupported schema suppresses comparison. A supported
   1.1/1.2 transition can use lower shared precision; it does not automatically
   authorize target-level comparison.
2. `url`, `client_name`, `engine_version` and `catalog_version` must be nonempty
   strings on both sides and match exactly. Missing/invalid values or any
   difference suppress comparison. URLs are not normalized to erase route,
   query or other distinctions.
3. If either side supplies `axe_core_verified_version`, `scope`, `state`,
   `viewport`, `exclusions` or `authentication_context`, that field must be
   present and non-null on both sides, have the same type, and match by value.
   No new state-capture or scope-authentication mechanism is implied. Optional
   scope/state fields missing from both sides do not independently suppress
   comparison, but matching URL/tool/client labels do not prove equivalent
   tested states. Undocumented external scope fields are not checked.
4. Pending-check coverage follows the rules below.

History applies these checks to **every adjacent pair** after sorting, not
just the first and last receipts. Any incompatible intermediate link suppresses
the overall comparison. A single receipt is checked against itself; an unchanged
count in that case does not establish improvement over time.

### Pending coverage: missing is not empty or clean

| Supplied `pending_checks` fields | Result |
|---|---|
| Missing from both receipts | Pending coverage is **unknown**. Other checks can still permit a limited comparison, with an explicit warning; this is not evidence of a clean or complete scan. |
| Missing from one side, including missing versus `[]` | Not comparable; suppress differences and deltas. |
| Null, non-list, or malformed entries on either side | Not comparable; suppress differences and deltas. |
| Valid lists differ | Not comparable; suppress differences and deltas. |
| Both valid lists equal `[]` | Other checks can permit limited comparison. Supplied empty lists are not independently verified completeness. |
| Equal valid nonempty lists | Other checks can permit limited comparison, with a warning that matching pending checks remain **unresolved**, not passes or complete coverage. |

For comparison, a valid pending entry is a dictionary with a nonempty string
`id` and a string `target` (which may be empty). Lists are compared as supplied,
including order and all entry details. This is deliberately conservative:
reordered or changed details can suppress comparison even when an operator
believes the coverage is equivalent. Equal lists do not prove that all unresolved
checks were supplied, nor authenticate their reported outcomes.

## Precision and output availability

The lowest available identity precision is used for a pair; history uses the
weakest precision across **all** links.

- **Target-level:** each receipt has schema 1.2, supported
  `finding_fingerprint_version: "1"`, a violations list whose entries have
  nonempty string `id`, `source` and `target`, canonical recomputed fingerprints,
  and a valid `rule_ids` list matching the finding rule inventory. Finding
  identity includes source, so supplied manual and automated observations do
  not collapse merely because rule and target match. Explicit valid empty
  finding/rule lists retain this precision.
- **Rule-level:** valid supplied `rule_ids` exist, but usable target identity
  does not. Rule differences do not identify individual targets or
  source-specific findings. Missing/unsupported fingerprint versions,
  inconsistent fingerprints or malformed findings cannot produce target-level
  absence classifications.
- **Aggregate-only:** no usable supplied rule inventory. Counts may be compared
  only when metadata permits it; no rules or individual findings are classified.

`trend.json` reads identity and counts from the supplied current receipt; the
legacy `current_violations` function argument does not synthesize missing
precision or override that receipt.

| Condition | `trend.json` | History record returned by `build_due_diligence` |
|---|---|---|
| Limited, target-level | Rule and endpoint finding differences/counts available. | Endpoint finding lists/counts available. |
| Limited, rule-level | Rule differences available; finding lists/counts omitted. | Finding lists empty and finding counts `null`; this is not an observed zero. |
| Limited, aggregate-only | Rule lists empty; finding lists/counts omitted. | Finding lists empty and finding counts `null`. |
| Not comparable, at any precision | Rule lists empty, finding lists/counts omitted, `delta_total_violations: null`. Raw summaries retained. | Finding lists empty, counts `null`, `blocking_delta: null`, `trend: "not-comparable"`. Raw timeline and endpoint counts retained. |

Counts must be nonnegative integers; booleans, strings, negative values and
containers are not coerced into counts. Missing/invalid counts yield `null`
comparative values, rendered as `n/a`. History `timeline[].total` is the
**critical + serious + moderate + minor subtotal**, not an asserted complete
finding total; it is unavailable if any constituent count is unavailable.
`blocking_before`/`blocking_after` sum supplied critical and serious counts.
When compatible and both sums are available, `blocking_delta` is end minus
start and `trend` is `decreased`, `increased` or `unchanged`. With compatible
metadata but unavailable counts, `trend` is `unavailable`. None of these count
labels is a verified improvement or regression claim.

## Breaking JSON contract migration

The two output schema versions are separate from input receipt schema versions:

- `trend.json` output schema: **1.3**. This supersedes the previous 1.1 output
  contract and the scoped 1.2 intermediate; removal of the fields below is
  explicitly versioned as breaking. Input receipts remain schema **1.2**
  (with legacy 1.1 inputs subject to compatibility checks).
- History record output schema (`build_due_diligence`): **1.0 → 1.1**.

**This is a breaking field removal, not an additive alias migration.**
`remediated_*` aliases are **not emitted**. Consumers must update field access,
validation and displayed meaning; do not silently recreate remediation aliases
or convert unavailable comparisons into zero findings/fixes.

| Previous field/value | Current contract |
|---|---|
| Trend `fixed_rules` | Removed; use `not_observed_rules`: rules supplied before, not observed in current evidence. |
| Trend `remediated_findings`, `remediated_count` | Removed, with no aliases; use `not_observed_findings`, `not_observed_count` only when those fields are available. |
| Trend `improved`, `regressed` | Removed; no equivalent verified improvement/regression flags. |
| History `remediated`, `remediated_count` | Removed, with no aliases; use `not_observed`, `not_observed_count`. |
| History `knowledge_established` | Removed, with no knowledge-date replacement. `period_start` is only the first supplied date after lexical sorting. |
| History trend `improving`, `regressing`, `flat` | Replaced by neutral supplied-count labels `decreased`, `increased`, `unchanged`, plus `unavailable` and `not-comparable`. |
| Retained `persisting`/`persisting_findings` and counts | Observed at both endpoints, not proven continuously present or unresolved throughout the period. |
| Retained `introduced`/`introduced_findings` and counts | Observed only at end, not proven newly introduced or caused during the period. |

Trend `new_rules` and `persisting_rules` likewise describe supplied rule-set
membership, not causes or verified regressions. Finding entries retain
`finding_fingerprint`, `id`, `source`, `target` and supplied `impact`; identity
consistency does not verify those observations. Check status, precision,
warnings and field availability before presenting differences.

## Determinism is not verification

Generation derives values from supplied receipts rather than a wall-clock
read. Stable inputs allow deterministic summaries and digests; determinism does
not authenticate dates, truth, completeness, consent, human review or legal
acceptance. The generated document carries the supplied-evidence limitations
and does not substitute for qualified accessibility evaluation.
