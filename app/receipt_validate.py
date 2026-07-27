"""Strict structural + cryptographic validation of AccessDoc receipts.

Why this module exists
----------------------
Before beta.5, a tampered prior receipt was only *observable*: the trend output
would classify findings differently, and a careful reader might notice. Nothing
in the product actually *rejected* it. "Detectable if you already suspect
tampering" is not a tamper-evidence property you can put in front of a lawyer.

This module closes that gap. It recomputes every `finding_fingerprint` from the
canonical `{rule, source, target}` triple and rejects any receipt where a stored
fingerprint does not match its own content. That makes silent edits to a
finding's rule, source, or target impossible to pass off as authentic: you
cannot change the content without changing the fingerprint, and you cannot
change the fingerprint without failing re-derivation.

Honest scope
------------
This is *self-consistency* verification, not proof of authorship or of time.
An attacker who rewrites a finding AND recomputes its fingerprint produces a
self-consistent receipt. Detecting that requires the signature chain (Sigstore
via the signing workflow) or the manifest/attestation digests inside the bundle.
The layered guarantee is:

    receipt self-consistency  -> this module
    bundle-member integrity   -> app/bundle.validate_bundle (SHA-256 manifest)
    authorship + build origin -> Sigstore signature over the bundle
    truthful wall-clock time  -> NOT provided; audit_date is caller-supplied

Never claim more than the layer you actually ran.
"""
import re

from .receipt_builder import (
    SCHEMA_VERSION,
    FINDING_FINGERPRINT_VERSION,
    compute_finding_fingerprint,
)

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

# Receipt schema versions this build understands.
SUPPORTED_RECEIPT_SCHEMAS = frozenset({"1.0", "1.1", "1.2"})

# Fields every schema 1.2 receipt must carry.
REQUIRED_1_2_FIELDS = (
    "schema_version",
    "accessdoc_version",
    "axe_core_verified_version",
    "catalog_version",
    "coverage_note",
    "audit_date",
    "client_name",
    "url",
    "engine_version",
    "summary",
    "rule_ids",
    "finding_fingerprint_version",
    "violations",
)

REQUIRED_VIOLATION_FIELDS = ("id", "impact", "source", "target",
                            "finding_fingerprint")

_SUMMARY_INT_FIELDS = (
    "critical", "serious", "moderate", "minor",
    "total_violations", "total_passes", "manual_findings",
)


def precision_of(receipt):
    """Return the defensible comparison precision of a receipt.

    'target-level'   : per-finding targets + verifiable fingerprints exist
    'rule-level'     : rule_ids exist, but no per-finding identity
    'aggregate-only' : counts only; no finding can be individually tracked
    """
    if not isinstance(receipt, dict):
        return "aggregate-only"
    violations = receipt.get("violations")
    if isinstance(violations, list) and violations:
        ok = all(
            isinstance(v, dict)
            and v.get("target") is not None
            and isinstance(v.get("finding_fingerprint"), str)
            and _HEX64_RE.match(v["finding_fingerprint"])
            for v in violations
        )
        if ok:
            return "target-level"
    if isinstance(receipt.get("rule_ids"), list) and receipt.get("rule_ids"):
        return "rule-level"
    return "aggregate-only"


def validate_receipt(receipt, strict=True):
    """Validate a receipt dict. Returns a list of human-readable errors.

    Args:
        receipt: parsed receipt dict.
        strict: when True, schema 1.2 receipts must satisfy every structural
            requirement AND every fingerprint must re-derive. When False, only
            hard integrity failures (fingerprint mismatch, malformed
            fingerprint) are reported, so legacy 1.0/1.1 receipts still pass.

    An empty list means the receipt is internally self-consistent.
    """
    errors = []
    if not isinstance(receipt, dict):
        return ["receipt is not a JSON object"]

    schema = receipt.get("schema_version")
    if not isinstance(schema, str) or not schema:
        errors.append("schema_version is missing or not a string")
        schema = ""
    elif schema not in SUPPORTED_RECEIPT_SCHEMAS:
        errors.append(
            f"unsupported schema_version {schema!r} "
            f"(supported: {', '.join(sorted(SUPPORTED_RECEIPT_SCHEMAS))})"
        )

    is_1_2 = schema == SCHEMA_VERSION

    if is_1_2 and strict:
        for field in REQUIRED_1_2_FIELDS:
            if field not in receipt:
                errors.append(f"schema 1.2 receipt missing field: {field}")

        fpv = receipt.get("finding_fingerprint_version")
        if fpv is not None and str(fpv) != FINDING_FINGERPRINT_VERSION:
            errors.append(
                f"unknown finding_fingerprint_version {fpv!r}; "
                f"this build derives version {FINDING_FINGERPRINT_VERSION}"
            )

        summary = receipt.get("summary")
        if not isinstance(summary, dict):
            errors.append("summary must be an object")
        else:
            for field in _SUMMARY_INT_FIELDS:
                value = summary.get(field)
                if not isinstance(value, int) or isinstance(value, bool):
                    errors.append(f"summary.{field} must be an integer")
                elif value < 0:
                    errors.append(f"summary.{field} must not be negative")

        rule_ids = receipt.get("rule_ids")
        if rule_ids is not None and not isinstance(rule_ids, list):
            errors.append("rule_ids must be a list")

    violations = receipt.get("violations")
    if violations is None:
        if is_1_2 and strict:
            errors.append("schema 1.2 receipt has no violations list")
        return errors
    if not isinstance(violations, list):
        errors.append("violations must be a list")
        return errors

    seen_rule_ids = set()
    for index, entry in enumerate(violations):
        where = f"violations[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{where} is not an object")
            continue

        if is_1_2 and strict:
            for field in REQUIRED_VIOLATION_FIELDS:
                if field not in entry:
                    errors.append(f"{where} missing field: {field}")

        rule_id = entry.get("id")
        if isinstance(rule_id, str) and rule_id:
            seen_rule_ids.add(rule_id)

        stored = entry.get("finding_fingerprint")
        if stored is None:
            continue
        if not isinstance(stored, str) or not _HEX64_RE.match(stored):
            errors.append(
                f"{where}.finding_fingerprint is not a 64-character "
                f"lowercase SHA-256 hex digest"
            )
            continue

        # The integrity check that makes tampering fail rather than merely look
        # odd: re-derive the fingerprint from the finding's own content.
        expected = compute_finding_fingerprint(
            entry.get("id"), entry.get("source"), entry.get("target")
        )
        if stored != expected:
            errors.append(
                f"{where}.finding_fingerprint does not match its content "
                f"(rule={entry.get('id')!r}, source={entry.get('source')!r}, "
                f"target={entry.get('target')!r}); receipt was modified after "
                f"generation or was produced by an incompatible generator"
            )

    if is_1_2 and strict and isinstance(receipt.get("rule_ids"), list):
        declared = set(receipt["rule_ids"])
        if seen_rule_ids and declared != seen_rule_ids:
            missing = sorted(seen_rule_ids - declared)
            extra = sorted(declared - seen_rule_ids)
            detail = []
            if missing:
                detail.append(f"absent from rule_ids: {missing}")
            if extra:
                detail.append(f"declared but unused: {extra}")
            errors.append(
                "rule_ids does not agree with violations ("
                + "; ".join(detail) + ")"
            )

    return errors


def verify_receipt_chain(receipts):
    """Verify an ordered chain of receipts (oldest first).

    Returns a dict describing the chain, with an explicit, defensible
    `comparison_precision` and a hard `valid` flag. Chain-level rules:

      * every receipt must be self-consistent (see validate_receipt)
      * audit_date must be non-decreasing; a receipt dated before its
        predecessor is reported, because a back-dated link is exactly what an
        adversarial reviewer looks for
      * precision degrades to the weakest link; a single aggregate-only
        receipt in the chain forbids per-finding remediation claims
    """
    order = {"target-level": 3, "rule-level": 2, "aggregate-only": 1}
    result = {
        "valid": True,
        "receipts": len(receipts or []),
        "errors": [],
        "warnings": [],
        "per_receipt": [],
        "comparison_precision": "aggregate-only",
    }
    if not receipts:
        result["valid"] = False
        result["errors"].append("chain is empty")
        return result

    weakest = "target-level"
    previous_date = None
    for index, receipt in enumerate(receipts):
        errors = validate_receipt(receipt, strict=True)
        precision = precision_of(receipt)
        if order[precision] < order[weakest]:
            weakest = precision
        audit_date = (receipt or {}).get("audit_date") or ""
        entry = {
            "index": index,
            "audit_date": audit_date,
            "schema_version": (receipt or {}).get("schema_version"),
            "accessdoc_version": (receipt or {}).get("accessdoc_version"),
            "precision": precision,
            "errors": errors,
        }
        result["per_receipt"].append(entry)
        if errors:
            result["valid"] = False
            result["errors"].extend(f"receipt[{index}]: {e}" for e in errors)
        if previous_date and audit_date and audit_date < previous_date:
            result["valid"] = False
            result["errors"].append(
                f"receipt[{index}]: audit_date {audit_date} precedes "
                f"receipt[{index - 1}] audit_date {previous_date}; "
                f"the chain is not in chronological order"
            )
        if audit_date:
            previous_date = audit_date

    result["comparison_precision"] = weakest
    if weakest != "target-level":
        result["warnings"].append(
            f"weakest link in the chain is {weakest}; per-finding remediation "
            f"claims are not supported by this chain"
        )
    result["warnings"].append(
        "Self-consistency only. Audit dates are caller-supplied and are not "
        "independently timestamped; authorship and build origin require the "
        "Sigstore signature over the bundle."
    )
    return result
