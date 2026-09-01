"""Bounded input limits for every AccessDoc surface (API, CLI, CI, MCP).

Every value is a hard ceiling. Inputs at or below these limits are accepted;
anything above is rejected with a 413 (HTTP) or LimitExceeded (internal) before
expensive artifact generation. HTTP bounds the complete transport body before
parsing; the shared parser independently bounds scanner strings and arrays.

Operators who genuinely need to process an oversized local corpus can opt out
explicitly and audibly:

    accessdoc bundle huge.json --allow-oversized      # CLI flag
    ACCESSDOC_ALLOW_OVERSIZED=1 accessdoc bundle ...  # environment

The opt-out is deliberately unavailable to the HTTP API.
"""
import os

MAX_HTTP_BODY_BYTES = 2 * 1024 * 1024          # 2 MiB total request/input body
MAX_VIOLATIONS = 10_000                        # axe-core violations array
MAX_TOTAL_NODES = 100_000                      # sum of nodes across violations
MAX_NODES_PER_VIOLATION = 5_000                # nodes in a single violation
MAX_STRING_CHARS = 10_000                      # any single string field
MAX_MANUAL_FINDINGS = 5_000                    # manual findings entries
MAX_HISTORY_RECEIPTS = 50                      # receipt_history chain length
MAX_HISTORY_RECEIPT_BYTES = 1024 * 1024        # 1 MiB per prior receipt

# Name of the explicit, local-only opt-out.
OVERSIZE_ENV_VAR = "ACCESSDOC_ALLOW_OVERSIZED"


class LimitExceeded(ValueError):
    """A bounded input limit was exceeded.

    Subclasses ValueError so existing callers that catch ValueError (the HTTP
    handler, the MCP server, the CLI top level) keep behaving correctly.
    """

    def __init__(self, message, limit_name=None, limit=None, actual=None):
        super().__init__(message)
        self.limit_name = limit_name
        self.limit = limit
        self.actual = actual


def oversized_allowed():
    """True only when the operator explicitly opted out on this machine."""
    return os.environ.get(OVERSIZE_ENV_VAR, "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _oversized_is_allowed(allow_oversized):
    if allow_oversized is None:
        return oversized_allowed()
    return bool(allow_oversized)


def enforce_scanner_input_size(raw, allow_oversized=None):
    """Reject an oversized serialized scanner payload before JSON decoding."""
    if _oversized_is_allowed(allow_oversized):
        return
    if isinstance(raw, str):
        actual = len(raw.encode("utf-8"))
    elif isinstance(raw, (bytes, bytearray)):
        actual = len(raw)
    else:
        return
    if actual > MAX_HTTP_BODY_BYTES:
        raise LimitExceeded(
            f"Scanner input too large "
            f"(limit {MAX_HTTP_BODY_BYTES} bytes, got {actual})",
            limit_name="MAX_HTTP_BODY_BYTES",
            limit=MAX_HTTP_BODY_BYTES,
            actual=actual,
        )


def _enforce_string_limits(scanner_data):
    """Iteratively enforce MAX_STRING_CHARS across a parsed payload."""
    stack = [("$", scanner_data)]
    while stack:
        path, value = stack.pop()
        if isinstance(value, str):
            actual = len(value)
            if actual > MAX_STRING_CHARS:
                raise LimitExceeded(
                    f"Scanner string at {path} exceeds "
                    f"{MAX_STRING_CHARS} characters",
                    limit_name="MAX_STRING_CHARS",
                    limit=MAX_STRING_CHARS,
                    actual=actual,
                )
        elif isinstance(value, dict):
            for key, child in value.items():
                stack.append((f"{path}.{key}", child))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                stack.append((f"{path}[{index}]", child))


def enforce_axe_limits(
    violations_raw,
    allow_oversized=None,
    scanner_data=None,
):
    """Enforce the shared ceilings on parsed axe scanner evidence."""
    if _oversized_is_allowed(allow_oversized):
        return

    if scanner_data is not None:
        _enforce_string_limits(scanner_data)

    if not isinstance(violations_raw, list):
        return

    count = len(violations_raw)
    if count > MAX_VIOLATIONS:
        raise LimitExceeded(
            f"Too many violations (limit {MAX_VIOLATIONS}, got {count})",
            limit_name="MAX_VIOLATIONS", limit=MAX_VIOLATIONS, actual=count,
        )

    total_nodes = 0
    for entry in violations_raw:
        if not isinstance(entry, dict):
            continue
        nodes = entry.get("nodes") or []
        if not isinstance(nodes, list):
            continue
        n = len(nodes)
        if n > MAX_NODES_PER_VIOLATION:
            raise LimitExceeded(
                f"Too many nodes in one violation "
                f"(limit {MAX_NODES_PER_VIOLATION}, got {n})",
                limit_name="MAX_NODES_PER_VIOLATION",
                limit=MAX_NODES_PER_VIOLATION, actual=n,
            )
        total_nodes += n
        if total_nodes > MAX_TOTAL_NODES:
            raise LimitExceeded(
                f"Too many nodes across all violations "
                f"(limit {MAX_TOTAL_NODES})",
                limit_name="MAX_TOTAL_NODES",
                limit=MAX_TOTAL_NODES, actual=total_nodes,
            )


def limits_summary():
    """Machine-readable snapshot of every ceiling, for docs and /limits."""
    return {
        "max_http_body_bytes": MAX_HTTP_BODY_BYTES,
        "max_violations": MAX_VIOLATIONS,
        "max_total_nodes": MAX_TOTAL_NODES,
        "max_nodes_per_violation": MAX_NODES_PER_VIOLATION,
        "max_string_chars": MAX_STRING_CHARS,
        "max_manual_findings": MAX_MANUAL_FINDINGS,
        "max_history_receipts": MAX_HISTORY_RECEIPTS,
        "max_history_receipt_bytes": MAX_HISTORY_RECEIPT_BYTES,
        "oversize_opt_out_env_var": OVERSIZE_ENV_VAR,
        "oversize_opt_out_available_on_http": False,
    }
