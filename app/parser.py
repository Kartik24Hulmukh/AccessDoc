from __future__ import annotations
import csv, io, json, re, hashlib
from html.parser import HTMLParser
from typing import Any
from .models import Finding, Occurrence, clean_text
from .catalog import lookup, IMPACT_TO_SEVERITY

MAX_INPUT = 2_000_000
MAX_DEPTH = 24
MAX_FINDINGS = 200
MAX_NODES = 500

class ParseError(ValueError): pass

def _depth(obj: Any, n=0) -> int:
    if n > MAX_DEPTH: raise ParseError("Input is nested too deeply")
    if isinstance(obj, dict):
        for v in obj.values(): _depth(v,n+1)
    elif isinstance(obj,list):
        for v in obj[:MAX_NODES+1]: _depth(v,n+1)
    return n

def _json(text: str):
    if len(text.encode("utf-8",errors="ignore")) > MAX_INPUT: raise ParseError("Input exceeds 2 MB")
    try: obj=json.loads(text)
    except json.JSONDecodeError as e: raise ParseError(f"Invalid JSON near line {e.lineno}, column {e.colno}")
    _depth(obj)
    return obj

def _id(source, rule, title, index):
    return hashlib.sha256(f"{source}|{rule}|{title}|{index}".encode()).hexdigest()[:16]

def _finding(source, rule, title, description, impact, nodes, index):
    m=lookup(rule)
    mapped = m["sc"] != "Unmapped"
    occ=[]
    for node in (nodes or [])[:MAX_NODES]:
        if isinstance(node,dict):
            target=node.get("target","")
            if isinstance(target,list): target=" > ".join(map(str,target))
            occ.append(Occurrence(html=node.get("html",""), selector=target, failure_summary=node.get("failureSummary",node.get("failure_summary","")), page_url=node.get("url","")))
        else: occ.append(Occurrence(failure_summary=str(node)))
    severity=IMPACT_TO_SEVERITY.get(str(impact).lower() if impact is not None else None,"needs-review")
    return Finding(_id(source,rule,title,index),source,rule,clean_text(title,300) or rule,clean_text(description,4000),m["sc"],m["title"],m["level"],severity,m["effort"],m["impact"],m["remediation"],occ, mapping_basis="curated_rule_map" if mapped else "unmapped_review_required", confidence="automated" if mapped else "needs_review", normative_url=m["normative_url"])

def parse_axe(obj: Any) -> list[Finding]:
    if not isinstance(obj,dict) or not isinstance(obj.get("violations"),list): raise ParseError("Not recognized as axe-core JSON: missing violations array")
    out=[]
    for i,v in enumerate(obj["violations"][:MAX_FINDINGS]):
        if not isinstance(v,dict): continue
        out.append(_finding("axe",v.get("id","unknown"),v.get("help") or v.get("id","Finding"),v.get("description","") or v.get("help","") ,v.get("impact"),v.get("nodes",[]),i))
    return out

def parse_lighthouse(obj: Any) -> list[Finding]:
    root=obj.get("lhr",obj) if isinstance(obj,dict) else {}
    audits=root.get("audits") if isinstance(root,dict) else None
    if not isinstance(audits,dict): raise ParseError("Not recognized as Lighthouse JSON: missing audits object")
    out=[]
    for key,a in audits.items():
        if len(out)>=MAX_FINDINGS: break
        if not isinstance(a,dict) or a.get("score") not in (0,0.0): continue
        details=a.get("details") or {}; items=details.get("items",[]) if isinstance(details,dict) else []
        nodes=[]
        for item in items[:MAX_NODES]:
            node=item.get("node",item) if isinstance(item,dict) else {}
            if isinstance(node,dict): nodes.append({"html":node.get("snippet",node.get("html","")),"target":node.get("selector",node.get("path","")),"failureSummary":node.get("explanation","")})
        rule=a.get("id",key)
        out.append(_finding("lighthouse",rule,a.get("title",rule),a.get("description",""),"moderate",nodes,len(out)))
    if not out: raise ParseError("No failing accessibility audits found in Lighthouse JSON")
    return out

def parse_wave_json(obj: Any) -> list[Finding]:
    if not isinstance(obj,dict): raise ParseError("Not recognized as WAVE JSON")
    categories=obj.get("categories",obj)
    out=[]
    for cat_name,cat in categories.items() if isinstance(categories,dict) else []:
        items=cat.get("items",cat) if isinstance(cat,dict) else []
        if isinstance(items,dict): items=list(items.values())
        if not isinstance(items,list): continue
        for item in items:
            if len(out)>=MAX_FINDINGS: break
            if not isinstance(item,dict): continue
            rule=str(item.get("id",item.get("type",cat_name))).lower().replace("_","-")
            out.append(_finding("wave",rule,item.get("name",item.get("title",rule)),item.get("description",item.get("text","")),item.get("impact","moderate"),item.get("nodes",item.get("items",[])),len(out)))
    if not out: raise ParseError("No WAVE findings recognized")
    return out

def parse_csv_text(text: str) -> list[Finding]:
    try: rows=list(csv.DictReader(io.StringIO(text)))
    except Exception as e: raise ParseError(f"Invalid CSV: {e}")
    if not rows: raise ParseError("CSV has no data rows")
    out=[]
    for row in rows[:MAX_FINDINGS]:
        low={str(k).lower().strip():v for k,v in row.items() if k}
        rule=low.get("rule") or low.get("rule id") or low.get("id") or "manual-review"
        out.append(_finding("wave-csv",rule,low.get("title") or low.get("name") or rule,low.get("description") or low.get("message") or "Imported WAVE CSV finding",low.get("impact") or "moderate",[{"html":low.get("html",""),"target":low.get("selector",low.get("xpath","")),"failureSummary":low.get("failure summary","")}],len(out)))
    return out

def parse_text(text: str) -> list[Finding]:
    lines=[clean_text(x,1200) for x in text.splitlines() if clean_text(x,1200)]
    if not lines: raise ParseError("No scanner findings found")
    out=[]
    for i,line in enumerate(lines[:MAX_FINDINGS]):
        title=line[:120]
        out.append(_finding("text","manual-review",title,line,None,[],i))
    return out

def parse_input(text: str, hint: str="auto") -> tuple[list[Finding],str]:
    if not isinstance(text,str): raise ParseError("Input must be text")
    if len(text.encode("utf-8",errors="ignore")) > MAX_INPUT: raise ParseError("Input exceeds 2 MB")
    h=(hint or "auto").lower()
    if h in ("csv","wave-csv"): return parse_csv_text(text),"wave-csv"
    if h=="text": return parse_text(text),"text"
    try: obj=_json(text)
    except ParseError:
        if h in ("axe","lighthouse","wave"): raise
        if "," in text and "\n" in text:
            try: return parse_csv_text(text),"wave-csv"
            except ParseError: pass
        return parse_text(text),"text"
    parsers = [("axe",parse_axe),("lighthouse",parse_lighthouse),("wave",parse_wave_json)]
    if h!="auto": parsers=sorted(parsers,key=lambda x:x[0]!=h)
    errors=[]
    for name,fn in parsers:
        try: return fn(obj),name
        except ParseError as e: errors.append(str(e))
    raise ParseError("Unsupported scanner JSON. " + " | ".join(errors))
