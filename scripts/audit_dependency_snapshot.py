#!/usr/bin/env python3
"""Fail closed unless pip-audit covered every exact post-install snapshot row.

The caller runs pinned pip-audit in an isolated tool environment and supplies
its raw JSON. This validator performs no network calls or dependency installs.
"""
import argparse
import json
import re
import sys
from pathlib import Path


class AuditFailure(ValueError):
    """The audit is incomplete, malformed, skipped, or reports an advisory."""


def _name(value):
    return re.sub(r"[-_.]+", "-", value).lower()


def parse_audit_json(text):
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise AuditFailure("Audit JSON contains a duplicate object key")
            result[key] = value
        return result

    def invalid_constant(value):
        raise AuditFailure("Audit JSON contains a non-finite value")

    return json.loads(text, object_pairs_hook=object_pairs,
                      parse_constant=invalid_constant)


def validate_audit(snapshot, payload):
    if not isinstance(snapshot, str):
        raise AuditFailure("Snapshot is not text")
    expected = {}
    for raw in snapshot.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;<>=!@]+)", line)
        if not match:
            raise AuditFailure("Snapshot must contain only exact name==version rows")
        name, version = _name(match[1]), match[2]
        if name in expected:
            raise AuditFailure("Snapshot contains a duplicate normalized package")
        expected[name] = version
    if not expected:
        raise AuditFailure("Snapshot is empty")
    if not isinstance(payload, dict) or "error" in payload:
        raise AuditFailure("Audit output is not a successful JSON object")
    rows = payload.get("dependencies")
    if not isinstance(rows, list):
        raise AuditFailure("Audit output lacks a dependency list")
    seen = {}
    advisory_records = 0
    for row in rows:
        if not isinstance(row, dict):
            raise AuditFailure("Malformed audit dependency row")
        if "skip_reason" in row:
            raise AuditFailure("Audit skipped a package")
        name, version = row.get("name"), row.get("version")
        if not isinstance(name, str) or not name or not isinstance(version, str) or not version:
            raise AuditFailure("Audit package identity or version is missing/unqueryable")
        name = _name(name)
        if name in seen:
            raise AuditFailure("Audit contains a duplicate normalized package")
        seen[name] = version
        vulns = row.get("vulns")
        if not isinstance(vulns, list):
            raise AuditFailure("Audit package lacks a vulnerability result list")
        advisory_records += len(vulns)
    if seen != expected:
        raise AuditFailure("Audit package/version coverage differs from the exact snapshot")
    if advisory_records:
        raise AuditFailure("Audit reported %d advisory record(s)" % advisory_records)
    return {"packages": len(expected), "advisory_records": 0, "skipped": 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--audit-json", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = validate_audit(args.snapshot.read_text(encoding="utf-8"),
                                parse_audit_json(args.audit_json.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, ValueError) as error:
        print("Audit gate failed: %s" % error, file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
