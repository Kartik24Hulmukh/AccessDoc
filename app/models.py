from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Any
import re

LEVELS = {"A", "AA", "AAA", "N/A"}
SEVERITIES = {"critical", "high", "medium", "low", "needs-review"}
EFFORTS = {"XS", "S", "M", "L", "XL", "Unknown"}


def clean_text(value: Any, limit: int = 4000) -> str:
    text = str(value or "").replace("\x00", "").strip()
    text = re.sub(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f]", "", text)
    return text[:limit]

@dataclass
class Occurrence:
    html: str = ""
    selector: str = ""
    failure_summary: str = ""
    page_url: str = ""

    def __post_init__(self):
        self.html = clean_text(self.html, 2000)
        self.selector = clean_text(self.selector, 1000)
        self.failure_summary = clean_text(self.failure_summary, 2000)
        self.page_url = clean_text(self.page_url, 1000)

@dataclass
class Finding:
    finding_id: str
    source: str
    source_rule_id: str
    title: str
    description: str
    wcag_criterion: str
    wcag_title: str
    level: str
    severity: str
    effort: str
    user_impact: str
    remediation: str
    occurrences: list[Occurrence] = field(default_factory=list)
    review_state: str = "unreviewed"
    mapping_basis: str = "curated_rule_map"
    confidence: str = "automated"
    normative_url: str = ""

    def __post_init__(self):
        for name, limit in (("finding_id",128),("source",32),("source_rule_id",128),("title",300),("description",4000),("wcag_criterion",32),("wcag_title",300),("user_impact",3000),("remediation",5000),("normative_url",1000)):
            setattr(self, name, clean_text(getattr(self, name), limit))
        if self.level not in LEVELS: self.level = "N/A"
        if self.severity not in SEVERITIES: self.severity = "needs-review"
        if self.effort not in EFFORTS: self.effort = "Unknown"
        self.occurrences = self.occurrences[:500]

    @property
    def instance_count(self) -> int:
        return max(1, len(self.occurrences))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["instance_count"] = self.instance_count
        return d

@dataclass
class Branding:
    agency_name: str = "AccessDoc Studio"
    primary_color: str = "#185ABD"
    logo_png: bytes | None = None

    def __post_init__(self):
        self.agency_name = clean_text(self.agency_name, 120) or "AccessDoc Studio"
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", self.primary_color or ""):
            self.primary_color = "#185ABD"
        if self.logo_png and len(self.logo_png) > 500_000:
            raise ValueError("Logo exceeds 500 KB")
        if self.logo_png and not self.logo_png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Only valid PNG logos are accepted")

@dataclass
class AuditRequest:
    client_name: str
    audit_date: str
    branding: Branding
    findings: list[Finding]
    manual_findings: str = ""
    source_format: str = "unknown"
    source_filename: str = "pasted-evidence"
    input_sha256: str = ""
    generator_version: str = "0.4.0-beta.4"

    def __post_init__(self):
        self.client_name = clean_text(self.client_name, 160) or "Client"
        self.manual_findings = clean_text(self.manual_findings, 12000)
        self.source_format = clean_text(self.source_format, 40) or "unknown"
        self.source_filename = clean_text(self.source_filename, 160) or "pasted-evidence"
        self.input_sha256 = clean_text(self.input_sha256, 64)
        if not re.fullmatch(r"[0-9a-f]{64}", self.input_sha256): self.input_sha256 = "unavailable"
        self.generator_version = clean_text(self.generator_version, 32) or "unknown"
        try: date.fromisoformat(self.audit_date)
        except Exception: self.audit_date = date.today().isoformat()
        self.findings = self.findings[:200]

DISCLAIMER = (
    "Assessment limitation: This report combines automated checks and any human findings recorded here. "
    "Automated tools detect only some accessibility barriers. A passing automated check or high score does "
    "not establish WCAG 2.2 conformance or legal compliance. Knowledgeable human evaluation—including "
    "keyboard, screen-reader, zoom/reflow, content-quality, and task-based testing—is required. Results apply "
    "only to the supplied evidence and stated scope. This report is not legal advice or certification."
)
