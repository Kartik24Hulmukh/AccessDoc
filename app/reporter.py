from __future__ import annotations
from io import BytesIO
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle, KeepTogether, Image
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from .models import AuditRequest, DISCLAIMER
from .catalog import CATALOG_VERSION

LEVEL_RANK={"A":0,"AA":1,"AAA":2,"N/A":3}
SEV_RANK={"critical":0,"high":1,"medium":2,"low":3,"needs-review":4}

def _hex(value):
    return colors.HexColor(value)

def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica",7)
    canvas.setFillColor(colors.HexColor("#555555"))
    text="Supplied evidence only — not a rescan, certification, legal opinion, or complete evaluation"
    canvas.drawString(18*mm,10*mm,text)
    canvas.drawRightString(192*mm,10*mm,f"Page {doc.page}")
    canvas.restoreState()

def generate_pdf(req: AuditRequest) -> bytes:
    buf=BytesIO()
    accent=_hex(req.branding.primary_color)
    doc=SimpleDocTemplate(buf,pagesize=A4,rightMargin=18*mm,leftMargin=18*mm,topMargin=18*mm,bottomMargin=20*mm,title=f"Accessibility Evidence Report — {req.client_name}",author=req.branding.agency_name,subject="Accessibility evidence report from supplied scanner output",invariant=1)
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Cover",parent=styles["Title"],fontName="Helvetica-Bold",fontSize=26,leading=31,textColor=accent,spaceAfter=16))
    styles.add(ParagraphStyle(name="H1x",parent=styles["Heading1"],fontName="Helvetica-Bold",fontSize=18,leading=23,textColor=accent,spaceBefore=10,spaceAfter=10))
    styles.add(ParagraphStyle(name="H2x",parent=styles["Heading2"],fontName="Helvetica-Bold",fontSize=13,leading=17,textColor=colors.HexColor("#252525"),spaceBefore=8,spaceAfter=6))
    styles.add(ParagraphStyle(name="Bodyx",parent=styles["BodyText"],fontName="Helvetica",fontSize=9.5,leading=14,textColor=colors.HexColor("#252525"),spaceAfter=7))
    styles.add(ParagraphStyle(name="Smallx",parent=styles["BodyText"],fontName="Helvetica",fontSize=8,leading=11,textColor=colors.HexColor("#555555")))
    styles.add(ParagraphStyle(name="Centerx",parent=styles["Bodyx"],alignment=TA_CENTER))
    story=[]
    if req.branding.logo_png:
        try:
            story += [Image(BytesIO(req.branding.logo_png),width=36*mm,height=18*mm,kind="proportional"),Spacer(1,10*mm)]
        except Exception: pass
    story += [Spacer(1,22*mm),Paragraph(escape(req.branding.agency_name),styles["H2x"]),Paragraph("Accessibility Evidence Report",styles["Cover"]),Paragraph("Evidence report — not a complete accessibility evaluation",styles["Bodyx"]),Paragraph(escape(req.client_name),styles["H1x"]),Spacer(1,8*mm),Paragraph(f"Assessment date: {escape(req.audit_date)}",styles["Bodyx"]),Paragraph(f"Source format: {escape(req.source_format)}",styles["Bodyx"]),Paragraph(f"Catalog: {escape(CATALOG_VERSION)}",styles["Smallx"]),Spacer(1,35*mm),Paragraph("Evidence-based report from supplied scanner output and recorded manual findings.",styles["Centerx"]),PageBreak()]
    story += [Paragraph("Important limitations",styles["H1x"]),Paragraph(escape(DISCLAIMER),styles["Bodyx"]),Spacer(1,8*mm),Paragraph("Required human evaluation",styles["H2x"]),Paragraph("Review keyboard interaction and focus order; screen-reader output; zoom and reflow; alternative-text quality; captions and media alternatives; form errors; status messages; authenticated and dynamic user flows; and representative assistive-technology combinations.",styles["Bodyx"]),PageBreak()]
    findings=sorted(req.findings,key=lambda f:(SEV_RANK.get(f.severity,9),LEVEL_RANK.get(f.level,9),-f.instance_count,f.title.lower()))
    total=len(findings); instances=sum(f.instance_count for f in findings)
    counts={x:sum(1 for f in findings if f.severity==x) for x in SEV_RANK}
    story += [Paragraph("Executive summary",styles["H1x"]),Paragraph(f"The supplied evidence produced <b>{total}</b> finding groups across <b>{instances}</b> recorded instances. Findings remain unreviewed until a qualified evaluator confirms the evidence and scope.",styles["Bodyx"])]
    summary=[["Severity","Finding groups"],["Critical",counts["critical"]],["High",counts["high"]],["Medium",counts["medium"]],["Low",counts["low"]],["Needs review",counts["needs-review"]]]
    t=Table(summary,colWidths=[75*mm,45*mm],repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),accent),("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("GRID",(0,0),(-1,-1),0.5,colors.HexColor("#D7D7D7")),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#F6F7F9")]),("LEFTPADDING",(0,0),(-1,-1),7),("RIGHTPADDING",(0,0),(-1,-1),7),("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6)]))
    story += [t,Spacer(1,8*mm),Paragraph("Prioritized findings",styles["H2x"])]
    rows=[["Priority","Criterion","Finding","Instances","Effort"]]
    for i,f in enumerate(findings,1): rows.append([str(i),f"{f.wcag_criterion} ({f.level})",Paragraph(escape(f.title),styles["Smallx"]),str(f.instance_count),f.effort])
    pt=Table(rows,colWidths=[14*mm,35*mm,82*mm,22*mm,18*mm],repeatRows=1)
    pt.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),accent),("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),7.5),("VALIGN",(0,0),(-1,-1),"TOP"),("GRID",(0,0),(-1,-1),0.35,colors.HexColor("#D7D7D7")),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#F6F7F9")]),("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
    story += [pt,PageBreak(),Paragraph("Detailed findings",styles["H1x"])]
    for i,f in enumerate(findings,1):
        criterion = f"{escape(f.wcag_criterion)} {escape(f.wcag_title)} — Level {escape(f.level)}" if f.wcag_criterion!="Unmapped" else "Unmapped — manual review required"
        block=[Paragraph(f"{i}. {escape(f.title)}",styles["H2x"]),Paragraph(f"<b>Source:</b> {escape(f.source)} / {escape(f.source_rule_id)} &nbsp; <b>Severity:</b> {escape(f.severity.title())} &nbsp; <b>Effort:</b> {escape(f.effort)}",styles["Smallx"]),Paragraph(f"<b>WCAG evidence mapping:</b> {criterion}",styles["Bodyx"]),Paragraph(f"<b>User impact:</b> {escape(f.user_impact)}",styles["Bodyx"]),Paragraph(f"<b>Remediation guidance:</b> {escape(f.remediation)}",styles["Bodyx"]),Paragraph(f"<b>Review state:</b> {escape(f.review_state.replace('_',' '))}. Mapping basis: {escape(f.mapping_basis.replace('_',' '))}.",styles["Smallx"])]
        if f.occurrences:
            evidence=[]
            for o in f.occurrences[:3]:
                txt=o.failure_summary or o.selector or o.html
                if txt: evidence.append("• "+escape(txt[:650]))
            if evidence: block += [Paragraph("<b>Representative evidence:</b><br/>"+"<br/>".join(evidence),styles["Smallx"])]
        story += [KeepTogether(block),Spacer(1,5*mm)]
    if req.manual_findings:
        story += [PageBreak(),Paragraph("Manual findings supplied by evaluator",styles["H1x"]),Paragraph(escape(req.manual_findings).replace("\n","<br/>"),styles["Bodyx"]),Paragraph("Manual findings require evaluator-confirmed WCAG mappings, severity, evidence, and retest criteria before client delivery.",styles["Smallx"])]
    mapped=sum(1 for f in findings if f.wcag_criterion!="Unmapped")
    unmapped=total-mapped
    receipt=(f"Source filename: {escape(req.source_filename)}.<br/>Input SHA-256: {escape(req.input_sha256)}.<br/>"
             f"Detected format: {escape(req.source_format)}. Generator: {escape(req.generator_version)}. Catalog: {escape(CATALOG_VERSION)}.<br/>"
             f"Finding groups: {total}; mapped: {mapped}; unmapped: {unmapped}; manual findings included: {'yes' if req.manual_findings else 'no'}.<br/>"
             f"Assessment date: {escape(req.audit_date)}. Source evidence was normalized, not rescanned.")
    story += [PageBreak(),Paragraph("Input evidence receipt",styles["H1x"]),Paragraph(receipt,styles["Bodyx"]),Paragraph("This receipt identifies submitted input text; it does not authenticate the source or verify accuracy or completeness. Unknown source rules were not assigned guessed criteria and remain labeled for manual review.",styles["Bodyx"]),Paragraph(escape(DISCLAIMER),styles["Smallx"])]
    doc.build(story,onFirstPage=_footer,onLaterPages=_footer)
    data=buf.getvalue()
    if len(data)<1000 or not data.startswith(b"%PDF-"): raise RuntimeError("PDF integrity check failed")
    return data
