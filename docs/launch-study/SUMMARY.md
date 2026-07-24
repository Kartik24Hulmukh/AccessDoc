# AccessDoc v0.6.0-beta.1 — Launch Study

## Methodology

18 public websites were scanned with axe-core 4.12.1 via Playwright (headless Chromium).
For each site, a tamper-evident evidence bundle was generated using AccessDoc v0.6.0-beta.1
with SARIF, VPAT, and EAA exports enabled.

**Coverage limitation:** Automated scanning detects approximately 30–57% of WCAG issues
(Deque Systems 2022). These results document what the scanner found, not what it missed.
This is not a conformance assessment.

## Results

| # | Site | Critical | Serious | Moderate | Minor | Total Violations | Passes | Receipt SHA-256 |
|---|------|----------|---------|----------|-------|-------------------|--------|-----------------|
| 1 | https://linear.app | 1 | 2 | 2 | 0 | 5 | 49 | `8b8b32c4be7a58e0...` |
| 2 | https://raycast.com | 1 | 2 | 2 | 0 | 5 | 38 | `9942d0baaa308142...` |
| 3 | https://cursor.sh | 0 | 3 | 1 | 0 | 4 | 45 | `0bcd00a6074bb3c8...` |
| 4 | https://v0.dev | 1 | 2 | 4 | 0 | 7 | 39 | `db3e00c81f74a52d...` |
| 5 | https://perplexity.ai | — | — | — | — | — | — | CSP blocked |
| 6 | https://notion.so | 0 | 2 | 0 | 0 | 2 | 44 | `997d3cd701f14357...` |
| 7 | https://figma.com | 0 | 0 | 0 | 0 | 0 | 43 | `0cef684f6d531df0...` |
| 8 | https://vercel.com | 0 | 0 | 1 | 0 | 1 | 43 | `015bd7983f79b01d...` |
| 9 | https://www.gov.uk | — | — | — | — | — | — | CSP blocked |
| 10 | https://www.usa.gov | 0 | 0 | 3 | 0 | 3 | 44 | `767d02405bf8b2a5...` |
| 11 | https://www.canada.ca | 0 | 0 | 0 | 0 | 0 | 22 | `74d3e4e5205f46ec...` |
| 12 | https://www.australia.gov.au | 2 | 0 | 1 | 0 | 3 | 43 | `711a581e4740492d...` |
| 13 | https://www.nih.gov | 0 | 1 | 2 | 0 | 3 | 44 | `7ef4a0bf611322cb...` |
| 14 | https://www.nasa.gov | 0 | 0 | 1 | 0 | 1 | 43 | `855b56fe97d5247c...` |
| 15 | https://www.wikipedia.org | 0 | 0 | 0 | 0 | 0 | 44 | `7ed8ef05d7e9e7dd...` |
| 16 | https://news.ycombinator.com | 2 | 2 | 3 | 0 | 7 | 18 | `d5897478e9f386e1...` |
| 17 | https://www.mozilla.org | 0 | 1 | 0 | 0 | 1 | 38 | `c096ffb865cb6d7c...` |
| 18 | https://www.w3.org | 0 | 0 | 0 | 0 | 0 | 42 | `6240c863774f28f5...` |

## Summary statistics

- Sites scanned: 16/18
- Sites blocked by CSP: 2 (perplexity.ai, gov.uk — CSP prevents inline script injection)
- Total violations across scanned sites: 42
- Average violations per site: 2.6
- Total critical: 7
- Total serious: 15
- Cleanest site: https://figma.com (0 violations)
- Most violations: https://v0.dev (7 violations)

## Artifacts

Each successfully scanned site has:
- `axe-NN.json` — raw axe-core output
- `bundle-NN.zip` — tamper-evident evidence bundle (PDF, HTML, OpenACR, SARIF, VPAT, EAA, in-toto)

## CSP limitation

Two sites (perplexity.ai, gov.uk) blocked axe-core injection via Content Security Policy.
This is a known limitation of client-side scanning. For production use, axe-core should be
run via a browser extension or a testing framework that can bypass CSP (e.g., Playwright with
`--disable-web-security` or Cypress with `cy.injectAxe`).

## Disclaimer

This study is for demonstration purposes only. It is not legal advice and not a
conformance assessment. Automated tools detect ~30–57% of WCAG issues; manual and
assistive-technology testing is required for a conformance claim.
