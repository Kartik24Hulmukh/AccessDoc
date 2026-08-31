"""Parse raw axe-core JSON into AuditSummary + AuditViolation list.

Hardened: rejects non-object payloads, tolerates null arrays, and never
crashes on missing/odd fields.

Schema 1.2: extracts axe node targets, normalizes them deterministically,
and emits one AuditViolation per unique normalized target. Violations with
no usable target get a deterministic fallback identity.
"""
import json
import re
from .models import AuditSummary, AuditViolation
from .catalog import get_wcag_scs
from .limits import enforce_axe_limits

# --- Target normalization constants -----------------------------------------
_TARGET_MAX_LEN = 200
_TARGET_DELIMITER = " > "
_NO_TARGET_MARKER = "no-target"
_MANUAL_NO_TARGET = "manual:no-target"
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _normalize_target_segment(value):
    """Normalize a single target segment (string)."""
    if value is None:
        return ""
    s = str(value)
    # Remove control characters safely (preserve Unicode).
    s = _CTRL_RE.sub("", s)
    # Strip whitespace.
    s = s.strip()
    return s


def _normalize_target_value(raw):
    """Normalize a single node["target"] value into a string.

    Handles:
    - a string
    - a list of selector segments (flat)
    - a nested list for iframe/shadow DOM targeting
    - missing / malformed
    """
    if raw is None:
        return ""
    # String case.
    if isinstance(raw, str):
        return _normalize_target_segment(raw)
    # List / nested list case.
    if isinstance(raw, list):
        parts = []
        for item in raw:
            if isinstance(item, list):
                # Nested list: join inner with delimiter, then outer.
                inner = _TARGET_DELIMITER.join(
                    _normalize_target_segment(x) for x in item
                    if _normalize_target_segment(x)
                )
                if inner:
                    parts.append(inner)
            else:
                seg = _normalize_target_segment(item)
                if seg:
                    parts.append(seg)
        return _TARGET_DELIMITER.join(parts)
    # Any other type: stringify defensively.
    return _normalize_target_segment(str(raw))


def _bound_target(text):
    """Bound excessively long target text."""
    if len(text) > _TARGET_MAX_LEN:
        return text[:_TARGET_MAX_LEN]
    return text


def _fallback_target(rule_id, source):
    """Deterministic fallback identity when no usable target exists."""
    return f"{rule_id}:{_NO_TARGET_MARKER}"


def _extract_node_targets(node):
    """Extract and normalize the target from a single axe node.

    Returns the normalized target string, or "" if no usable target.
    """
    if not isinstance(node, dict):
        return ""
    raw = node.get("target")
    return _normalize_target_value(raw)


def parse_axe_json(raw):
    data = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(data, dict):
        raise ValueError("axe-core input must be a JSON object")
    recognizable = {"violations", "passes", "incomplete", "testEngine", "url"}
    if not any(key in data for key in recognizable):
        raise ValueError(
            "axe-core input must include recognizable axe result fields "
            "(for example: violations/passes/incomplete/testEngine/url)"
        )

    violations_raw = data.get("violations") or []
    passes_raw     = data.get("passes") or []
    incomplete_raw = data.get("incomplete") or []
    if not isinstance(violations_raw, list):
        raise ValueError("'violations' must be a list")
    # Single-sourced bounded-input contract: every surface (HTTP API, CLI, CI
    # gate, MCP) funnels through this parser, so the ceilings in app/limits.py
    # now apply identically everywhere. The HTTP handler additionally rejects
    # oversized payloads earlier, before the body is even parsed.
    enforce_axe_limits(violations_raw)
    url            = data.get("url") or ""
    engine         = data.get("testEngine") or {}
    engine_ver     = (engine.get("version") if isinstance(engine, dict) else "") or ""

    impact_counts = {"critical": 0, "serious": 0, "moderate": 0, "minor": 0}
    violations = []
    for v in violations_raw:
        if not isinstance(v, dict):
            continue
        impact = v.get("impact") or "minor"
        impact_counts[impact] = impact_counts.get(impact, 0) + 1
        rule_id = v.get("id", "")
        wcag_scs = get_wcag_scs(rule_id)
        nodes = v.get("nodes") or []

        # Extract unique normalized targets from nodes.
        seen_targets = set()
        normalized_targets = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            tgt = _extract_node_targets(node)
            tgt = _bound_target(tgt)
            if tgt and tgt not in seen_targets:
                seen_targets.add(tgt)
                normalized_targets.append(tgt)

        if not normalized_targets:
            # No usable target: emit one finding with fallback identity.
            normalized_targets = [_fallback_target(rule_id, "automated")]

        for tgt in normalized_targets:
            violations.append(AuditViolation(
                id=rule_id, impact=impact,
                description=v.get("description", ""),
                help_url=v.get("helpUrl", ""),
                wcag_scs=wcag_scs,
                nodes=len(nodes),
                target=tgt,
            ))

    summary = AuditSummary(
        critical=impact_counts.get("critical", 0),
        serious=impact_counts.get("serious", 0),
        moderate=impact_counts.get("moderate", 0),
        minor=impact_counts.get("minor", 0),
        total_violations=len(violations),
        total_passes=len(passes_raw),
        total_incomplete=len(incomplete_raw),
        url=url, engine_version=engine_ver,
    )
    return summary, violations
