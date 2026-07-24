# PDF/UA Plan (Future Release)

> **Status: PLANNED — not implemented in v0.6.0-beta.1.**
> The current PDF is untagged and not accessible to screen readers.

## Current state

The generated `report.pdf` is produced by `app/reporter.py` using ReportLab's
`SimpleDocTemplate` and `platypus` flowables. The PDF has:

- ❌ No `/StructTreeRoot` (no structure tree)
- ❌ No `/MarkInfo` (not marked as tagged)
- ❌ No `/Lang` (document language not set)
- ⚠️ `/Title` set to `(anonymous)` (not a meaningful title)
- ❌ Tables not tagged as `/Table` structure elements
- ❌ No explicit reading order for assistive technology

This means screen readers (NVDA, JAWS, VoiceOver) cannot navigate the PDF
semantically. They will read it as a flat stream of text without heading
structure, table semantics, or landmark regions.

## Why this matters

AccessDoc is a disability-sector tool. The PDF is the artifact practitioners
hand to clients. An inaccessible PDF from an accessibility tool is a
credibility problem comparable to the HTML self-audit issue fixed in Phase 3.

## Proposed approach: ReportLab tagged PDF

ReportLab supports tagged PDFs via the `pdfbase.pdfmetrics` and structure
element APIs. The approach:

### 1. Enable tagged PDF mode

```python
from reportlab.platypus import SimpleDocTemplate

doc = SimpleDocTemplate(buf, pagesize=A4, ...)
# Enable tagged PDF
doc.canv.setPageCompression(1)
```

### 2. Set document metadata

```python
doc.title = f"WCAG 2.2 Audit Report — {client_name}"
doc.author = f"AccessDoc {VERSION}"
doc.subject = "Automated accessibility audit evidence"
doc.lang = "en"  # Document language
```

### 3. Add structure elements

Wrap each flowable in structure elements:

```python
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle

# Headings become /H1, /H2 structure elements
# Paragraphs become /P
# Tables become /Table with /TR, /TH, /TD children
```

### 4. Tag tables

ReportLab's `Table` flowable needs to be wrapped in a structure element that
declares it as a table, with header cells tagged as `/TH` and data cells as
`/TD`.

### 5. Add accessibility markers

- `/Marked true` in the document catalog
- `/StructTreeRoot` referencing the structure element hierarchy
- `/MarkInfo` dictionary

## Verification

After implementation, verify with:
1. `pac.exe` (PDF Accessibility Checker) — should pass PDF/UA-1 checks
2. NVDA + Adobe Reader — should navigate by heading, read tables semantically
3. axe-core cannot audit PDFs; manual AT testing is required

## Scope for first implementation

- Set document title, author, language
- Tag headings as /H1, /H2
- Tag the summary table and violation table as /Table with /TH, /TD
- Mark the PDF as tagged (/Marked true, /MarkInfo)
- Add alt text for any images (none currently, but future-proof)

## Dependencies

- ReportLab >= 4.0 (already required)
- No new external dependencies
- Manual verification with PAC and NVDA (not automatable in CI)

## Alternative considered: generate PDF from HTML

Generating the PDF from the accessible HTML (via WeasyPrint or similar) would
inherit the HTML's accessibility structure. This was considered and rejected
for the first implementation because:
- WeasyPrint adds a heavy dependency (cairo, pango)
- ReportLab is already the PDF engine and supports tagging natively
- The HTML→PDF path would need separate testing
- ReportLab gives finer control over PDF structure elements

However, if ReportLab's tagging API proves too limited, the HTML→PDF path
should be revisited as it would automatically inherit all HTML accessibility
fixes.
