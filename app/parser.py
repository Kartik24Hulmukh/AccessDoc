"""Parse raw axe-core JSON into AuditSummary + AuditViolation list.

Hardened: rejects non-object payloads, tolerates null arrays, and never
crashes on missing/odd fields.
"""
import json
from .models import AuditSummary, AuditViolation
from .catalog import get_wcag_scs


def parse_axe_json(raw):
    data = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(data, dict):
        raise ValueError("axe-core input must be a JSON object")

    violations_raw = data.get("violations") or []
    passes_raw     = data.get("passes") or []
    incomplete_raw = data.get("incomplete") or []
    if not isinstance(violations_raw, list):
        raise ValueError("'violations' must be a list")
    url            = data.get("url") or ""
    engine         = data.get("testEngine") or {}
    engine_ver     = (engine.get("version") if isinstance(engine, dict) else "") or ""

    impact_counts = {"critical": 0, "serious": 0, "moderate": 0, "minor": 0}
    violations = []
    for v in violations_raw:
        if not isinstance(v, dict):
            continue
        impact = v.get("impact") or "minor"
        impact_counts[impact] = impact_counts.get(impact, 0) + 1
        rule_id = v.get("id", "")
        violations.append(AuditViolation(
            id=rule_id, impact=impact,
            description=v.get("description", ""),
            help_url=v.get("helpUrl", ""),
            wcag_scs=get_wcag_scs(rule_id),
            nodes=len(v.get("nodes") or []),
        ))

    summary = AuditSummary(
        critical=impact_counts.get("critical", 0),
        serious=impact_counts.get("serious", 0),
        moderate=impact_counts.get("moderate", 0),
        minor=impact_counts.get("minor", 0),
        total_violations=len(violations),
        total_passes=len(passes_raw),
        total_incomplete=len(incomplete_raw),
        url=url, engine_version=engine_ver,
    )
    return summary, violations
