"""Shared hosted boundary; local CLI options never cross this allowlist.

Authentication is optional for backwards-compatible local/demo use. Configure
ACCESSDOC_REQUIRE_AUTH=true AND ACCESSDOC_API_KEY for an authenticated pilot.
This is a single shared pilot credential, not tenant quotas or distributed limits.
"""
import hmac
import os

from .parser import parse_axe_json

PUBLIC_KEYS = (
    "scanner_input", "client_name", "agency_name", "audit_date",
    "manual_findings", "enrich", "include_sarif", "include_vpat",
    "include_eaa", "prior_receipt",
)


def auth_required():
    return bool(os.getenv("ACCESSDOC_API_KEY", "") or
                any(k.strip() for k in os.getenv("ACCESSDOC_API_KEYS", "").split(",")) or
                os.getenv("ACCESSDOC_REQUIRE_AUTH", "false").lower() == "true")


def readiness_reasons():
    """Passive, non-secret core configuration checks; no paid provider probe."""
    required = os.getenv("ACCESSDOC_REQUIRE_AUTH", "false").lower() == "true"
    keys = bool(os.getenv("ACCESSDOC_API_KEY", "") or any(
        k.strip() for k in os.getenv("ACCESSDOC_API_KEYS", "").split(",")))
    reasons = ["AUTH_NOT_CONFIGURED"] if required and not keys else []
    state = operation_state()
    reasons.extend(state["configuration_errors"])
    if not state["generation_enabled"] and "GENERATION_CONFIG_INVALID" not in reasons:
        reasons.append("GENERATION_DISABLED")
    return reasons


def operation_state():
    """Independent, passive process admission controls; never return env values."""
    result = {"configuration_errors": []}
    for name, env in (("generation", "ACCESSDOC_GENERATION_ENABLED"),
                      ("remediation", "ACCESSDOC_REMEDIATION_ENABLED")):
        value = os.getenv(env, "true").strip().lower()
        result[name + "_enabled"] = value == "true"
        if value not in ("true", "false"):
            result["configuration_errors"].append(name.upper() + "_CONFIG_INVALID")
    return result


def operation_error(remediation=False):
    """Disable new work, not already accepted jobs or fleet/account spending."""
    name = "remediation" if remediation else "generation"
    state = operation_state()
    if not state[name + "_enabled"]:
        return 503, (name.upper() + "_CONFIG_INVALID"
                     if name.upper() + "_CONFIG_INVALID" in state["configuration_errors"]
                     else name.upper() + "_DISABLED")
    return None


def auth_error(headers):
    key = os.getenv("ACCESSDOC_API_KEY", "")
    required = os.getenv("ACCESSDOC_REQUIRE_AUTH", "false").lower() == "true"
    legacy = [k.strip() for k in os.getenv("ACCESSDOC_API_KEYS", "").split(",") if k.strip()]
    if not key and not legacy:
        return (503, "AUTH_NOT_CONFIGURED") if required else None
    # Explicit single-key configuration takes precedence. Never silently allow
    # a legacy header to bypass a newly configured Bearer key.
    if key:
        values = headers.get_all("Authorization") or []
        if len(values) != 1 or not hmac.compare_digest(values[0].encode("utf-8"), ("Bearer " + key).encode("utf-8")):
            return 401, "UNAUTHORIZED"
    else:
        values = headers.get_all("X-API-Key") or []
        if len(values) != 1:
            return 401, "UNAUTHORIZED"
        matches = [hmac.compare_digest(values[0].encode("utf-8"), candidate.encode("utf-8")) for candidate in legacy]
        if not any(matches):
            return 401, "UNAUTHORIZED"
    return None


def public_body(body):
    if not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object")
    # Do not inherit ACCESSDOC_ALLOW_OVERSIZED from a CLI-oriented deployment.
    parse_axe_json(body.get("scanner_input"), allow_oversized=False)
    return {key: body[key] for key in PUBLIC_KEYS if key in body}


REMEDIATION_KEYS = ("scanner_input", "violations", "client_name", "model")


def remediation_body(body):
    """Boundary for POST /api/remediate: scanner_input (if present) must pass the
    same axe parser/limits as /api/generate; bare violations are checked with
    the same policy before they can reach a model. Unknown keys never cross."""
    if not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object")
    if body.get("scanner_input") is not None:
        parse_axe_json(body.get("scanner_input"), allow_oversized=False)
    if body.get("violations") is not None:
        parse_axe_json({"violations": body["violations"]}, allow_oversized=False)
    if "model" in body and body["model"] is not None and not isinstance(body["model"], str):
        raise ValueError("model must be a string")
    return {key: body[key] for key in REMEDIATION_KEYS if key in body}
