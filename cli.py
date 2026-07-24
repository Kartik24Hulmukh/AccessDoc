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
    pdf_engine = getattr(args, "pdf_engine", "reportlab")
    body = _body_from_args(args, {
        "include_sarif": args.sarif,
        "include_vpat": args.vpat,
        "include_eaa": args.eaa,
        "enrich": args.enrich,
        "pdf_engine": pdf_engine,
    })
    if getattr(args, "prior", None):
        body["prior_receipt"] = _read(args.prior)
    if getattr(args, "history", None):
        hist = []
        for path in args.history:
            loaded = json.loads(_read(path))
            hist.extend(loaded if isinstance(loaded, list) else [loaded])
        body["receipt_history"] = hist
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


def cmd_doctor(args):
    """Check environment: Python version, optional deps, write permissions."""
    import platform
    import tempfile

    checks = []
    ok = 0
    warn = 0

    def _check(name, status, detail=""):
        nonlocal ok, warn
        mark = "\u2705" if status == "ok" else ("\u26a0\ufe0f" if status == "warn" else "\u274c")
        checks.append(f"  {mark} {name}: {detail}")
        if status == "ok":
            ok += 1
        elif status == "warn":
            warn += 1

    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 10):
        _check("Python", "ok", f"{py_ver} ({platform.python_implementation()})")
    else:
        _check("Python", "warn", f"{py_ver} requires >= 3.10")

    try:
        import reportlab
        _check("reportlab", "ok", f"v{reportlab.Version} - PDF generation available")
    except ImportError:
        _check("reportlab", "warn", "not installed - pip install reportlab")

    try:
        import yaml
        _check("PyYAML", "ok", f"v{yaml.__version__} - YAML validation available")
    except ImportError:
        _check("PyYAML", "warn", "not installed - pip install PyYAML")

    try:
        from playwright.sync_api import sync_playwright
        _check("playwright", "ok", "installed - scan available")
    except ImportError:
        _check("playwright", "warn", "not installed - pip install playwright")

    try:
        from weasyprint import HTML
        _check("weasyprint", "ok", "installed - tagged PDF/UA-1 available")
    except ImportError:
        _check("weasyprint", "warn", "not installed - pip install weasyprint (for tagged PDF)")

    try:
        tmp = tempfile.NamedTemporaryFile(delete=True, dir=".")
        tmp.close()
        _check("Write permission (cwd)", "ok", f"can write to {os.getcwd()}")
    except (OSError, PermissionError):
        _check("Write permission (cwd)", "warn", f"cannot write to {os.getcwd()}")

    from app.models import VERSION
    _check("AccessDoc", "ok", f"v{VERSION}")

    print("AccessDoc doctor - environment check")
    print("=" * 50)
    for line in checks:
        print(line)
    print("=" * 50)
    print(f"{ok} OK, {warn} warnings")
    if warn > 0:
        print("\nWarnings do not block core functionality (bundle generation).")
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
    b.add_argument("--history", nargs="+", default=None,
                   help="Prior receipt JSON files (oldest first) -> adds due-diligence.md "
                        "evidencing reasonable steps taken over time")
    b.add_argument("--pdf-engine", default="reportlab",
                   choices=["reportlab", "weasyprint"],
                   help="PDF engine: reportlab (default, untagged) or "
                        "weasyprint (experimental, tagged PDF/UA-1, "
                        "requires: pip install weasyprint)")
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

    d = sub.add_parser("doctor")
    d.set_defaults(func=cmd_doctor)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
