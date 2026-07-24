# Accessibility

This project follows the [ACCESSIBILITY.md](https://github.com/mgifford/ACCESSIBILITY.md)
convention: a machine- and human-readable statement of a project's
accessibility posture and how it is evidenced.

## Conformance target
- **Standard:** WCAG 2.2 Level AA / EN 301 549 (Chapter 9, Web).
- **Status:** AccessDoc is a documentation tool. Its own generated artifacts
  (HTML report, VPAT draft) are built to be accessible; the product does not
  claim conformance on behalf of audited sites.

## How accessibility is evidenced here
- Automated scanning with axe-core (verified 4.11.2).
- Every bundle ships a tamper-evident `receipt.json`, an EN 301 549-mapped
  `openacr.yaml`, and an in-toto attestation whose digests cover all members.
- Coverage is stated explicitly: automated tools detect ~30-57% of WCAG
  issues (Deque Systems 2022); manual and assistive-technology testing is
  required for a conformance claim.

## Provenance
- Findings are labeled `automated` or `manual`.
- Any AI-assisted explanatory text is labeled `AI-ASSISTED - verify`.

## Feedback
Accessibility issues with AccessDoc itself: open an issue on the repository.

## Limitations
This file and the artifacts AccessDoc produces are evidence of a conformance
*effort*. They are not legal advice and not a declaration of conformity.
