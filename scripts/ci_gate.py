#!/usr/bin/env python3
"""AccessDoc CI Gate - read axe-core JSON, build bundle, exit with severity code.

Exit codes:
  0  no violations at or above threshold
  1  violations found at or above threshold
  2  error (parse failure, bundle failure, etc.)
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.service import build_artifacts
from app.bundle import build_bundle

THRESHOLD_MAP = {
    "critical": ["critical"],
    "high":     ["critical", "serious"],
    "medium":   ["critical", "serious", "moderate"],
    "none":     [],
}


def main():
    parser = argparse.ArgumentParser(description="AccessDoc CI gate")
    parser.add_argument("--axe-json",    required=True)
    parser.add_argument("--output-dir",  default="./dist")
    parser.add_argument("--fail-on",     default="critical",
                        choices=["critical", "high", "medium", "none"])
    parser.add_argument("--client-name", default="CI Audit")
    parser.add_argument("--audit-date",  default="")
    args = parser.parse_args()

    try:
        with open(args.axe_json) as f:
            axe_data = f.read()
    except OSError as exc:
        print(f"ERROR: cannot read {args.axe_json}: {exc}", file=sys.stderr)
        sys.exit(2)

    try:
        body = {
            "scanner_input": axe_data,
            "client_name":   args.client_name,
            "audit_date":    args.audit_date,
        }
        artifacts = build_artifacts(body)
        zip_bytes = build_bundle(artifacts)
    except Exception as exc:
        print(f"ERROR: build failed: {exc}", file=sys.stderr)
        sys.exit(2)

    os.makedirs(args.output_dir, exist_ok=True)
    out_path = os.path.join(args.output_dir, "accessdoc-bundle.zip")
    with open(out_path, "wb") as f:
        f.write(zip_bytes)
    print(f"Bundle written to {out_path} ({len(zip_bytes):,} bytes)")

    import zipfile, io
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        receipt = json.loads(z.read("receipt.json"))

    summary = receipt.get("summary", {})
    print("Summary:", json.dumps(summary, indent=2))

    blocking_impacts = THRESHOLD_MAP.get(args.fail_on, [])
    if not blocking_impacts:
        print("fail-on=none - always passing")
        sys.exit(0)

    violations_found = any(summary.get(impact, 0) > 0 for impact in blocking_impacts)
    if violations_found:
        print(f"FAIL: violations found at threshold '{args.fail_on}'", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"PASS: no violations at threshold '{args.fail_on}'")
        sys.exit(0)


if __name__ == "__main__":
    main()
