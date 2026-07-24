#!/usr/bin/env python3
"""Unified AccessDoc command-line interface."""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.service import build_artifacts
from app.bundle import build_bundle, validate_bundle


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _body_from_args(args, extra=None):
    body = {
        "scanner_input": _read(args.axe_json),
        "client_name": getattr(args, "client_name", "CLI Audit"),
        "audit_date": getattr(args, "audit_date", "") or "",
    }
    if getattr(args, "manual", None):
        body["manual_findings"] = _read(args.manual)
    if extra:
        body.update(extra)
    return body


def cmd_bundle(args):
    body = _body_from_args(args, {
        "include_sarif": args.sarif,
        "include_vpat": args.vpat,
        "include_eaa": args.eaa,
        "enrich": args.enrich,
    })
    if getattr(args, "prior", None):
        body["prior_receipt"] = _read(args.prior)
    arts = build_artifacts(body)
    data = build_bundle(arts)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "wb") as f:
        f.write(data)
    print(f"Wrote {args.out} ({len(data):,} bytes)")
    return 0


def cmd_sarif(args):
    arts = build_artifacts(_body_from_args(args, {"include_sarif": True}))
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(arts.sarif_json)
    print(f"Wrote {args.out}")
    return 0


def cmd_vpat(args):
    arts = build_artifacts(_body_from_args(args, {"include_vpat": True}))
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(arts.vpat_html)
    print(f"Wrote {args.out}")
    return 0


def cmd_eaa(args):
    arts = build_artifacts(_body_from_args(args, {"include_eaa": True}))
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(arts.eaa_markdown)
    print(f"Wrote {args.out}")
    return 0


def cmd_verify(args):
    with open(args.bundle, "rb") as f:
        data = f.read()
    result = validate_bundle(data)
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


def cmd_trend(args):
    body = {"scanner_input": _read(args.axe_json), "prior_receipt": _read(args.prior)}
    arts = build_artifacts(body)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(arts.trend_json)
    print(f"Wrote {args.out}")
    return 0


def cmd_scan(args):
    from app.scan import run_scan_json, ScanUnavailable
    try:
        out = run_scan_json(args.url)
    except ScanUnavailable as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"Wrote {args.out}")
    return 0


def cmd_catalog(args):
    from app.catalog import catalog_summary
    print(json.dumps(catalog_summary(), indent=2))
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="accessdoc", description="AccessDoc evidence CLI")
    sub = p.add_subparsers(dest="command", required=True)

    def add_common(sp):
        sp.add_argument("axe_json")
        sp.add_argument("--client-name", default="CLI Audit")
        sp.add_argument("--audit-date", default="")
        sp.add_argument("--manual", default=None)

    b = sub.add_parser("bundle")
    add_common(b)
    b.add_argument("--out", default="./dist/accessdoc-bundle.zip")
    b.add_argument("--sarif", action="store_true")
    b.add_argument("--vpat", action="store_true")
    b.add_argument("--eaa", action="store_true")
    b.add_argument("--enrich", action="store_true")
    b.add_argument("--prior", default=None)
    b.set_defaults(func=cmd_bundle)

    s = sub.add_parser("sarif")
    add_common(s)
    s.add_argument("--out", default="./findings.sarif.json")
    s.set_defaults(func=cmd_sarif)

    v = sub.add_parser("vpat")
    add_common(v)
    v.add_argument("--out", default="./vpat-draft.html")
    v.set_defaults(func=cmd_vpat)

    e = sub.add_parser("eaa")
    add_common(e)
    e.add_argument("--out", default="./eaa-evidence.md")
    e.set_defaults(func=cmd_eaa)

    ver = sub.add_parser("verify")
    ver.add_argument("bundle")
    ver.set_defaults(func=cmd_verify)

    t = sub.add_parser("trend")
    t.add_argument("prior")
    t.add_argument("axe_json")
    t.add_argument("--out", default="./trend.json")
    t.set_defaults(func=cmd_trend)

    sc = sub.add_parser("scan")
    sc.add_argument("url")
    sc.add_argument("--out", default="./axe.json")
    sc.set_defaults(func=cmd_scan)

    c = sub.add_parser("catalog")
    c.set_defaults(func=cmd_catalog)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
