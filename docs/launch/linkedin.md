# LinkedIn Post — Compliance Angle

**Draft (do not post until trademark check is resolved):**

---

Accessibility audits have a trust problem.

When a vendor says "we passed an accessibility scan," what does that actually mean? Which tool? Which version? What did it check? What did it miss? And can you verify the report hasn't been edited after the fact?

AccessDoc v0.6.0-beta.1 addresses this by turning axe-core scan output into a **tamper-evident evidence bundle** — not a conformance certificate, but a verifiable record of what was actually found.

Each bundle includes:
📄 A PDF report + accessible HTML
📋 An EN 301 549-mapped OpenACR YAML (EU procurement format)
🔍 SARIF 2.1.0 for GitHub Code Scanning
📝 A VPAT draft (clearly marked DRAFT)
🇪🇺 An EAA evidence pack (European Accessibility Act)
🔐 An in-toto attestation with SHA-256 digests covering every file

The important part: it explicitly states its limitations. Automated tools detect approximately 30–57% of WCAG issues (Deque Systems 2022). Every bundle says so. The VPAT draft says "DRAFT — NOT A CERTIFIED VPAT." No conformance claims.

This is for teams who need to document their accessibility effort with the same rigor they apply to security — chain of custody, tamper detection, provenance labels on every finding.

Available as a CLI, MCP server, GitHub Action, and API.

#Accessibility #WCAG #Compliance #EN301549 #EAA #SARIF #DevTools

---
*Note: This draft observes the banned-words list. No "100x", "revolutionary", "guaranteed", "fully compliant", or "certified" claims.*
