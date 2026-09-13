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


def auth_error(headers):
    key = os.getenv("ACCESSDOC_API_KEY", "")
    required = os.getenv("ACCESSDOC_REQUIRE_AUTH", "false").lower() == "true"
    if not key:
        return (503, "AUTH_NOT_CONFIGURED") if required else None
    values = headers.get_all("Authorization") or []
    expected = ("Bearer " + key).encode("utf-8")
    if len(values) != 1 or not hmac.compare_digest(values[0].encode("utf-8"), expected):
        return 401, "UNAUTHORIZED"
    return None


def public_body(body):
    if not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object")
    # Do not inherit ACCESSDOC_ALLOW_OVERSIZED from a CLI-oriented deployment.
    parse_axe_json(body.get("scanner_input"), allow_oversized=False)
    return {key: body[key] for key in PUBLIC_KEYS if key in body}
