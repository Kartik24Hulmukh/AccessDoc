# Self-Accessibility Audit — AccessDoc v0.6.0-beta.1

> An accessibility tool with an inaccessible report is a credibility disaster.
> This document records the before/after results of auditing AccessDoc's own
> HTML and PDF outputs.

## Methodology

1. Created a **stress fixture** (`fixtures/axe-stress.json`) with 65 violations
   across all four impact levels (17 critical, 16 serious, 16 moderate, 16
   minor), long URLs, long CSS selectors, non-ASCII/RTL text, and emoji in the
   client name. All optional sections enabled (SARIF, VPAT, EAA).
2. Generated `report.html`, `vpat-draft.html`, and `report.pdf` from the stress
   fixture using AccessDoc's `build_artifacts()` function.
3. Ran axe-core 4.12.1 against each HTML file via Playwright (headless Chromium)
   at both default viewport and 320px width (WCAG 1.4.10 Reflow).
4. Audited the PDF for PDF/UA tagging, document title, language, and reading
   order.
5. Recorded all violations with impact level.
6. Fixed all violations.
7. Re-ran axe-core to confirm zero violations.
8. Added a permanent regression test (`tests/test_self_audit.py`) pointed at
   the stress fixture.

## HTML audit — BEFORE fix (v0.6.0-beta.1 as shipped)

### report.html (from sample fixture)

| Impact | Rule ID | Description | Nodes |
|--------|---------|-------------|-------|
| moderate | `landmark-one-main` | Ensure the document has a main landmark | 1 |
| moderate | `region` | Ensure all page content is contained by landmarks | 5 |

**Total: 2 violations (0 critical, 0 serious, 2 moderate)**

### vpat-draft.html (from sample fixture)

| Impact | Rule ID | Description | Nodes |
|--------|---------|-------------|-------|
| moderate | `landmark-one-main` | Ensure the document has a main landmark | 1 |
| moderate | `region` | Ensure all page content is contained by landmarks | 6 |

**Total: 2 violations (0 critical, 0 serious, 2 moderate)**

## HTML audit — AFTER fix (stress fixture)

### report.html

| Viewport | Violations | Critical | Serious | Moderate |
|----------|-----------|----------|---------|----------|
| Default | **0** | 0 | 0 | 0 |
| 320px (reflow) | **0** | 0 | 0 | 0 |

### vpat-draft.html

| Viewport | Violations | Critical | Serious | Moderate |
|----------|-----------|----------|---------|----------|
| Default | **0** | 0 | 0 | 0 |
| 320px (reflow) | **0** | 0 | 0 | 0 |

## Bugs found — separated by detection method

### Detected by axe-core

| # | Bug | Impact | Where | Fix |
|---|-----|--------|-------|-----|
| 1 | Missing `<main>` landmark | moderate | report.html, vpat-draft.html | Added `<main>` wrapper |
| 2 | Content outside landmarks | moderate | report.html, vpat-draft.html | Content moved inside `<main>` |

### Proactive improvements (NOT detected by axe-core)

These were not flagged as violations but were fixed as accessibility best
practices:

| # | Improvement | Rationale | Fix |
|---|-------------|-----------|-----|
| 3 | Missing `scope` on `<th>` | WCAG 1.3.1 — table headers should declare scope | Added `scope="col"` |
| 4 | Missing `<thead>`/`<tbody>` | Semantic table structure | Added `<thead>` and `<tbody>` |
| 5 | Missing viewport meta tag | Responsive layout / WCAG 1.4.10 reflow | Added `<meta name="viewport">` |

## PDF audit — currently unaudited by axe-core

The PDF (`report.pdf`) is the artifact practitioners hand to clients. It was
audited manually for PDF/UA compliance:

| Check | Status | Details |
|-------|--------|---------|
| Tagged PDF (PDF/UA) | ❌ NO | No `/StructTreeRoot`, no `/MarkInfo` — PDF is untagged |
| Document title | ⚠️ Poor | Set to `(anonymous)` — not a meaningful title |
| Document language | ❌ NO | `/Lang` not set |
| Table tagging | ❌ NO | Tables are not tagged as `/Table` structure elements |
| Reading order | ⚠️ Implicit | No explicit reading order for assistive technology |

**The PDF is NOT accessible.** It is an untagged PDF that screen readers will
read in implicit order without table structure, headings, or landmarks. This
is a known limitation documented in `docs/THREAT-MODEL.md` and
`docs/pdf-ua-plan.md`.

## Regression test

`tests/test_self_audit.py` generates both HTML outputs from the **stress
fixture** (`fixtures/axe-stress.json`) and runs axe-core against them via
Playwright. It asserts:

- Zero violations at **critical, serious, AND moderate** impact levels
- Zero blocking violations at 320px viewport width (WCAG 1.4.10 reflow)
- `<main>` element present in both outputs
- `scope` attributes present on table headers
- `<thead>` and `<tbody>` present in both outputs

The moderate level is included because the bugs fixed in Phase 3
(landmark-one-main, region) were moderate — asserting only critical/serious
would not catch a regression of those fixes.

If Playwright is not installed, the test prints a **LOUD warning** to stderr
and is skipped. It must not pass silently.

## Honest assessment

The HTML violations found were **moderate** (best-practice), not critical or
serious. No WCAG Level A or AA success criteria were violated in the HTML
outputs. However, an accessibility tool should meet best-practice standards,
not just minimum compliance. The fixes bring AccessDoc's HTML outputs to zero
axe-core violations at all blocking impact levels.

The PDF is a different story: it is **not accessible** (untagged, no language,
no meaningful title). This is a significant gap for a disability-sector tool
and is documented honestly in `docs/pdf-ua-plan.md`.

**Coverage limitation:** axe-core detects ~30-57% of WCAG issues. This audit
only covers what axe-core can detect in HTML. Manual testing (keyboard
navigation, screen reader, etc.) of the HTML outputs has not been performed.
The PDF was audited by inspecting its internal structure, not by testing with
a screen reader.
