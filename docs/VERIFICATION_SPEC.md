# AccessDoc Verification Specification

This specification defines the behavior, exit codes, and threat model boundaries of the standalone offline verifier (`scripts/verify_bundle.py`).

## Verifier Primitive and Exit Codes

The offline verifier checks evidence bundle ZIP files against internal digests and structural specifications without requiring external runtime dependencies.

```
VERIFY(bundle.zip) -> exit code
 0   all checks passed
 10  structure    - unreadable/corrupt zip, member set disagrees with manifest, unsupported schema_version, archive over 4 MB cap
 20  integrity    - byte length or sha256 mismatch against manifest.json
 30  content      - report.pdf does not start with %PDF-, receipt.json/attestation.intoto.json unparseable JSON
 40  signature    - requested with --require-signature and signature check failed or tool is absent
 64  usage / limitation - wholesale manifest replacement detected where attestation subject digests disagree with manifest.json
```

## Hostile Fixtures Suite

The repository tests eight hostile mutation fixtures asserting exact exit codes:

| Fixture | Mutation | Exit Code | Rationale |
|---|---|---|---|
| `tampered_member.zip` | 1 byte modified in `report.html` | 20 | Digest mismatch against `manifest.json` |
| `manifest_digest_mismatch.zip` | Edited `sha256` string in `manifest.json` | 20 | Digest mismatch against actual member |
| `extra_member.zip` | File added that `manifest.json` does not list | 10 | Structure check fails |
| `missing_member.zip` | Member removed that `manifest.json` lists | 10 | Structure check fails |
| `not_a_pdf.zip` | `report.pdf` missing `%PDF-` magic bytes | 30 | Content check fails |
| `oversize.zip` | Archive expanded above 4 MB limit | 10 | Zip-bomb / size cap check fails |
| `corrupt_zip.zip` | Truncated/corrupted ZIP bytes | 10 | Bad ZIP format rejected |
| `resealed_manifest.zip` | Member modified and `manifest.json` recomputed | 64 | Attestation subject mismatch / signature required |

## What this does not detect

The standalone offline verifier operates purely using Python standard library primitives (`zipfile`, `hashlib`, `json`). Because Sigstore and Ed25519 cryptographic verification libraries are not in the Python standard library:

1. **Wholesale Resealing without Signature Check**: If an attacker modifies an artifact member, recomputes `manifest.json`, AND rewrites `attestation.intoto.json` without verifying cryptographic signatures, pure digest checking cannot prove the original author's identity.
2. **Signature Verification is Deferred by Default**: By default, `verify_bundle.py` reports `"signature": "DEFERRED"` and provides the exact command for external validation (`cosign verify-blob --bundle <bundle.sigstore.json> <bundle.zip>`).
3. **Mandatory Signature Enforcement**: When cryptographic proof of origin is required, invoke `verify_bundle.py --require-signature`, which delegates to `cosign` or `sigstore` CLI to cryptographically verify author identity and exits with code `40` if verification fails or tooling is missing.
