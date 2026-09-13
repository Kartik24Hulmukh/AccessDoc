"""Parse raw axe-core JSON into AuditSummary + AuditViolation list.

Hardened: rejects non-object payloads, tolerates null arrays, and never
crashes on missing/odd fields.

Schema 1.2: extracts axe node targets, normalizes them deterministically,
and emits one AuditViolation per unique normalized target. Violations with
no usable target get a deterministic fallback identity.
"""
import json
import hashlib
import re
from .models import AuditSummary, AuditViolation
from .catalog import get_wcag_scs
from .limits import (
    enforce_axe_limits,
    enforce_scanner_input_size,
)

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
        return text[:_TARGET_MAX_LEN - 65] + "~" + hashlib.sha256(text.encode()).hexdigest()
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
    def valid(value, depth=0):
        if value is None or isinstance(value, str):
            return True
        return (isinstance(value, list) and depth < 2
                and all(valid(item, depth + 1) for item in value))
    if not valid(raw):
        raise ValueError("node target must be a string or nested list of strings (depth <= 2)")
    return _normalize_target_value(raw)


def _str_or_empty(value, index, field):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"violations[{index}].{field} must be a string or null")
    return value


def _array_or_empty(data, field):
    """Normalize an explicit null array while rejecting other wrong types."""
    value = data.get(field)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"'{field}' must be a list or null")
    return value


def parse_axe_json(raw, allow_oversized=None):
    if isinstance(raw, str):
        enforce_scanner_input_size(raw, allow_oversized=allow_oversized)
        data = json.loads(raw)
    else:
        data = raw
    if not isinstance(data, dict):
        raise ValueError("axe-core input must be a JSON object")

    # Every result returned by axe.run contains a violations key, including a
    # legitimate zero-violation scan. Metadata-only objects must not be sealed
    # as clean accessibility evidence. Preserve the established null-array
    # compatibility contract by normalizing an explicit null to an empty list.
    if "violations" not in data:
        raise ValueError("axe-core input must include a 'violations' list")
    violations_raw = _array_or_empty(data, "violations")
    passes_raw = _array_or_empty(data, "passes")
    incomplete_raw = _array_or_empty(data, "incomplete")
    for field, entries in (("passes", passes_raw), ("incomplete", incomplete_raw)):
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ValueError(f"{field}[{index}] must be a JSON object")
    # The parser is the shared semantic validation boundary for every surface.
    # HTTP additionally bounds the whole transport body before parsing.
    enforce_axe_limits(
        violations_raw,
        allow_oversized=allow_oversized,
        scanner_data=data,
    )
    url = data.get("url")
    if url is None:
        url = ""
    elif not isinstance(url, str):
        raise ValueError("'url' must be a string or null")
    engine = data.get("testEngine")
    if engine is None:
        engine = {}
    elif not isinstance(engine, dict):
        raise ValueError("'testEngine' must be an object or null")
    engine_ver = engine.get("version")
    if engine_ver is None:
        engine_ver = ""
    elif not isinstance(engine_ver, str):
        raise ValueError("'testEngine.version' must be a string or null")

    violations = []
    for index, v in enumerate(violations_raw):
        if not isinstance(v, dict):
            raise ValueError(f"violations[{index}] must be an object")
        rule_id = v.get("id")
        if not isinstance(rule_id, str) or not rule_id.strip():
            raise ValueError(
                f"violations[{index}].id must be a non-empty string"
            )
        rule_id = rule_id.strip()
        impact = v.get("impact")
        if impact is None or impact == "":
            impact = "unknown"
        elif not isinstance(impact, str):
            raise ValueError(
                f"violations[{index}].impact must be a string or null"
            )
        if impact not in ("critical", "serious", "moderate", "minor"):
            impact = "unknown"
        wcag_scs = get_wcag_scs(rule_id)
        nodes = v.get("nodes")
        if nodes is None:
            nodes = []
        if not isinstance(nodes, list):
            raise ValueError(
                f"violations[{index}].nodes must be a list or null"
            )
        for node_index, node in enumerate(nodes):
            if not isinstance(node, dict):
                raise ValueError(
                    f"violations[{index}].nodes[{node_index}] "
                    "must be an object"
                )

        # Extract unique normalized targets from nodes.
        seen_targets = set()
        normalized_targets = []
        for node in nodes:
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
                description=_str_or_empty(v.get("description"), index, "description"),
                help_url=_str_or_empty(v.get("helpUrl"), index, "helpUrl"),
                wcag_scs=wcag_scs,
                nodes=len(nodes),
                target=tgt,
            ))

    emitted = {"critical": 0, "serious": 0, "moderate": 0, "minor": 0,
               "unknown": 0}
    for _v in violations:
        emitted[_v.impact] = emitted.get(_v.impact, 0) + 1
    summary = AuditSummary(
        critical=emitted["critical"],
        serious=emitted["serious"],
        moderate=emitted["moderate"],
        minor=emitted["minor"],
        unknown=emitted["unknown"],
        total_violations=len(violations),
        total_passes=len(passes_raw),
        total_incomplete=len(incomplete_raw),
        url=url, engine_version=engine_ver,
    )
    return summary, violations
