"""Shared domain models and constants for AccessDoc v0.5.0-beta.1."""
from dataclasses import dataclass, field
from typing import List

VERSION = "0.5.0-beta.1"

COVERAGE_STATS = {
    "deque_2022": {"pct_range": (30, 57), "source": "Deque Systems Accessibility Report 2022"},
    "gds_2017":   {"pct_range": (30, 40), "source": "GDS accessibility audits 2017"},
}

DISCLAIMER = (
    "IMPORTANT - AUTOMATED AUDIT LIMITATIONS\n"
    "Automated tools like axe-core detect 30-57 % of WCAG issues "
    "(Deque Systems 2022; GDS 2017). This report does NOT replace a "
    "manual audit, assistive-technology testing, or legal accessibility review."
)

DISCLAIMER_COMPACT = (
    "Auto-scan detects ~30-57 % of WCAG issues (Deque 2022). "
    "Manual review required for legal compliance."
)


@dataclass
class AuditViolation:
    id: str
    impact: str
    description: str
    help_url: str
    wcag_scs: List[str] = field(default_factory=list)
    nodes: int = 0


@dataclass
class AuditSummary:
    critical: int = 0
    serious: int = 0
    moderate: int = 0
    minor: int = 0
    total_violations: int = 0
    total_passes: int = 0
    total_incomplete: int = 0
    url: str = ""
    engine_version: str = ""
