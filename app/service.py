"""Core orchestration: parse -> report -> bundle."""
import json
import datetime
from dataclasses import dataclass
from .models import VERSION
from .parser import parse_axe_json
from .reporter import generate_pdf_report
from .catalog import AXE_CORE_VERIFIED_VERSION, CATALOG_VERSION
from .openacr import generate_openacr_yaml
from .intoto import build_intoto_bundle


@dataclass
class Artifacts:
    pdf_bytes: bytes
    html_bytes: bytes
    receipt_json: str
    openacr_yaml: str
    intoto_bytes: bytes


def _build_html(summary, violations, client_name, audit_date):
    rows = "".join(
        f"<tr><td>{v.id}</td><td>{v.impact}</td><td>{v.nodes}</td>"
        f"<td>{', '.join(v.wcag_scs) or '-'}</td></tr>"
        for v in violations
    )
    return (
        f"<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>AccessDoc - {client_name}</title></head><body>"
        f"<h1>WCAG 2.2 Audit: {client_name}</h1>"
        f"<p>Date: {audit_date} | URL: {summary.url}</p>"
        f"<p>axe-core: {summary.engine_version} | catalog: {CATALOG_VERSION} | AccessDoc: {VERSION}</p>"
        f"<table border='1'><tr><th>Rule</th><th>Impact</th><th>Nodes</th><th>WCAG SC</th></tr>{rows}</table>"
        f"<p><small>Automated scan detects ~30-57% of WCAG issues. Manual review required.</small></p>"
        f"</body></html>"
    )


def build_artifacts(body):
    client_name = body.get("client_name", "Client")
    agency_name = body.get("agency_name", "Audit Agency")
    audit_date  = body.get("audit_date") or datetime.date.today().isoformat()
    scanner_raw = body.get("scanner_input", "{}")

    summary, violations = parse_axe_json(scanner_raw)
    pdf_bytes  = generate_pdf_report(summary, violations, client_name, agency_name, audit_date)
    html_bytes = _build_html(summary, violations, client_name, audit_date).encode()

    receipt = {
        "schema_version": "1.1",
        "accessdoc_version": VERSION,
        "axe_core_verified_version": AXE_CORE_VERIFIED_VERSION,
        "catalog_version": CATALOG_VERSION,
        "coverage_note": "Automated scan detects ~30-57% of WCAG issues (Deque 2022).",
        "audit_date": audit_date,
        "client_name": client_name,
        "url": summary.url,
        "engine_version": summary.engine_version,
        "summary": {
            "critical": summary.critical, "serious": summary.serious,
            "moderate": summary.moderate, "minor": summary.minor,
            "total_violations": summary.total_violations,
            "total_passes": summary.total_passes,
        },
    }

    openacr_yaml = generate_openacr_yaml(summary, violations, client_name, audit_date)
    intoto_bytes = build_intoto_bundle({
        "report.pdf":   pdf_bytes,
        "report.html":  html_bytes,
        "receipt.json": json.dumps(receipt).encode(),
        "openacr.yaml": openacr_yaml.encode(),
    })

    return Artifacts(
        pdf_bytes=pdf_bytes,
        html_bytes=html_bytes,
        receipt_json=json.dumps(receipt, indent=2),
        openacr_yaml=openacr_yaml,
        intoto_bytes=intoto_bytes,
    )
