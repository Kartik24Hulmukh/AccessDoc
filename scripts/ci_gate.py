#!/usr/bin/env python3
"""AccessDoc CI Gate. Exit 0=pass, 1=violations at threshold, 2=error."""
import argparse
import io
import json
import os
import sys
import zipfile

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


def _maybe_read(path):
    if not path:
        return None
    try:
        with open(path) as f:
            return f.read()
    except OSError as exc:
        print(f"ERROR: cannot read {path}: {exc}", file=sys.stderr)
        sys.exit(2)


def main():
    parser = argparse.ArgumentParser(description="AccessDoc CI gate")
    parser.add_argument("--axe-json", required=True)
    parser.add_argument("--output-dir", default="./dist")
    parser.add_argument("--fail-on", default="critical",
                        choices=["critical", "high", "medium", "none"])
    parser.add_argument("--client-name", default="CI Audit")
    parser.add_argument("--audit-date", default="")
    parser.add_argument("--sarif", action="store_true")
    parser.add_argument("--vpat", action="store_true")
    parser.add_argument("--eaa", action="store_true")
    parser.add_argument("--manual-findings", default="")
    parser.add_argument("--prior-receipt", default="")
    args = parser.parse_args()

    axe = _maybe_read(args.axe_json)
    if axe is None:
        sys.exit(2)
    manual = _maybe_read(args.manual_findings)
    prior = _maybe_read(args.prior_receipt)

    try:
        body = {"scanner_input": axe, "client_name": args.client_name,
                "audit_date": args.audit_date, "include_sarif": args.sarif,
                "include_vpat": args.vpat, "include_eaa": args.eaa}
        if manual:
            body["manual_findings"] = manual
        if prior:
            body["prior_receipt"] = prior
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

    if args.sarif and artifacts.sarif_json:
        sarif_path = os.path.join(args.output_dir, "findings.sarif.json")
        with open(sarif_path, "w", encoding="utf-8") as f:
            f.write(artifacts.sarif_json)
        print(f"SARIF written to {sarif_path}")

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        receipt = json.loads(z.read("receipt.json"))
    summary = receipt.get("summary", {})
    print("Summary:", json.dumps(summary, indent=2))

    blocking = THRESHOLD_MAP.get(args.fail_on, [])
    if not blocking:
        print("fail-on=none - always passing")
        sys.exit(0)
    if any(summary.get(i, 0) > 0 for i in blocking):
        print(f"FAIL: violations found at threshold '{args.fail_on}'", file=sys.stderr)
        sys.exit(1)
    print(f"PASS: no violations at threshold '{args.fail_on}'")
    sys.exit(0)


if __name__ == "__main__":
    main()
