# Outreach Email Variants for Accessibility Practitioners

## Variant A — Direct practitioner outreach

**Subject:** Would you hand this accessibility evidence to a client?

Hi [name],

I've been following your work in accessibility auditing and thought you might be interested in AccessDoc — an open-source tool that turns axe-core JSON into a tamper-evident evidence bundle.

The idea: instead of screenshots in a Word doc, you get a ZIP containing a PDF report, an EN 301 549 OpenACR YAML, SARIF, a VPAT draft, an EAA evidence pack, and an in-toto attestation whose SHA-256 digests cover every file. Anyone can verify the bundle hasn't been altered.

It explicitly does NOT claim conformance — automated tools detect ~30–57% of WCAG issues (Deque 2022), and every bundle says so. But it does give you defensible documentation of what the scan found, with provenance labels on every finding (`automated` vs `manual`).

You can also merge your manual findings (CSV/Markdown) into the same attested bundle.

I'm looking for honest feedback from 5 practitioners before broader launch. Would you be willing to:
1. Run it on a recent axe-core scan (takes 30 seconds)
2. Tell me whether you'd hand the output to a client (yes/no, and why)

If yes, I'll send you a quick-start guide. No strings attached.

Repo: https://github.com/Kartik24Hulmukh/AccessDoc
Live demo: https://access-doc.vercel.app

Thanks for your time,
[your name]

---

## Variant B — Compliance/procurement angle

**Subject:** Tamper-evident accessibility evidence — early feedback request

Hi [name],

In procurement contexts, accessibility reports are often just assertions. "We passed a scan." But which tool? Which version? What coverage? Can you verify it hasn't been edited?

AccessDoc v0.6.0-beta.1 is an open-source tool that produces a **verifiable** evidence bundle from axe-core JSON:

- PDF + HTML report
- EN 301 549 OpenACR YAML (the format EU procurement uses)
- SARIF 2.1.0 for GitHub Code Scanning
- VPAT draft (marked DRAFT — not certified)
- EAA evidence pack (European Accessibility Act)
- in-toto attestation with SHA-256 digests covering every file

It states its limitations explicitly: automated scanning detects ~30–57% of WCAG issues. No conformance claims. Just evidence of what was found, with chain-of-custody.

I'm seeking feedback from accessibility practitioners before broader launch. Would you be willing to try it on a real scan and tell me:
1. Is the output format useful for your workflow?
2. Would you hand this to a client?

Quick start: `pip install accessdoc && accessdoc bundle axe.json --sarif --vpat --eaa`

Thanks,
[your name]

---

## Variant C — Developer/CI angle

**Subject:** Gate your CI on accessibility — with tamper-evident evidence

Hi [name],

Saw your work on accessibility in CI pipelines. AccessDoc is an open-source tool that takes axe-core JSON and produces a tamper-evident evidence bundle — plus a GitHub Action that gates CI on severity.

```
- uses: Kartik24Hulmukh/AccessDoc@v0.6.0-beta.1
  with:
    axe-json: axe-results.json
    fail-on: critical
    sarif: true
```

The Action generates a bundle (PDF, OpenACR YAML, SARIF, VPAT draft, EAA pack, in-toto attestation) and uploads it as a build artifact. The SARIF output integrates with GitHub Code Scanning.

It also works as a CLI, a stdio MCP server for AI agents, and a Vercel API.

Important: it doesn't claim conformance. Automated tools detect ~30–57% of WCAG issues. Every bundle states this. It's evidence, not certification.

I'm looking for feedback from 5 practitioners before broader launch. Would you try it on a project and tell me if the output is something you'd hand to a client?

Repo: https://github.com/Kartik24Hulmukh/AccessDoc

Thanks,
[your name]
