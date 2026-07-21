# GitHub publication checklist

## Human gates — all required

- [ ] Confirm copyright owner and authority to publish every source, fixture, logo, and document.
- [ ] Confirm release owner.
- [ ] Confirm monitored security contact and enable private vulnerability reporting.
- [ ] Complete qualified name review in intended jurisdictions.
- [ ] Import only `repository/` into a private repository first.
- [ ] Run hosted CI against the exact commit.
- [ ] Require pull requests, independent approval, passing checks, resolved conversations, and no force pushes.
- [ ] Keep the candidate workflow non-publishing; a human must create the prerelease.
- [ ] Review README, UI, sample output, package description, and release notes for claim consistency.
- [ ] Mark `v0.4.0-beta.4` as a prerelease.

## Hosted receipts

- [ ] Empty-cache dependency installation.
- [ ] 20/20 tests.
- [ ] HTTP positive and negative flows.
- [ ] Mobile/desktop browser journey.
- [ ] PDF and HTML/receipt validation.
- [ ] Container build, SBOM, and digest scan.
- [ ] Exact source archive manifest and SHA-256.

Any unresolved ownership, security-contact, name-review, or hosted-CI gate is a publication blocker.
