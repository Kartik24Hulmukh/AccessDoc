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
from .limits import MAX_MANUAL_FINDINGS, MAX_NODES_PER_VIOLATION, LimitExceeded

_VALID_IMPACTS = {"critical", "serious", "moderate", "minor"}
_MANUAL_NO_TARGET = "manual:no-target"
_ROW_FIELDS = frozenset({
    "id", "rule", "impact", "description", "desc", "help_url", "helpUrl",
    "wcag_scs", "wcag", "sc", "nodes", "target", "selector",
})


def _norm_impact(value):
    if value is not None and not isinstance(value, str):
        raise ValueError("manual finding impact must be a string or null")
    v = (value or "").strip().lower()
    return v if v in _VALID_IMPACTS else "moderate"


def _split_scs(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(s).strip() for s in value if str(s).strip()]
    parts = str(value).replace(";", ",").split(",")
    return [p.strip() for p in parts if p.strip()]


def _node_count(value):
    """Optional bounded count: integers or ASCII decimal cells, never bools.

    Test the decimal length before conversion so interpreter integer-string
    limits cannot leak cell contents or change the public error contract.
    """
    if value is None:
        return 0
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return 0
        if not value.isascii() or not value.isdecimal():
            raise ValueError("Invalid manual finding node count")
        value = value.lstrip("0") or "0"
        if len(value) > len(str(MAX_NODES_PER_VIOLATION)):
            raise LimitExceeded("Manual finding node count exceeds limit",
                                limit_name="MAX_NODES_PER_VIOLATION",
                                limit=MAX_NODES_PER_VIOLATION)
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("Invalid manual finding node count")
    if value > MAX_NODES_PER_VIOLATION:
        raise LimitExceeded("Manual finding node count exceeds limit",
                            limit_name="MAX_NODES_PER_VIOLATION",
                            limit=MAX_NODES_PER_VIOLATION)
    return value


def _row_to_violation(row):
    target = str(row.get("target") or row.get("selector") or "").strip()
    if not target:
        target = _MANUAL_NO_TARGET
    return AuditViolation(
        id=str(row.get("id") or row.get("rule") or "manual-finding").strip(),
        impact=_norm_impact(row.get("impact")),
        description=str(row.get("description") or row.get("desc") or "").strip(),
        help_url=str(row.get("help_url") or row.get("helpUrl") or "").strip(),
        wcag_scs=_split_scs(row.get("wcag_scs") or row.get("wcag") or row.get("sc")),
        nodes=_node_count(row.get("nodes")),
        source=SOURCE_MANUAL,
        target=target,
    )


def _column_indexes(header):
    # Last duplicate header wins, matching DictReader. Ignored columns never
    # create thousands of padded dictionary entries for each narrow row.
    return {name: i for i, name in enumerate(header) if name in _ROW_FIELDS}


def _project_cells(cells, indexes):
    return {name: cells[i] if i < len(cells) else None
            for name, i in indexes.items()}


def _parse_markdown_table(text):
    indexes = None
    for line in io.StringIO(text, newline=None):
        ln = line.strip()
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if indexes is None:
            indexes = _column_indexes([c.lower() for c in cells])
            continue
        if set("".join(cells)) <= set("-: "):  # separator row
            continue
        yield _project_cells(cells, indexes)


def _parse_csv(text):
    try:
        reader = csv.reader(io.StringIO(text, newline=None), strict=True)
        indexes = _column_indexes(next(reader, []))
        for cells in reader:
            if cells:  # DictReader ignores blank lines.
                yield _project_cells(cells, indexes)
    except csv.Error as exc:
        # The C parser's implicit field ceiling is a resource boundary too.
        # Translate both header and lazy-iteration faults into the adapters'
        # validation contracts; never echo a private cell or raw exception.
        if "field larger than field limit" in str(exc):
            raise LimitExceeded("Manual CSV field exceeds parsing limit",
                                limit_name="CSV_FIELD_SIZE_LIMIT",
                                limit=csv.field_size_limit()) from None
        raise ValueError("Invalid manual findings CSV") from None


def _bounded_findings(rows):
    findings = []
    for index, row in enumerate(rows):
        if index >= MAX_MANUAL_FINDINGS:
            raise LimitExceeded("too many manual findings",
                                limit_name="MAX_MANUAL_FINDINGS",
                                limit=MAX_MANUAL_FINDINGS, actual=index + 1)
        findings.append(_row_to_violation(row))
    return findings


def parse_manual_findings(data):
    """Parse manual findings from list/CSV/Markdown into AuditViolation list."""
    if not data:
        return []
    if isinstance(data, list):
        if len(data) > MAX_MANUAL_FINDINGS:
            raise LimitExceeded("too many manual findings")
        if any(not isinstance(r, dict) for r in data):
            raise ValueError("manual findings entries must be objects")
        return [_row_to_violation(r) for r in data]
    if isinstance(data, str):
        stripped = data.strip()
        if stripped.startswith("|"):
            return _bounded_findings(_parse_markdown_table(stripped))
        # treat as CSV
        return _bounded_findings(_parse_csv(stripped))
    raise ValueError("manual_findings must be a list, CSV or Markdown string")


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
    summary.unknown = impact_counts.get("unknown", 0)
    summary.total_violations = len(merged)
    summary.manual_findings = sum(1 for v in merged if v.source == SOURCE_MANUAL)
    return merged
