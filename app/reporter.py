"""PDF report generator using ReportLab.

SECURITY: every user-controlled value rendered into a Paragraph or PDF
metadata field passes through safe_text() (app/safe_text.py) so hostile
input can never inject active ReportLab markup (<font>, <b>, <a>, <img>,
entities, control characters, etc).
"""
from io import BytesIO

# Reproducibility: ReportLab stamps /CreationDate, /ModDate and two /ID md5s
# derived from the current time. invariant=1 pins all of them so identical
# input yields byte-identical PDF output. This MUST be set before any
# reportlab canvas/doc object is constructed.
import reportlab.rl_config
reportlab.rl_config.invariant = 1
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from .models import DISCLAIMER_COMPACT, VERSION
from .catalog import CATALOG_VERSION
from .safe_text import safe_text


def build_pdf_title(client_name="", audit_date=""):
    """Build a meaningful PDF /Title with NO empty interpolation.

    Phase 3.2 shipped "Accessibility Evidence Report - - " because the client
    and date were blank and the separators were emitted unconditionally. Only
    non-empty parts are joined, so the title degrades gracefully instead of
    looking like a broken template.

    All values are safe_text()-escaped and control-character safe.
    """
    parts = ["Accessibility Evidence Report"]
    c = safe_text((client_name or "").strip())
    d = safe_text((audit_date or "").strip())
    if c and c.lower() != "client":
        parts.append(c)
    if d:
        parts.append(d)
    return " - ".join(parts)


def display_engine_version(engine_version):
    """Keep absent scanner provenance unknown; never substitute catalog data."""
    value = safe_text(engine_version).strip()
    return value or "unknown / not supplied"


def generate_pdf_report(summary, violations, client_name="Client", agency_name="Audit Agency", audit_date=""):
    # All user-controlled values are sanitized before reaching ReportLab.
    s_client = safe_text(client_name)
    s_agency = safe_text(agency_name)
    s_date = safe_text(audit_date)
    s_url = safe_text(summary.url)
    s_engine = display_engine_version(summary.engine_version)

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm,
                            title=build_pdf_title(s_client, s_date),
                            author=safe_text(f"AccessDoc {VERSION}"),
                            subject=safe_text(
                                "Automated WCAG 2.2 accessibility audit evidence "
                                "(DRAFT - automated coverage only)"
                            ),
                            lang="en")
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle("T", parent=styles["Title"], fontSize=22, spaceAfter=12)
    story.append(Paragraph("WCAG 2.2 Automated Audit Report", title_style))
    story.append(Paragraph(
        f"Client: <b>{s_client}</b> | Agency: {s_agency} | Date: {s_date}",
        styles["Normal"],
    ))
    story.append(Paragraph(
        f"URL: {s_url or 'N/A'} | axe-core: {s_engine}",
        styles["Normal"],
    ))
    story.append(Paragraph(
        f"Catalog: {CATALOG_VERSION} | AccessDoc: {VERSION}",
        styles["Normal"],
    ))
    story.append(Spacer(1, 0.3*cm))
    story.append(HRFlowable(width="100%"))

    disc_style = ParagraphStyle("D", parent=styles["Normal"], fontSize=8, textColor=colors.grey)
    story.append(Paragraph(DISCLAIMER_COMPACT, disc_style))
    story.append(Spacer(1, 0.4*cm))

    summary_data = [
        ["Critical", "Serious", "Moderate", "Minor", "Total", "Passes"],
        [str(summary.critical), str(summary.serious), str(summary.moderate),
         str(summary.minor), str(summary.total_violations), str(summary.total_passes)],
    ]
    t = Table(summary_data, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#2C3E50")),
        ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
        ("FONTSIZE",   (0,0), (-1,-1), 9),
        ("GRID",       (0,0), (-1,-1), 0.5, colors.grey),
        ("ALIGN",      (0,0), (-1,-1), "CENTER"),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.6*cm))

    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=13)
    story.append(Paragraph("Coverage & Methodology", h2))
    story.append(Paragraph(
        "Automated scanning with axe-core detects approximately <b>30-57%</b> of WCAG issues "
        "(Deque Systems 2022; GDS 2017). Manual testing is required for full compliance.",
        styles["Normal"]
    ))
    story.append(Spacer(1, 0.4*cm))
    story.append(Paragraph("Violation Detail", h2))

    if not violations:
        story.append(Paragraph("No violations detected.", styles["Normal"]))
    else:
        vd = [["Rule ID", "Impact", "Nodes", "WCAG SC", "Description"]]
        order = {"critical":0,"serious":1,"moderate":2,"minor":3}
        for v in sorted(violations, key=lambda x: order.get(x.impact, 4)):
            s_id = safe_text(v.id)
            s_impact = safe_text(v.impact)
            s_desc_full = safe_text(v.description)
            s_desc = s_desc_full[:70] + ("..." if len(s_desc_full) > 70 else "")
            s_wcag = safe_text(", ".join(v.wcag_scs) or "-")
            s_source = safe_text(v.source)
            # Combine WCAG SC and source label for the table cell.
            wcag_cell = s_wcag
            if s_source and s_source != "automated":
                wcag_cell = f"{s_wcag} [{s_source}]"
            vd.append([s_id, s_impact, str(v.nodes), wcag_cell, s_desc])
        vt = Table(vd, colWidths=[3.5*cm, 2*cm, 1.5*cm, 2.5*cm, None])
        vt.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#2C3E50")),
            ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
            ("FONTSIZE",   (0,0), (-1,-1), 8),
            ("GRID",       (0,0), (-1,-1), 0.4, colors.lightgrey),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F5F5F5")]),
        ]))
        story.append(vt)

    doc.build(story)
    return buf.getvalue()
