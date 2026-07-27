"""Time-series / regression tracking for accessibility posture.

Given a prior receipt and the current receipt, compute the delta (new, fixed,
persisting rules) and produce a trend object that chains to the prior receipt
by its sha256. This is what buyers show lawyers and regulators: "posture over
time", with a tamper-evident chain.

Schema 1.2: supports backward-compatible comparison precision levels.
- 'aggregate-only': only counts exist, cannot classify individual findings
- 'rule-level': rule_ids exist but target fingerprints do not
- 'target-level': compatible fingerprint version and finding fingerprints exist
"""
import hashlib
import json
from .models import VERSION


def _sha256_of_receipt(receipt):
    """Stable digest of a receipt dict/str (sorted keys, compact)."""
    if isinstance(receipt, (bytes, bytearray)):
        return hashlib.sha256(bytes(receipt)).hexdigest()
    if isinstance(receipt, str):
        try:
            receipt = json.loads(receipt)
        except ValueError:
            return hashlib.sha256(receipt.encode()).hexdigest()
    payload = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _rule_set(violations):
    return {v.id for v in violations}


def _detect_precision(receipt):
    """Detect the comparison precision level of a receipt.

    Returns one of: 'target-level', 'rule-level', 'aggregate-only'
    """
    if isinstance(receipt, str):
        try:
            receipt = json.loads(receipt)
        except ValueError:
            return "aggregate-only"
    if not isinstance(receipt, dict):
        return "aggregate-only"

    violations = receipt.get("violations")
    if isinstance(violations, list) and violations:
        # Check if violations have finding_fingerprint and target
        has_fingerprints = all(
            isinstance(v, dict) and v.get("finding_fingerprint")
            for v in violations if isinstance(v, dict)
        )
        has_targets = all(
            isinstance(v, dict) and v.get("target") is not None
            for v in violations if isinstance(v, dict)
        )
        if has_fingerprints and has_targets:
            return "target-level"

    rule_ids = receipt.get("rule_ids")
    if isinstance(rule_ids, list) and rule_ids:
        return "rule-level"

    return "aggregate-only"


def _extract_fingerprints(receipt):
    """Extract finding fingerprints from a receipt's violations.

    Returns a set of finding_fingerprint strings, or empty set if not available.
    """
    if isinstance(receipt, str):
        try:
            receipt = json.loads(receipt)
        except ValueError:
            return set()
    if not isinstance(receipt, dict):
        return set()
    fps = set()
    for v in (receipt.get("violations") or []):
        if isinstance(v, dict) and v.get("finding_fingerprint"):
            fps.add(v["finding_fingerprint"])
    return fps


def _extract_rule_ids(receipt):
    """Extract rule_ids from a receipt."""
    if isinstance(receipt, str):
        try:
            receipt = json.loads(receipt)
        except ValueError:
            return set()
    if not isinstance(receipt, dict):
        return set()
    return set(receipt.get("rule_ids") or [])


def _prior_rule_set(prior_receipt):
    """Best-effort extraction of the prior rule id set from a stored receipt."""
    if isinstance(prior_receipt, str):
        try:
            prior_receipt = json.loads(prior_receipt)
        except ValueError:
            return set(), {}
    rule_ids = prior_receipt.get("rule_ids") or []
    summary = prior_receipt.get("summary", {})
    return set(rule_ids), summary


def build_trend(prior_receipt, current_receipt, current_violations):
    """Return a trend.json string chaining current state to the prior receipt.

    Supports backward-compatible comparison precision:
    - If both receipts have target-level precision, compare by finding fingerprint
    - If either is rule-level or aggregate-only, use the lowest shared precision
    - Never invent target-level remediation claims from aggregate-only data
    """
    prior_precision = _detect_precision(prior_receipt)
    current_precision = _detect_precision(current_receipt)

    # Use the lowest defensible shared precision.
    precision_order = {"target-level": 3, "rule-level": 2, "aggregate-only": 1}
    shared_precision = (
        prior_precision if precision_order[prior_precision] <= precision_order[current_precision]
        else current_precision
    )

    warnings = []

    if prior_precision != current_precision:
        warnings.append(
            f"Prior receipt precision ({prior_precision}) differs from current "
            f"({current_precision}). Using lowest shared precision: {shared_precision}."
        )

    if shared_precision == "aggregate-only":
        warnings.append(
            "Prior receipt has aggregate-only precision (counts only). "
            "Individual findings cannot be classified as remediated, persisting, "
            "or introduced. All trend classifications are at aggregate count level only."
        )

    prior_rules, prior_summary = _prior_rule_set(prior_receipt)
    current_rules = _rule_set(current_violations)

    new_rules = sorted(current_rules - prior_rules)
    fixed_rules = sorted(prior_rules - current_rules)
    persisting = sorted(current_rules & prior_rules)

    # Target-level comparison if both receipts support it.
    remediated_findings = []
    persisting_findings = []
    introduced_findings = []
    if shared_precision == "target-level":
        prior_fps = _extract_fingerprints(prior_receipt)
        # Build current fingerprints from current_violations.
        from .receipt_builder import compute_finding_fingerprint
        current_fps = set()
        current_fp_map = {}
        for v in current_violations:
            fp = compute_finding_fingerprint(v.id, v.source, v.target)
            current_fps.add(fp)
            current_fp_map[fp] = v

        remediated_fps = sorted(prior_fps - current_fps)
        persisting_fps = sorted(prior_fps & current_fps)
        introduced_fps = sorted(current_fps - prior_fps)

        for fp in remediated_fps:
            remediated_findings.append({"finding_fingerprint": fp})
        for fp in persisting_fps:
            v = current_fp_map.get(fp)
            if v:
                persisting_findings.append({
                    "finding_fingerprint": fp,
                    "id": v.id,
                    "target": v.target,
                })
        for fp in introduced_fps:
            v = current_fp_map.get(fp)
            if v:
                introduced_findings.append({
                    "finding_fingerprint": fp,
                    "id": v.id,
                    "target": v.target,
                })

    cur_summary = current_receipt.get("summary", {})
    prior_total = prior_summary.get("total_violations")
    cur_total = cur_summary.get("total_violations")
    delta_total = None
    if isinstance(prior_total, int) and isinstance(cur_total, int):
        delta_total = cur_total - prior_total

    trend = {
        "schema_version": "1.1",
        "generator": {"name": "accessdoc", "version": VERSION},
        "prev_receipt_sha256": _sha256_of_receipt(prior_receipt),
        "comparison_precision": shared_precision,
        "prior_precision": prior_precision,
        "current_precision": current_precision,
        "prior_summary": prior_summary,
        "current_summary": cur_summary,
        "delta_total_violations": delta_total,
        "new_rules": new_rules,
        "fixed_rules": fixed_rules,
        "persisting_rules": persisting,
        "regressed": len(new_rules) > 0,
        "improved": len(fixed_rules) > 0,
        "note": "Rule-level trend. Absence of a rule means it was not detected "
                "by the automated scan, not that it is necessarily resolved.",
        "warnings": warnings,
    }

    if shared_precision == "target-level":
        trend["remediated_findings"] = remediated_findings
        trend["persisting_findings"] = persisting_findings
        trend["introduced_findings"] = introduced_findings
        trend["remediated_count"] = len(remediated_findings)
        trend["persisting_count"] = len(persisting_findings)
        trend["introduced_count"] = len(introduced_findings)

    return json.dumps(trend, indent=2)


def rule_ids_for_receipt(violations):
    """Helper to embed rule ids in a receipt so future trends are precise."""
    return sorted({v.id for v in violations})
