"""SARIF 2.1.0 exporter.

Emits findings in the OASIS SARIF format so AccessDoc violations appear
natively in GitHub Code Scanning / any SARIF-aware tool. This is the
gitleaks / semgrep distribution playbook applied to accessibility evidence.
"""
import json
from .models import VERSION
from .catalog import AXE_CORE_VERIFIED_VERSION

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"

# axe impact -> SARIF result level
_LEVEL = {
    "critical": "error",
    "serious": "error",
    "moderate": "warning",
    "minor": "note",
}


def _level_for(impact):
    return _LEVEL.get(impact, "warning")


def generate_sarif(summary, violations):
    """Return a SARIF 2.1.0 log as a JSON string."""
    # Deduplicate rules by id, preserving first-seen metadata.
    rules = {}
    for v in violations:
        if v.id in rules:
            continue
        tags = ["accessibility", "wcag"] + [f"wcag-{sc}" for sc in v.wcag_scs]
        if v.source == "manual":
            tags.append("manual-finding")
        rules[v.id] = {
            "id": v.id,
            "name": v.id.replace("-", "_"),
            "shortDescription": {"text": (v.description or v.id)[:120]},
            "fullDescription": {"text": v.description or v.id},
            "helpUri": v.help_url or "https://dequeuniversity.com/rules/axe/",
            "defaultConfiguration": {"level": _level_for(v.impact)},
            "properties": {
                "tags": tags,
                "wcag_success_criteria": v.wcag_scs,
                "impact": v.impact,
                "source": v.source,
            },
        }

    rule_index = {rid: i for i, rid in enumerate(rules)}
    artifact_uri = summary.url or "unknown://audited-target"

    results = []
    for v in violations:
        results.append({
            "ruleId": v.id,
            "ruleIndex": rule_index[v.id],
            "level": _level_for(v.impact),
            "message": {
                "text": (
                    f"{v.description or v.id} "
                    f"[impact={v.impact}; nodes={v.nodes}; "
                    f"WCAG {', '.join(v.wcag_scs) or 'n/a'}; source={v.source}]"
                )
            },
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": artifact_uri}
                }
            }],
            "properties": {"nodes": v.nodes, "source": v.source},
        })

    log = {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [{
            "tool": {
                "driver": {
                    "name": "AccessDoc",
                    "version": VERSION,
                    "informationUri": "https://accessdoc.dev",
                    "rules": list(rules.values()),
                    "properties": {
                        "axe_core_verified_version": AXE_CORE_VERIFIED_VERSION,
                        "coverage_note": "Automated scan detects ~30-57% of WCAG issues (Deque 2022). Manual review required.",
                    },
                }
            },
            "results": results,
            "properties": {
                "total_violations": summary.total_violations,
                "manual_findings": summary.manual_findings,
            },
        }],
    }
    return json.dumps(log, indent=2)
