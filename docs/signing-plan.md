# Signing Plan (Future Release)

> **Status: PLANNED — not implemented in v0.6.0-beta.1.**

## Goal

Sign the in-toto attestation so that bundle recipients can verify *who*
generated the bundle and that it has not been modified since generation.

## Proposed approach: sigstore / cosign

### Why sigstore?

- Keyless signing via OpenID Connect (OIDC) — no key management burden
- Free for open-source projects (public good infrastructure)
- Integrated with GitHub Actions (native `sigstore` action)
- Transparency log (Rekor) provides a public, append-only record of signatures
- Widely adopted in the software supply-chain space (SLSA, OpenSSF)

### What would be signed

The in-toto DSSE envelope's `payload` field (the base64-encoded in-toto
Statement). The signature would be added to the `signatures` array in the
envelope, which is currently empty.

### Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  AccessDoc  │────▶│   cosign     │────▶│   Rekor     │
│  generates  │     │   signs      │     │   logs      │
│  bundle     │     │   payload    │     │   signature │
└─────────────┘     └──────────────┘     └─────────────┘
                           │
                           ▼
                    ┌──────────────┐
                    │  Bundle ZIP  │
                    │  contains    │
                    │  signed      │
                    │  attestation │
                    └──────────────┘
```

### Verification flow

1. Recipient receives the bundle ZIP.
2. Extracts `attestation.intoto.json`.
3. Uses `cosign verify` (or a lightweight verifier) to check the signature
   against the signer's identity (e.g., `github.com/Kartik24Hulmukh`).
4. Checks the Rekor transparency log for the signature entry.
5. Runs `validate_bundle()` to verify file hashes.

### CLI changes (future)

```bash
# Generate a signed bundle (requires OIDC token in CI)
accessdoc bundle axe.json --out bundle.zip --sign --identity github.com/Kartik24Hulmukh

# Verify a signed bundle
accessdoc verify bundle.zip --verify-signature --identity github.com/Kartik24Hulmukh
```

### Non-goals for the first signing release

- No GPG/PGP key management (sigstore is keyless)
- No custom CA or PKI
- No support for multiple signers on a single bundle
- No online verification service (offline verification via Rekor log)

### Dependencies

- `sigstore-python` (for signing in Python)
- `cosign` (CLI, for CI/CD integration)
- GitHub Actions OIDC token (for keyless signing in CI)

### Migration path

1. v0.6.0-beta.1: unsigned attestation (current state)
2. Next release: optional signing via `--sign` flag
3. Future: signing enabled by default in CI, unsigned bundles flagged as "unverified"

## Alternative considered: PGP

PGP was considered and rejected because:
- Key management is a significant burden for users
- No built-in transparency log
- Declining adoption in software supply-chain security
- sigstore provides the same guarantees with better UX

## Alternative considered: raw Ed25519

Raw Ed25519 signing was considered and rejected because:
- Requires key distribution and management
- No identity binding (a raw key doesn't prove *who* signed)
- No transparency log
- sigstore provides keyless signing with identity binding via OIDC
