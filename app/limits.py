"""Bounded input limits for every AccessDoc surface (API, CLI, CI, MCP).

Every value is a hard ceiling. Inputs at or below these limits are accepted;
anything above is rejected with a 413 (HTTP) or LimitExceeded (internal) before
expensive work begins. The goal is to prevent resource exhaustion from hostile
or accidentally-large payloads while leaving generous headroom for real audits.

Parity contract (beta.5+)
-------------------------
Before beta.5 these ceilings were enforced ONLY by the public HTTP handler, so
the CLI silently accepted payloads the API rejected. That is a validation
contract split: two surfaces of the same product disagreed about what a valid
audit input is. `enforce_axe_limits()` is now called from `parse_axe_json()`,
which every surface goes through, so the contract is single-sourced.

Operators who genuinely need to process an oversized local corpus can opt out
explicitly and audibly:

    accessdoc bundle huge.json --allow-oversized      # CLI flag
    ACCESSDOC_ALLOW_OVERSIZED=1 accessdoc bundle ...  # environment

The opt-out is deliberately unavailable to the HTTP API: the public surface has
no mechanism to set it, so no remote caller can lift the ceilings.
"""
import os

MAX_HTTP_BODY_BYTES = 2 * 1024 * 1024          # 2 MiB total request body
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


def enforce_axe_limits(violations_raw, allow_oversized=None):
    """Enforce the shared ceilings on a parsed axe `violations` list.

    Args:
        violations_raw: the raw `violations` list from axe-core JSON.
        allow_oversized: tri-state. None consults the environment opt-out;
            True skips enforcement; False forces enforcement regardless of the
            environment (used by the HTTP surface).

    Raises:
        LimitExceeded: when any ceiling is exceeded.
    """
    if allow_oversized is None:
        allow_oversized = oversized_allowed()
    if allow_oversized:
        return
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
