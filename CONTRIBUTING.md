# Contributing to AccessDoc

Contributions to code, documentation, accessibility testing, deterministic mappings, translations, and deployment guidance are welcome.

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
make test verify
```

Use branches such as `fix/...`, `feat/...`, or `docs/...`. Keep each pull request focused. Add tests and documentation for behavior changes.

## Non-negotiable invariants

- Mapping changes require authoritative references, fixtures, deterministic tests, and qualified review.
- Unknown rules remain unmapped; AI output is never normative mapping evidence.
- Never add certification, legal, complete-coverage, or PDF/UA claims without independent evidence.
- Never submit real client reports, personal data, secrets, tokens, or proprietary exports. Use minimized synthetic fixtures.
- UI and report changes must preserve keyboard access, visible focus, responsive layout, readable contrast, and mandatory limitations.
- Security vulnerabilities go through `SECURITY.md`, not public issues.

## Pull requests

Complete the PR template; run the full suite; describe security, privacy, accessibility, compatibility, report, and mapping impact. Ordinary changes require passing checks and independent review. Security boundaries, mappings, privacy behavior, claims, and release policy require two qualified approvals when two eligible maintainers exist.

By contributing, you agree that your contribution is licensed under Apache-2.0. No contributor license agreement is currently required.
