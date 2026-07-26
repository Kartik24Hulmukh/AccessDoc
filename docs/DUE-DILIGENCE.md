# The Due-Diligence Record

## Why this exists

Every accessibility scanner on the market answers the question *"is this page
conformant right now?"*

That is not the question enforcement actually turns on.

Reviewing early European Accessibility Act enforcement, regulators are not
auditing abstract WCAG scorecards. They act on **use cases that fail real
people**, and the two questions they ask are:

1. **Did the organisation know about the barrier?**
2. **Did it take reasonable steps to fix it, within a reasonable time?**

A single point-in-time scan answers neither. Worse, it can actively harm you:
a scan report sitting in a drive proves *knowledge* while proving nothing about
*action*. It is evidence against you.

## What AccessDoc produces

`due-diligence.md` is built from a chain of dated, tamper-evident receipts and
shows, per barrier:

- when it was **first detected** (establishes the knowledge date)
- whether it was **remediated**, **still present**, or **newly introduced**
- the trend in blocking issues (critical + serious) across the period

Because each receipt is covered by an in-toto attestation and a SHA-256
manifest, any edit to a prior report breaks the manifest hash. Attestations
are unsigned by default; signing requires the Sigstore workflow. Audit dates
are caller-supplied and are not independently timestamped, so the record is
tamper-evident but cannot by itself prevent backdating.

## Usage

```bash
accessdoc bundle scan.json \
  --history q1-receipt.json q2-receipt.json q3-receipt.json \
  --out evidence.zip
```

Receipts may be passed in any order; they are sorted by `audit_date`.

## What it does NOT claim

- It is **not** a conformance claim and **not** a legal opinion.
- Automated scanning detects roughly **30-57%** of WCAG issues. Absence of
  findings is not evidence of conformance.
- A clean trend does not mean a site is accessible. It means the barriers
  *this tool can see* went down.

These limits are printed inside the generated document itself, so the caveat
travels with the artifact rather than living in a README nobody reads.

## Design note: determinism

Every value is derived from the receipts supplied. No wall-clock read occurs
anywhere in generation, which is what allows two runs of the same input to
produce byte-identical output.
