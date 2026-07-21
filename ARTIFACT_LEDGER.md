# Artifact ledger — 0.4.0-beta.4

Exactly one downloadable authority is permitted.

## Current authority

- Filename: `AccessDoc-v0.4.0-beta.4-vercel-ready-source.zip`
- Scope: GitHub-ready open-source repository, local/container runtime, stateless Vercel Python adapter, static UI, tests, stress harness, release verifier, Vercel/Gumloop runbooks, and sanitized local verification receipt.
- Archive file count, byte count, and SHA-256: recorded in the external delivery receipt after deterministic packaging because an archive cannot contain its own digest without changing that digest.
- Supersession: replaces `AccessDoc-v0.4.0-beta.3-open-source-rc.zip` and every earlier AccessDoc ZIP.

## Authority rule

Extract the archive and use its single top-level directory as the GitHub repository root. Do not mix files from a previous beta. Gumloop prompts are included in `gumloop/` and `GUMLOOP_PROMPTS.md`; no second prompt artifact is authoritative.
