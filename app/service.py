from __future__ import annotations
import base64, hashlib, json, re, struct
from dataclasses import dataclass
from datetime import date
from pathlib import PurePath
from typing import Any
from .catalog import CATALOG_VERSION
from .html_report import generate_html
from .models import AuditRequest, Branding
from .parser import ParseError, parse_input
from .reporter import generate_pdf

VERSION = "0.4.0-beta.4"
MAX_BODY = 2_700_000
MAX_BUNDLE_BYTES = 4_000_000
MAX_LOGO_ENCODED = 670_000
MAX_LOGO_BYTES = 500_000
MAX_PNG_DIMENSION = 4096
MAX_PNG_PIXELS = 16_000_000

@dataclass(frozen=True)
class Artifacts:
    request: AuditRequest
    pdf: bytes
    html: bytes
    receipt: dict[str, Any]
    receipt_bytes: bytes
    summary: dict[str, Any]

def safe_source_filename(value: Any) -> str:
    name=PurePath(str(value or 'pasted-evidence').replace('\\','/')).name
    name=re.sub(r'[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]','',name).strip()
    return name[:120] or 'pasted-evidence'

def decode_logo(data_url: Any) -> bytes | None:
    value=str(data_url or '')
    if not value:return None
    if not value.startswith('data:image/png;base64,'):raise ValueError('Logo must be a PNG')
    encoded=value.split(',',1)[1]
    if len(encoded)>MAX_LOGO_ENCODED:raise ValueError('Logo exceeds encoded size limit')
    try:logo=base64.b64decode(encoded,validate=True)
    except Exception as exc:raise ValueError('Logo must contain valid base64') from exc
    if len(logo)>MAX_LOGO_BYTES:raise ValueError('Logo exceeds 500 KB')
    if len(logo)<24 or logo[:8]!=b'\x89PNG\r\n\x1a\n' or logo[12:16]!=b'IHDR':raise ValueError('Logo must be a valid PNG')
    width,height=struct.unpack('>II',logo[16:24])
    if width<1 or height<1 or width>MAX_PNG_DIMENSION or height>MAX_PNG_DIMENSION or width*height>MAX_PNG_PIXELS:raise ValueError('Logo dimensions exceed limit')
    return logo

def build_artifacts(body: dict[str, Any]) -> Artifacts:
    if not isinstance(body,dict):raise ValueError('JSON body must be an object')
    scanner=body.get('scanner_input','')
    if not isinstance(scanner,str):raise ValueError('scanner_input must be text')
    if not scanner.strip():raise ValueError('Paste or upload scanner evidence')
    manual=body.get('manual_findings','')
    if not isinstance(manual,str):raise ValueError('manual_findings must be text')
    audit_date=str(body.get('audit_date',''))
    if audit_date:
        try:date.fromisoformat(audit_date)
        except ValueError as exc:raise ValueError('audit_date must use YYYY-MM-DD') from exc
    findings,detected=parse_input(scanner,str(body.get('format_hint','auto')))
    logo=decode_logo(body.get('logo_data_url',''))
    branding=Branding(body.get('agency_name','AccessDoc Studio'),body.get('primary_color','#185ABD'),logo)
    input_sha256=hashlib.sha256(scanner.encode('utf-8')).hexdigest()
    req=AuditRequest(body.get('client_name','Client'),audit_date,branding,findings,manual,detected,safe_source_filename(body.get('source_filename')),input_sha256,VERSION)
    pdf=generate_pdf(req)
    counts={s:sum(1 for f in findings if f.severity==s) for s in ('critical','high','medium','low','needs-review')}
    unmapped=sum(1 for f in findings if f.wcag_criterion=='Unmapped')
    receipt={
        'schema_version':'1.0',
        'source_filename':req.source_filename,
        'submitted_text_sha256':input_sha256,
        'detected_format':detected,
        'generator_version':req.generator_version,
        'catalog_version':CATALOG_VERSION,
        'mapped_findings':len(findings)-unmapped,
        'unmapped_findings':unmapped,
        'manual_findings_included':bool(req.manual_findings),
        'pdf_sha256':hashlib.sha256(pdf).hexdigest(),
        'scope_statement':'Digest identifies submitted UTF-8 input text; AccessDoc normalized supplied evidence and did not rescan or authenticate its source.'
    }
    html=generate_html(req,receipt)
    receipt_bytes=(json.dumps(receipt,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
    summary={'detected_format':detected,'finding_count':len(findings),'instance_count':sum(f.instance_count for f in findings),'severity_counts':counts,'catalog_review_required':unmapped,'input_evidence_receipt':receipt}
    return Artifacts(req,pdf,html,receipt,receipt_bytes,summary)
