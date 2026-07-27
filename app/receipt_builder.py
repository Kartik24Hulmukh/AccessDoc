"""Canonical receipt builder for AccessDoc schema 1.2.

This is the SINGLE source of truth for receipt construction. Every product
surface (CLI, API, CI gate, MCP, trend, due-diligence) must call
build_receipt() to produce a receipt dict, and receipt_json_str() to produce
the canonical JSON string that goes into the ZIP bundle and the in-toto
attestation.

Schema 1.2 receipt fields:
  schema_version: "1.2"
  accessdoc_version
  axe_core_verified_version
  catalog_version
  coverage_note
  audit_date
  client_name
  url
  engine_version
  summary
  rule_ids
  finding_fingerprint_version
  violations

Each violations[] entry:
  id, impact, source, target, finding_fingerprint
"""
import hashlib
import json
from .models import VERSION
from .catalog import AXE_CORE_VERIFIED_VERSION, CATALOG_VERSION

FINDING_FINGERPRINT_VERSION = "1"
SCHEMA_VERSION = "1.2"
COVERAGE_NOTE = "Automated scan detects ~30-57% of WCAG issues (Deque 2022)."


def normalize_rule_id(rule_id):
    """Normalize a rule id for fingerprinting."""
    return str(rule_id or "").strip()


def normalize_source(source):
    """Normalize a source label for fingerprinting."""
    return str(source or "").strip()


def normalize_target(target):
    """Normalize a target for fingerprinting (already normalized by parser)."""
    return str(target or "").strip()


def compute_finding_fingerprint(rule_id, source, target):
    """Compute the canonical SHA-256 fingerprint for a single finding.

    Canonical fingerprint input:
      {"rule": normalized_rule_id, "source": normalized_source, "target": normalized_target}
    Canonical serialization:
      json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    Fingerprint:
      sha256(canonical_bytes).hexdigest()

    Returns the COMPLETE 64-character hex digest (never truncated).
    """
    value = {
        "rule": normalize_rule_id(rule_id),
        "source": normalize_source(source),
        "target": normalize_target(target),
    }
    canonical_bytes = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest()


def _violation_to_receipt_entry(v):
    """Convert an AuditViolation to a receipt violations[] entry."""
    fp = compute_finding_fingerprint(v.id, v.source, v.target)
    return {
        "id": v.id,
        "impact": v.impact,
        "source": v.source,
        "target": v.target,
        "finding_fingerprint": fp,
    }


def rule_ids_for_receipt(violations):
    """Return sorted unique rule ids from violations."""
    return sorted({v.id for v in violations})


def build_receipt(summary, violations, metadata):
    """Build the canonical schema 1.2 receipt dict.

    Args:
      summary: AuditSummary dataclass
      violations: list of AuditViolation
      metadata: dict with keys: audit_date, client_name

    Returns:
      dict with all schema 1.2 fields populated.
    """
    audit_date = metadata.get("audit_date", "")
    client_name = metadata.get("client_name", "Client")

    receipt = {
        "schema_version": SCHEMA_VERSION,
        "accessdoc_version": VERSION,
        "axe_core_verified_version": AXE_CORE_VERIFIED_VERSION,
        "catalog_version": CATALOG_VERSION,
        "coverage_note": COVERAGE_NOTE,
        "audit_date": audit_date,
        "client_name": client_name,
        "url": summary.url,
        "engine_version": summary.engine_version,
        "summary": {
            "critical": summary.critical,
            "serious": summary.serious,
            "moderate": summary.moderate,
            "minor": summary.minor,
            "total_violations": summary.total_violations,
            "total_passes": summary.total_passes,
            "manual_findings": summary.manual_findings,
        },
        "rule_ids": rule_ids_for_receipt(violations),
        "finding_fingerprint_version": FINDING_FINGERPRINT_VERSION,
        "violations": [_violation_to_receipt_entry(v) for v in violations],
    }
    return receipt


def receipt_json_str(receipt):
    """Produce the canonical JSON string for a receipt.

    This is the SINGLE function that produces the bytes placed in the ZIP
    bundle, hashed by the manifest, and listed in in-toto subjects/materials.
    Using indent=2 for human readability; the determinism comes from
    consistent serialization (same function everywhere).
    """
    return json.dumps(receipt, indent=2, ensure_ascii=False)
