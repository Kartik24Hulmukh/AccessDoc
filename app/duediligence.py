"""Due-diligence ledger: proof of *reasonable steps over time*.

Why this module exists
----------------------
Enforcement practice under the EAA and ADA Title II does not turn on whether a
site was ever perfect. Regulators and courts ask two questions:

    1. Did the organisation KNOW about the barrier?
    2. Did it take REASONABLE STEPS to remove it, within a reasonable time?

A single-point-in-time scan answers neither. It can even hurt you: it proves
knowledge without proving action. What answers both is an append-only,
tamper-evident chain of dated evidence showing detection, then remediation.

This module turns a chain of AccessDoc receipts into that record. It is the
artifact a lawyer wants in a bundle and no scanner currently produces.

Determinism: every value is derived from the receipts passed in. No wall clock.
"""

DUE_DILIGENCE_SCHEMA_VERSION = "1.0"

_IMPACTS = ("critical", "serious", "moderate", "minor")


def _counts(receipt):
    s = (receipt or {}).get("summary") or {}
    return {k: int(s.get(k) or 0) for k in _IMPACTS}


def _total(counts):
    return sum(counts.values())


def _fingerprints(receipt):
    """Stable identity for each finding, so we can track a specific barrier."""
    out = {}
    for v in (receipt or {}).get("violations") or []:
        if not isinstance(v, dict):
            continue
        rule = v.get("id") or v.get("rule") or "unknown"
        target = v.get("target") or v.get("selector") or ""
        out[f"{rule}|{target}"] = {
            "rule": rule,
            "target": target,
            "impact": (v.get("impact") or "minor").lower(),
        }
    return out


def _date_of(receipt):
    return (receipt or {}).get("audit_date") or (receipt or {}).get("date") or ""


def build_due_diligence(receipts):
    """Build the due-diligence record from an ordered list of receipts (oldest first).

    Returns a dict. Raises ValueError on empty input.
    """
    if not receipts:
        raise ValueError("at least one receipt is required to build a due-diligence record")
    chain = [r for r in receipts if isinstance(r, dict)]
    if not chain:
        raise ValueError("no valid receipt dicts supplied")
    chain = sorted(chain, key=lambda r: _date_of(r) or "")

    timeline = []
    for r in chain:
        c = _counts(r)
        timeline.append({
            "audit_date": _date_of(r),
            "counts": c,
            "total": _total(c),
            "accessdoc_version": r.get("accessdoc_version", ""),
        })

    first, last = _fingerprints(chain[0]), _fingerprints(chain[-1])
    remediated = sorted(set(first) - set(last))
    persisting = sorted(set(first) & set(last))
    introduced = sorted(set(last) - set(first))

    first_c, last_c = _counts(chain[0]), _counts(chain[-1])
    blocking_before = first_c["critical"] + first_c["serious"]
    blocking_after = last_c["critical"] + last_c["serious"]

    return {
        "schema_version": DUE_DILIGENCE_SCHEMA_VERSION,
        "audits_in_record": len(chain),
        "period_start": _date_of(chain[0]),
        "period_end": _date_of(chain[-1]),
        "timeline": timeline,
        "knowledge_established": _date_of(chain[0]),
        "remediated_count": len(remediated),
        "persisting_count": len(persisting),
        "introduced_count": len(introduced),
        "remediated": [first[k] for k in remediated],
        "persisting": [last[k] for k in persisting],
        "introduced": [last[k] for k in introduced],
        "blocking_before": blocking_before,
        "blocking_after": blocking_after,
        "blocking_delta": blocking_after - blocking_before,
        "trend": (
            "improving" if blocking_after < blocking_before
            else "regressing" if blocking_after > blocking_before
            else "flat"
        ),
    }


def render_due_diligence_md(record):
    """Render the record as reviewer-facing Markdown. Claims stay defensible."""
    L = []
    a = L.append
    a("# Due-Diligence Record")
    a("")
    a("> **What this is.** An append-only record of accessibility barriers detected")
    a("> and remediated over time, assembled from tamper-evident AccessDoc receipts.")
    a("> It is intended to evidence *awareness* and *reasonable steps taken*.")
    a(">")
    a("> **What this is NOT.** It is not a conformance claim, not a legal opinion,")
    a("> and not proof of WCAG compliance. Automated scanning detects roughly")
    a("> 30-57% of WCAG issues; absence of findings is not evidence of conformance.")
    a("")
    a(f"- Audits in record: **{record['audits_in_record']}**")
    a(f"- Period: **{record['period_start'] or 'n/a'}** to **{record['period_end'] or 'n/a'}**")
    a(f"- Knowledge established (first recorded detection): **{record['knowledge_established'] or 'n/a'}**")
    a(f"- Trend in blocking issues (critical + serious): **{record['trend']}** "
      f"({record['blocking_before']} -> {record['blocking_after']})")
    a("")
    a("## Timeline")
    a("")
    a("| Audit date | Critical | Serious | Moderate | Minor | Total |")
    a("|---|---|---|---|---|---|")
    for t in record["timeline"]:
        c = t["counts"]
        a(f"| {t['audit_date'] or 'n/a'} | {c['critical']} | {c['serious']} "
          f"| {c['moderate']} | {c['minor']} | {t['total']} |")
    a("")
    a("## Actions evidenced")
    a("")
    a(f"- **Remediated** (present at start, absent at end): {record['remediated_count']}")
    a(f"- **Still present** (unresolved across the period): {record['persisting_count']}")
    a(f"- **Newly introduced** (absent at start, present at end): {record['introduced_count']}")
    a("")
    if record["persisting"]:
        a("### Unresolved barriers")
        a("")
        a("These were known at the start of the period and remain present. "
          "An explanation of why they are outstanding strengthens the record.")
        a("")
        for v in record["persisting"][:50]:
            a(f"- `{v['rule']}` ({v['impact']}) - `{v['target'] or 'n/a'}`")
        a("")
    if record["introduced"]:
        a("### Regressions introduced during the period")
        a("")
        for v in record["introduced"][:50]:
            a(f"- `{v['rule']}` ({v['impact']}) - `{v['target'] or 'n/a'}`")
        a("")
    a("---")
    a("")
    a("Each audit in this record is backed by a signed-ready in-toto attestation and "
      "a SHA-256 manifest. Any edit to a prior report breaks the hash chain.")
    return "\n".join(L) + "\n"
