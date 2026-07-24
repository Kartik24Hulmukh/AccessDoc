"""Time-series / regression tracking for accessibility posture.

Given a prior receipt and the current receipt, compute the delta (new, fixed,
persisting rules) and produce a trend object that chains to the prior receipt
by its sha256. This is what buyers show lawyers and regulators: "posture over
time", with a tamper-evident chain.
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


def _prior_rule_set(prior_receipt):
    """Best-effort extraction of the prior rule id set from a stored receipt.

    Receipts may embed a 'rule_ids' list (preferred) or we fall back to an
    empty set (older receipts only carried aggregate counts).
    """
    if isinstance(prior_receipt, str):
        try:
            prior_receipt = json.loads(prior_receipt)
        except ValueError:
            return set(), {}
    rule_ids = prior_receipt.get("rule_ids") or []
    summary = prior_receipt.get("summary", {})
    return set(rule_ids), summary


def build_trend(prior_receipt, current_receipt, current_violations):
    """Return a trend.json string chaining current state to the prior receipt."""
    prior_rules, prior_summary = _prior_rule_set(prior_receipt)
    current_rules = _rule_set(current_violations)

    new_rules = sorted(current_rules - prior_rules)
    fixed_rules = sorted(prior_rules - current_rules)
    persisting = sorted(current_rules & prior_rules)

    cur_summary = current_receipt.get("summary", {})
    prior_total = prior_summary.get("total_violations")
    cur_total = cur_summary.get("total_violations")
    delta_total = None
    if isinstance(prior_total, int) and isinstance(cur_total, int):
        delta_total = cur_total - prior_total

    trend = {
        "schema_version": "1.0",
        "generator": {"name": "accessdoc", "version": VERSION},
        "prev_receipt_sha256": _sha256_of_receipt(prior_receipt),
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
    }
    return json.dumps(trend, indent=2)


def rule_ids_for_receipt(violations):
    """Helper to embed rule ids in a receipt so future trends are precise."""
    return sorted({v.id for v in violations})
