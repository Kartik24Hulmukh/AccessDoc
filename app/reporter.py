"""PDF report generator using ReportLab."""
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from .models import DISCLAIMER_COMPACT, VERSION
from .catalog import AXE_CORE_VERIFIED_VERSION, CATALOG_VERSION


def generate_pdf_report(summary, violations, client_name="Client", agency_name="Audit Agency", audit_date=""):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle("T", parent=styles["Title"], fontSize=22, spaceAfter=12)
    story.append(Paragraph("WCAG 2.2 Automated Audit Report", title_style))
    story.append(Paragraph(f"Client: <b>{client_name}</b> | Agency: {agency_name} | Date: {audit_date}", styles["Normal"]))
    story.append(Paragraph(f"URL: {summary.url or 'N/A'} | axe-core: {summary.engine_version or AXE_CORE_VERIFIED_VERSION}", styles["Normal"]))
    story.append(Paragraph(f"Catalog: {CATALOG_VERSION} | AccessDoc: {VERSION}", styles["Normal"]))
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
            desc = v.description[:70] + ("..." if len(v.description) > 70 else "")
            vd.append([v.id, v.impact, str(v.nodes), ", ".join(v.wcag_scs) or "-", desc])
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
