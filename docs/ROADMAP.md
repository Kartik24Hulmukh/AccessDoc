# AccessDoc Roadmap

## Positioning: why this is not another scanner

The automated accessibility scanner market is saturated and commoditised.
axe-core is MIT-licensed and powers nearly every tool, free or paid. Competing
on detection quality is competing against the thing everyone already embeds.

AccessDoc does not compete there. **axe-core is an input, not the product.**

The product is the *evidence layer*: a tamper-evident, byte-reproducible,
publicly verifiable record of what was found, when it was found, and what was
done about it. Nobody in the open-source space is building this.

### The insight the roadmap is built on

Early EAA enforcement is not driven by WCAG scorecards. Regulators act on
use cases that fail real people, and they ask:

> Did the organisation know, and did it take reasonable steps?

Every scanner answers "what is broken now?" That is the wrong question, and
answering it alone produces a document that proves knowledge without proving
action -- evidence *against* the holder.

AccessDoc answers the question that is actually asked.

## Shipped in v0.7.0-beta.1

| Item | Why it matters |
|---|---|
| Due-diligence record | The only artifact in the category that evidences reasonable steps over time |
| Reproducibility genuinely closed (3 root causes) | Without it the hash chain proves nothing |
| Sigstore keyless signing workflow | Moves evidence from "we say so" to third-party verifiable |
| Honest PDF/HTML split | Credibility. An accessibility tool shipping an untagged PDF as "conformance evidence" is self-refuting |

## Next

### P0 - required before any public launch
- **Adoption gate.** 5 practitioner responses. No engineering substitutes for this.
- **Trademark clearance** on the product name.
- Run **veraPDF** against a WeasyPrint-rendered bundle. No PDF/UA claim without
  a validator result.

### P1 - deepens the moat
- **Sign by default**, not just in CI. Local bundles are unsigned today.
- **`accessdoc verify` against Rekor** - let a third party verify with one
  command and no trust in the issuer.
- **Hosted verification page.** Drop a bundle in, see pass/fail. The single
  highest-leverage traction asset: it makes the value legible in 5 seconds.

### P2 - distribution
- Tagged PDF via WeasyPrint once veraPDF-validated (opt-in first).
- GitHub Marketplace listing.
- Quarterly re-audit scheduling to make the due-diligence chain accumulate
  automatically. Recurring value, not a one-shot report.

## Explicit non-goals

- **Do not build an overlay.** Overlays carry a 22.6% litigation rate and the
  FTC fined accessiBe $1M. Proximity is reputational poison.
- **Do not claim conformance.** AccessDoc produces evidence; humans certify.
- **Do not compete on detection.** That is axe-core's job.
