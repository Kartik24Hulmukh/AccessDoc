# Signing and public verifiability

## The gap this closes

AccessDoc emits an in-toto DSSE attestation with an **empty `signatures`
array**. Be clear about what that does and does not prove:

- It **does** prove internal consistency: every file digest matches the
  manifest, so a modified report is detectable.
- It **does not** prove authorship or time. Anyone who can edit the report can
  regenerate a matching attestation. Against a motivated forger, an unsigned
  attestation is worth nothing.

This matters because the whole pitch is evidence a third party can trust.

## The fix: Sigstore keyless signing

`.github/workflows/sign-evidence.yml` signs a bundle using
[Sigstore](https://www.sigstore.dev/):

- **No long-lived keys.** An ephemeral certificate is issued against the
  workflow's OIDC identity and discarded immediately.
- **Publicly logged.** The signature is recorded in the Rekor transparency
  log, so its existence at a point in time is independently checkable.
- **Identity-bound.** Verification asserts *which repository and workflow*
  produced the bundle.

## Verifying a signed bundle

```bash
pip install sigstore

python -m sigstore verify identity \
  --bundle evidence.zip.sigstore.json \
  --cert-identity "https://github.com/OWNER/REPO/.github/workflows/sign-evidence.yml@refs/heads/main" \
  --cert-oidc-issuer https://token.actions.githubusercontent.com \
  evidence.zip
```

A client, regulator, or opposing counsel can run that command. They do not
need to trust the agency that produced the report.

## Honest status

| Property | Status |
|---|---|
| Bundle is byte-reproducible | Verified and tested across a second boundary |
| Manifest covers every member | Verified |
| Attestation covers every member | Verified |
| Attestation is cryptographically signed | **Only via the signing workflow.** Local `accessdoc bundle` output is unsigned |
| Signature is in a public transparency log | Only for bundles run through the workflow |

Do not describe a locally generated bundle as "signed". It is
**tamper-evident**, which is a weaker and different claim.
