# A11y Weekly Submission

**Subject:** AccessDoc — Tamper-evident accessibility evidence bundles from axe-core JSON

**Blurb (≤300 words):**

AccessDoc is an open-source tool that transforms raw axe-core JSON into a tamper-evident accessibility **evidence bundle**. Rather than claiming conformance (which automated tools can't do — they detect only ~30–57% of WCAG issues per Deque Systems 2022), AccessDoc documents exactly what a scan found, with explicit coverage limits and chain-of-custody protections.

Each bundle contains a PDF report, an accessible HTML companion, an EN 301 549-mapped OpenACR YAML, SARIF 2.1.0 for GitHub Code Scanning, a VPAT draft (marked DRAFT — not certified), an EAA evidence pack, and an in-toto attestation whose SHA-256 digests cover every file. A manifest.json lets anyone verify the bundle hasn't been altered after generation.

Key features in v0.6.0-beta.1:
- Security-hardened: all user-controlled text is HTML-escaped and YAML-safe (regression-tested)
- Provenance labels: every finding is tagged `automated` or `manual`
- Manual-findings merge: combine human review with automated results in one attested bundle
- Deterministic enrichment: a static WCAG knowledge base explains findings in plain language (AI-assisted text is always labeled)
- Multiple interfaces: CLI, stdio MCP server for AI agents, GitHub Action, and a Vercel API
- Regression trend: compare current findings against a prior receipt

AccessDoc never claims conformance. It produces evidence of a conformance *effort* — the kind of documentation procurement teams and regulators can actually verify.

Repo: https://github.com/Kartik24Hulmukh/AccessDoc
Live demo: https://access-doc.vercel.app

*Not legal advice. Not a conformance claim.*
