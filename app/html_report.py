from __future__ import annotations
from html import escape
import hashlib,re
from .models import AuditRequest, DISCLAIMER
from .catalog import CATALOG_VERSION
REPORT_CSS="""body{max-width:72rem;margin:auto;padding:1rem;font:1rem/1.6 system-ui,sans-serif;color:#171717}a:focus{outline:3px solid #185abd;outline-offset:3px}header,section,article{margin-block:2rem}article{border-top:2px solid #ddd;padding-top:1rem}dt{font-weight:700}dd{margin:0 0 1rem}code{overflow-wrap:anywhere}*,*::before,*::after{box-sizing:border-box;min-width:0}p,li,dd,dt,h1,h2,h3,a{overflow-wrap:anywhere;word-break:break-word}dl{max-width:100%}@media(max-width:20rem){body{padding:.5rem}}@media print{a[href=\"#main\"]{display:none}}"""
def fragment_id(f)->str:
    basis='\x1f'.join((f.source,f.source_rule_id,f.finding_id))
    slug=re.sub(r'[^a-z0-9]+','-',f.source_rule_id.lower()).strip('-')[:32] or 'finding'
    return f'finding-{slug}-{hashlib.sha256(basis.encode()).hexdigest()[:12]}'
def generate_html(req:AuditRequest,receipt:dict)->bytes:
    findings=sorted(req.findings,key=lambda f:(f.severity,f.level,-f.instance_count,f.title.lower()))
    items=[]
    for f in findings:
        fid=fragment_id(f);display_id=escape(f.finding_id or f.source_rule_id)
        occ=''.join(f'<li>{escape(o.failure_summary or o.selector or o.html)}</li>' for o in f.occurrences[:3] if (o.failure_summary or o.selector or o.html))
        items.append(f"""<article id="{fid}"><h3>{escape(f.title)}</h3><dl><dt>Report-local finding ID</dt><dd>{display_id}</dd><dt>Source</dt><dd>{escape(f.source)} / {escape(f.source_rule_id)}</dd><dt>Severity</dt><dd>{escape(f.severity)}</dd><dt>WCAG evidence mapping</dt><dd>{escape(f.wcag_criterion)} {escape(f.wcag_title)} — level {escape(f.level)}</dd><dt>User impact</dt><dd>{escape(f.user_impact)}</dd><dt>Remediation guidance</dt><dd>{escape(f.remediation)}</dd><dt>Review state</dt><dd>{escape(f.review_state)}</dd></dl>{('<h4>Representative evidence</h4><ul>'+occ+'</ul>') if occ else ''}</article>""")
    receipt_rows=''.join(f'<dt>{escape(str(k).replace("_"," ").title())}</dt><dd>{escape(str(v).lower() if isinstance(v,bool) else str(v))}</dd>' for k,v in receipt.items())
    manual=f'<section><h2>Manual findings supplied by evaluator</h2><p>{escape(req.manual_findings)}</p></section>' if req.manual_findings else ''
    doc=f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"><title>Accessibility evidence report — {escape(req.client_name)}</title><style>{REPORT_CSS}</style></head><body><a href="#main">Skip to report</a><header><p>{escape(req.branding.agency_name)}</p><h1>Accessibility evidence report — {escape(req.client_name)}</h1><p>Source format: {escape(req.source_format)} · Catalog: {escape(CATALOG_VERSION)}</p></header><main id="main"><section aria-labelledby="limitations"><h2 id="limitations">Important limitations</h2><p>{escape(DISCLAIMER)}</p><p>This HTML companion is generated from the same normalized report object as the PDF. It is a beta companion, not a claim of WCAG conformance.</p></section><section aria-labelledby="receipt"><h2 id="receipt">Input evidence receipt</h2><p>This receipt identifies the submitted input text processed by this report. It does not authenticate the source or verify accuracy or completeness.</p><dl>{receipt_rows}</dl></section><section aria-labelledby="findings"><h2 id="findings">Detailed findings</h2>{''.join(items) or '<p>No finding groups were supplied.</p>'}</section>{manual}</main><footer><p>Generated from supplied evidence; not a rescan, certification, legal opinion, or complete accessibility evaluation.</p></footer></body></html>"""
    return doc.encode('utf-8')
