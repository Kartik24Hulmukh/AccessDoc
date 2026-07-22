"""Parse raw axe-core JSON into AuditSummary + AuditViolation list."""
import json
from .models import AuditSummary, AuditViolation
from .catalog import get_wcag_scs


def parse_axe_json(raw):
    data = json.loads(raw) if isinstance(raw, str) else raw
    violations_raw = data.get("violations", [])
    passes_raw     = data.get("passes", [])
    incomplete_raw = data.get("incomplete", [])
    url            = data.get("url", "")
    engine         = data.get("testEngine", {})
    engine_ver     = engine.get("version", "")

    impact_counts = {"critical": 0, "serious": 0, "moderate": 0, "minor": 0}
    violations = []
    for v in violations_raw:
        impact = v.get("impact") or "minor"
        impact_counts[impact] = impact_counts.get(impact, 0) + 1
        rule_id = v.get("id", "")
        violations.append(AuditViolation(
            id=rule_id, impact=impact,
            description=v.get("description", ""),
            help_url=v.get("helpUrl", ""),
            wcag_scs=get_wcag_scs(rule_id),
            nodes=len(v.get("nodes", [])),
        ))

    summary = AuditSummary(
        critical=impact_counts.get("critical", 0),
        serious=impact_counts.get("serious", 0),
        moderate=impact_counts.get("moderate", 0),
        minor=impact_counts.get("minor", 0),
        total_violations=len(violations_raw),
        total_passes=len(passes_raw),
        total_incomplete=len(incomplete_raw),
        url=url, engine_version=engine_ver,
    )
    return summary, violations
