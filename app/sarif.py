"""SARIF 2.1.0 exporter.

Emits findings in the OASIS SARIF format so AccessDoc violations appear
natively in GitHub Code Scanning / any SARIF-aware tool. This is the
gitleaks / semgrep distribution playbook applied to accessibility evidence.
"""
import json
from .models import VERSION
from .catalog import AXE_CORE_VERIFIED_VERSION
from .receipt_builder import (
    compute_finding_fingerprint,
    FINDING_FINGERPRINT_VERSION,
)

# SARIF partialFingerprints key. Code-scanning platforms use partialFingerprints
# to track "the same finding" across runs; feeding them the AccessDoc finding
# fingerprint means an unresolved barrier stays one alert instead of being
# reopened on every scan, and a remediated barrier closes cleanly.
FINGERPRINT_KEY = f"accessdocFindingFingerprint/v{FINDING_FINGERPRINT_VERSION}"

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
    # Preserve interchange rule IDs. Mixed-source rule metadata must not
    # misclassify either observation; result-level evidence is authoritative.
    grouped = {}
    for v in violations:
        grouped.setdefault(v.id, []).append(v)
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
            "defaultConfiguration": {"level": _level_for(v.impact)},
            "properties": {
                "tags": tags,
                "wcag_success_criteria": v.wcag_scs,
                "impact": v.impact,
                "source": v.source,
            },
        }

        if v.help_url:
            rules[v.id]["helpUri"] = v.help_url
        elif v.source == "automated":
            rules[v.id]["helpUri"] = "https://dequeuniversity.com/rules/axe/"

    for rid, observations in grouped.items():
        sources = sorted({v.source for v in observations})
        if len(sources) < 2:
            continue
        criteria = sorted({sc for v in observations for sc in v.wcag_scs})
        tags = ["accessibility", "wcag"] + [f"wcag-{sc}" for sc in criteria]
        if "manual" in sources:
            tags.append("manual-finding")
        rules[rid] = {
            "id": rid,
            "name": rid.replace("-", "_"),
            "shortDescription": {"text": f"Mixed-source supplied findings: {rid}"[:120]},
            "fullDescription": {"text": (
                "This identifier is shared by supplied findings from multiple sources. "
                "Each result's source, description and severity are authoritative; "
                "rule metadata does not establish independent verification or approval."
            )},
            "properties": {
                "tags": tags,
                "wcag_success_criteria": criteria,
                "source": "mixed",
                "sources": sources,
            },
        }
        # A mixed rule has no inferred scanner guidance. Retain a URI only
        # when every observation explicitly supplies the same nonempty one.
        help_uris = {v.help_url for v in observations}
        if len(help_uris) == 1 and "" not in help_uris:
            rules[rid]["helpUri"] = next(iter(help_uris))

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
                },
                "logicalLocations": [{
                    "name": v.target or v.id,
                    "fullyQualifiedName": v.target or v.id,
                    "kind": "element",
                }],
            }],
            "partialFingerprints": {
                FINGERPRINT_KEY: compute_finding_fingerprint(
                    v.id, v.source, v.target
                ),
            },
            "properties": {
                "nodes": v.nodes,
                "source": v.source,
                "target": v.target,
                "finding_fingerprint_version": FINDING_FINGERPRINT_VERSION,
            },
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
                "review_status": "draft-unreviewed",
                "review_note": "No reviewer approval is recorded. Source labels do not authenticate supplied evidence.",
            },
        }],
    }
    return json.dumps(log, indent=2)
