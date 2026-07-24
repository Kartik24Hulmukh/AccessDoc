# Show HN: AccessDoc — Tamper-evident accessibility evidence from axe-core JSON

**Title:** Show HN: AccessDoc – Turn axe-core JSON into a tamper-evident accessibility evidence bundle

**Body:**

Hi HN,

I built AccessDoc because accessibility audit reports are often just screenshots in a Word doc. There's no chain of custody, no tamper detection, and no way to prove what the scanner actually found vs. what someone edited afterwards.

AccessDoc takes raw axe-core JSON and produces a **tamper-evident evidence bundle** containing:

- A PDF report + accessible HTML companion
- An EN 301 549-mapped OpenACR YAML (the format EU procurement asks for)
- SARIF 2.1.0 for GitHub Code Scanning
- A VPAT draft (clearly marked DRAFT — not a certified VPAT)
- An EAA evidence pack (European Accessibility Act)
- An in-toto attestation whose SHA-256 digests cover every file
- A manifest.json that lets anyone verify the bundle hasn't been altered

The key design decisions:

1. **It never claims conformance.** Automated tools detect ~30–57% of WCAG issues (Deque 2022). Every bundle states this limit explicitly. The VPAT draft says "DRAFT — AUTOMATED EVIDENCE ONLY — NOT A CERTIFIED VPAT" in red.

2. **Provenance labels on every finding.** Each violation is tagged `automated` or `manual`. You can merge manual findings (CSV/Markdown) and they're attested alongside the automated ones.

3. **Security-hardened output.** All user-controlled text is HTML-escaped (prevents stored XSS in reports) and YAML-safe (prevents injection in OpenACR). Regression-tested in `test_security.py`.

4. **Deterministic core.** No network calls, no LLM in the evidence pipeline. The enrichment KB is a static dictionary. Any AI-assisted text is labeled `AI-ASSISTED - verify`.

5. **Multiple interfaces:** CLI (`accessdoc bundle axe.json --sarif --vpat --eaa`), a stdio MCP server for agents, a Vercel serverless API, and a reusable GitHub Action.

It's at v0.6.0-beta.1. The test suite has 170 tests (25 skipped for optional deps) and 15 adversarial stress checks (XSS payloads, YAML injection, 5000-violation scale, tamper detection).

I'd love feedback on:
- Is the "evidence, not conformance" framing useful for procurement contexts?
- What other formats do you need? (Section 508 mapping? A11yScore?)
- Would you hand this output to a client?

Repo: https://github.com/Kartik24Hulmukh/AccessDoc
Live demo: https://access-doc.vercel.app (GET = health, POST axe JSON = bundle zip)

Not legal advice. Not a conformance claim. Just evidence of what a scan found.
