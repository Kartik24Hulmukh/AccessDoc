# Self-Accessibility Audit — AccessDoc v0.6.0-beta.1

> An accessibility tool with an inaccessible report is a credibility disaster.
> This document records the before/after results of auditing AccessDoc's own
> HTML outputs with axe-core.

## Methodology

1. Generated `report.html` and `vpat-draft.html` from `fixtures/axe-sample.json`
   using AccessDoc's `build_artifacts()` function.
2. Ran axe-core 4.12.1 against each HTML file via Playwright (headless Chromium).
3. Recorded all violations with impact level.
4. Fixed all violations.
5. Re-ran axe-core to confirm zero violations.
6. Added a permanent regression test (`tests/test_self_audit.py`).

## BEFORE fix (v0.6.0-beta.1 as shipped)

### report.html

| Impact | Rule ID | Description | Nodes |
|--------|---------|-------------|-------|
| moderate | `landmark-one-main` | Ensure the document has a main landmark | 1 |
| moderate | `region` | Ensure all page content is contained by landmarks | 5 |

**Total: 2 violations (0 critical, 0 serious, 2 moderate)**

### vpat-draft.html

| Impact | Rule ID | Description | Nodes |
|--------|---------|-------------|-------|
| moderate | `landmark-one-main` | Ensure the document has a main landmark | 1 |
| moderate | `region` | Ensure all page content is contained by landmarks | 6 |

**Total: 2 violations (0 critical, 0 serious, 2 moderate)**

### Root causes

1. **Missing `<main>` landmark**: Both HTML templates wrapped content directly
   in `<body>` without a `<main>` element. axe-core's `landmark-one-main` rule
   (best practice) flags this.
2. **Content outside landmarks**: All content (headings, paragraphs, tables)
   was outside any landmark region. The `region` rule flags content that is
   not contained by a landmark.
3. **Missing `scope` on `<th>`**: Table headers did not have `scope="col"`
   attributes. While axe-core did not flag this as a violation (it's a
   best-practice recommendation, not a rule), it was fixed as a proactive
   accessibility improvement.
4. **Missing `<thead>`/`<tbody>`**: Tables used a bare `<tr>` for headers
   without semantic grouping. Fixed for correctness.

## AFTER fix

### report.html

**0 violations** ✅

### vpat-draft.html

**0 violations** ✅

### Changes made

**`app/service.py` — `_build_html()`:**
- Added `<main>` wrapper around all body content
- Added `<thead>` and `<tbody>` around table header and data rows
- Added `scope='col'` to all `<th>` elements
- Added `<meta name='viewport'>` for responsive layout

**`app/vpat.py` — `generate_vpat_html()`:**
- Added `<main>` wrapper around all body content
- Added `<thead>` and `<tbody>` around table header and data rows
- Added `scope="col"` to all `<th>` elements
- Added `<meta name='viewport'>` for responsive layout

## Regression test

`tests/test_self_audit.py` generates both HTML outputs from the sample fixture
and runs axe-core against them via Playwright. It asserts:

- Zero critical/serious violations in report.html
- Zero critical/serious violations in vpat-draft.html
- `<main>` element present in both outputs
- `scope` attributes present on table headers

This test is skipped if Playwright is not installed but **should be run in CI**.

## Honest assessment

The violations found were **moderate** (best-practice), not critical or serious.
No WCAG Level A or AA success criteria were violated. However, an accessibility
tool should meet best-practice standards, not just minimum compliance. The fixes
bring AccessDoc's own outputs to zero axe-core violations.

**Coverage limitation:** axe-core detects ~30-57% of WCAG issues. This audit
only covers what axe-core can detect. Manual testing (keyboard navigation,
screen reader, etc.) of the HTML outputs has not been performed and is
recommended before claiming the outputs are fully accessible.
