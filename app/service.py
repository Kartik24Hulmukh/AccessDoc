"""Core orchestration: parse -> (merge manual) -> report -> optional exports -> attest.

SECURITY: every user-controlled value rendered into HTML goes through
html.escape(); every value rendered into YAML goes through openacr._yq().
The deterministic evidence core never calls out to a network or an LLM.
"""
import html
import json
import datetime
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

from .models import VERSION, SOURCE_MANUAL
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
    sarif_json: Optional[str] = None
    vpat_html: Optional[str] = None
    eaa_markdown: Optional[str] = None
    trend_json: Optional[str] = None

    def payloads(self):
        """Ordered dict of every bundle member except manifest.json.

        Optional exports are inserted before the attestation so they are
        attested by both the in-toto statement and the manifest.
        """
        p = OrderedDict()
        p["report.pdf"] = self.pdf_bytes
        p["report.html"] = self.html_bytes
        p["receipt.json"] = self.receipt_json.encode()
        p["openacr.yaml"] = self.openacr_yaml.encode()
        if self.sarif_json is not None:
            p["findings.sarif.json"] = self.sarif_json.encode()
        if self.vpat_html is not None:
            p["vpat-draft.html"] = self.vpat_html.encode()
        if self.eaa_markdown is not None:
            p["eaa-evidence.md"] = self.eaa_markdown.encode()
        if self.trend_json is not None:
            p["trend.json"] = self.trend_json.encode()
        p["attestation.intoto.json"] = self.intoto_bytes
        return p


def _build_html(summary, violations, client_name, audit_date):
    e = html.escape
    rows = "".join(
        f"<tr><td>{e(v.id)}</td><td>{e(v.impact)}</td><td>{v.nodes}</td>"
        f"<td>{e(', '.join(v.wcag_scs) or '-')}</td><td>{e(v.source)}</td></tr>"
        for v in violations
    )
    return (
        f"<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>AccessDoc - {e(client_name)}</title></head><body>"
        f"<h1>WCAG 2.2 Audit: {e(client_name)}</h1>"
        f"<p>Date: {e(audit_date)} | URL: {e(summary.url)}</p>"
        f"<p>axe-core: {e(summary.engine_version)} | catalog: {e(CATALOG_VERSION)} | AccessDoc: {e(VERSION)}</p>"
        f"<table border='1'><tr><th>Rule</th><th>Impact</th><th>Nodes</th><th>WCAG SC</th><th>Source</th></tr>{rows}</table>"
        f"<p><small>Automated scan detects ~30-57% of WCAG issues (Deque 2022). "
        f"Manual review required for legal compliance.</small></p>"
        f"</body></html>"
    )


def build_artifacts(body):
    """Build the full artifact set from a request body.

    Recognised keys:
      scanner_input   (required) raw axe-core JSON (str or dict); must be non-empty
      client_name, agency_name, audit_date
      manual_findings  optional list/CSV/markdown of human findings
      enrich           bool -> attach plain-language explanations to receipt
      include_sarif    bool -> add findings.sarif.json
      include_vpat     bool -> add vpat-draft.html
      include_eaa      bool -> add eaa-evidence.md
      prior_receipt    dict/json-str -> add trend.json (regression tracking)

    Raises ValueError if scanner_input is missing/empty or not valid axe JSON.
    """
    scanner_raw = body.get("scanner_input")
    if not scanner_raw:
        raise ValueError("scanner_input is required and must be non-empty axe-core JSON")

    client_name = body.get("client_name", "Client")
    agency_name = body.get("agency_name", "Audit Agency")
    audit_date  = body.get("audit_date") or datetime.date.today().isoformat()

    summary, violations = parse_axe_json(scanner_raw)

    # ---- optional: merge human (manual) findings ----
    manual = body.get("manual_findings")
    if manual:
        from .manual import parse_manual_findings, merge_findings
        manual_viols = parse_manual_findings(manual)
        violations = merge_findings(violations, manual_viols, summary)

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
            "manual_findings": summary.manual_findings,
        },
    }

    # ---- optional: provenance-labeled AI/plain-language enrichment ----
    if body.get("enrich"):
        from .enrich import enrich_violations
        receipt["enrichment"] = enrich_violations(violations)

    openacr_yaml = generate_openacr_yaml(summary, violations, client_name, audit_date)

    # ---- optional exports ----
    sarif_json = vpat_html = eaa_markdown = trend_json = None

    if body.get("include_sarif"):
        from .sarif import generate_sarif
        sarif_json = generate_sarif(summary, violations)

    if body.get("include_vpat"):
        from .vpat import generate_vpat_html
        vpat_html = generate_vpat_html(summary, violations, client_name, audit_date)

    if body.get("include_eaa"):
        from .eaa import generate_eaa_pack
        eaa_markdown = generate_eaa_pack(summary, violations, client_name, audit_date)

    prior = body.get("prior_receipt")
    if prior:
        from .timeseries import build_trend
        trend_json = build_trend(prior, receipt, violations)

    # ---- attestation over every produced file ----
    attested = {
        "report.pdf":   pdf_bytes,
        "report.html":  html_bytes,
        "receipt.json": json.dumps(receipt).encode(),
        "openacr.yaml": openacr_yaml.encode(),
    }
    if sarif_json is not None:
        attested["findings.sarif.json"] = sarif_json.encode()
    if vpat_html is not None:
        attested["vpat-draft.html"] = vpat_html.encode()
    if eaa_markdown is not None:
        attested["eaa-evidence.md"] = eaa_markdown.encode()
    if trend_json is not None:
        attested["trend.json"] = trend_json.encode()

    intoto_bytes = build_intoto_bundle(attested)

    return Artifacts(
        pdf_bytes=pdf_bytes,
        html_bytes=html_bytes,
        receipt_json=json.dumps(receipt, indent=2),
        openacr_yaml=openacr_yaml,
        intoto_bytes=intoto_bytes,
        sarif_json=sarif_json,
        vpat_html=vpat_html,
        eaa_markdown=eaa_markdown,
        trend_json=trend_json,
    )
