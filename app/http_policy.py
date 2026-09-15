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
    same axe parser/limits as /api/generate; a bare violations list is bounded by
    app.remediate. Unknown keys never cross."""
    if not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object")
    if body.get("scanner_input") is not None:
        parse_axe_json(body.get("scanner_input"), allow_oversized=False)
    if "model" in body and body["model"] is not None and not isinstance(body["model"], str):
        raise ValueError("model must be a string")
    return {key: body[key] for key in REMEDIATION_KEYS if key in body}
