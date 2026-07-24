"""Merge human (manual) accessibility findings into the automated finding set.

This is the feature that turns AccessDoc from "automated half" into a complete
audit deliverable: an auditor pastes their manual findings (CSV, Markdown
table, or a list of dicts) and they are merged, provenance-labeled
(source="manual"), and attested alongside the automated ones.

Accepted input shapes for parse_manual_findings():
  * list[dict]  keys: id, impact, description, help_url?, wcag_scs?, nodes?
  * CSV string  header row with columns: id,impact,description,wcag_scs,...
  * Markdown table string  (| id | impact | description | wcag_scs |)
"""
import csv
import io
from .models import AuditViolation, SOURCE_MANUAL

_VALID_IMPACTS = {"critical", "serious", "moderate", "minor"}


def _norm_impact(value):
    v = (value or "").strip().lower()
    return v if v in _VALID_IMPACTS else "moderate"


def _split_scs(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(s).strip() for s in value if str(s).strip()]
    parts = str(value).replace(";", ",").split(",")
    return [p.strip() for p in parts if p.strip()]


def _row_to_violation(row):
    return AuditViolation(
        id=str(row.get("id") or row.get("rule") or "manual-finding").strip(),
        impact=_norm_impact(row.get("impact")),
        description=str(row.get("description") or row.get("desc") or "").strip(),
        help_url=str(row.get("help_url") or row.get("helpUrl") or "").strip(),
        wcag_scs=_split_scs(row.get("wcag_scs") or row.get("wcag") or row.get("sc")),
        nodes=int(row.get("nodes") or 0) if str(row.get("nodes") or "").strip().isdigit() else 0,
        source=SOURCE_MANUAL,
    )


def _parse_markdown_table(text):
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip().startswith("|")]
    if len(lines) < 2:
        return []
    header = [c.strip().lower() for c in lines[0].strip("|").split("|")]
    rows = []
    for ln in lines[1:]:
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if set("".join(cells)) <= set("-: "):  # separator row
            continue
        if len(cells) < len(header):
            cells += [""] * (len(header) - len(cells))
        rows.append(dict(zip(header, cells)))
    return rows


def parse_manual_findings(data):
    """Parse manual findings from list/CSV/Markdown into AuditViolation list."""
    if not data:
        return []
    if isinstance(data, list):
        return [_row_to_violation(r) for r in data if isinstance(r, dict)]
    if isinstance(data, str):
        stripped = data.strip()
        if stripped.startswith("|"):
            return [_row_to_violation(r) for r in _parse_markdown_table(stripped)]
        # treat as CSV
        reader = csv.DictReader(io.StringIO(stripped))
        return [_row_to_violation(r) for r in reader]
    return []


def merge_findings(automated, manual, summary):
    """Append manual findings, update summary counts + manual_findings tally."""
    merged = list(automated) + list(manual)
    impact_counts = {"critical": 0, "serious": 0, "moderate": 0, "minor": 0}
    for v in merged:
        impact_counts[v.impact] = impact_counts.get(v.impact, 0) + 1
    summary.critical = impact_counts["critical"]
    summary.serious = impact_counts["serious"]
    summary.moderate = impact_counts["moderate"]
    summary.minor = impact_counts["minor"]
    summary.total_violations = len(merged)
    summary.manual_findings = sum(1 for v in merged if v.source == SOURCE_MANUAL)
    return merged
