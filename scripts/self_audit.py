"""Run axe-core self-audit against AccessDoc's own report.html and vpat-draft.html."""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.service import build_artifacts

def load_axe_source() -> str:
    candidates = [
        os.environ.get("ACCESSDOC_AXE_PATH", ""),
        str(ROOT / "node_modules" / "axe-core" / "axe.min.js"),
        "/home/user/axe-core.min.js",
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return Path(c).read_text(encoding="utf-8")
    raise RuntimeError("axe-core JS not found. Run 'npm install axe-core'.")

def audit_html(page, html_content: str, axe_src: str, viewport_width: int = 1280) -> dict:
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html_content)
        tmp_path = f.name
    try:
        page.set_viewport_size({"width": viewport_width, "height": 800})
        page.goto(Path(tmp_path).as_uri(), wait_until="load", timeout=10000)
        page.add_script_tag(content=axe_src)
        result = page.evaluate("async () => await axe.run(document)")
        return result
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

def main():
    stress_fixture = ROOT / "fixtures" / "axe-stress.json"
    body = {
        "scanner_input": stress_fixture.read_text(encoding="utf-8"),
        "client_name": "Self-Audit-Client",
        "include_vpat": True,
        "include_sarif": True,
        "include_eaa": True,
    }
    artifacts = build_artifacts(body)
    report_html = artifacts.html_bytes.decode("utf-8")
    vpat_html = artifacts.vpat_html

    axe_src = load_axe_source()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        report_result = audit_html(page, report_html, axe_src)
        report_reflow = audit_html(page, report_html, axe_src, viewport_width=320)
        vpat_result = audit_html(page, vpat_html, axe_src) if vpat_html else {}
        vpat_reflow = audit_html(page, vpat_html, axe_src, viewport_width=320) if vpat_html else {}

        browser.close()

    audit_output = {
        "report_html": report_result,
        "report_html_320px": report_reflow,
        "vpat_draft_html": vpat_result,
        "vpat_draft_html_320px": vpat_reflow,
    }

    out_file = ROOT / "axe-self-audit.json"
    out_file.write_text(json.dumps(audit_output, indent=2), encoding="utf-8")
    print(f"Archived axe JSON audit output to {out_file.name}")

    all_violations = (
        report_result.get("violations", []) +
        report_reflow.get("violations", []) +
        vpat_result.get("violations", []) +
        vpat_reflow.get("violations", [])
    )

    impacts = {"critical": 0, "serious": 0, "moderate": 0, "minor": 0}
    for v in all_violations:
        imp = v.get("impact", "minor")
        impacts[imp] = impacts.get(imp, 0) + 1

    print("=== AXE-CORE SELF-AUDIT RESULTS ===")
    print(f"Total violations found: {len(all_violations)}")
    print(f"  Critical: {impacts['critical']}")
    print(f"  Serious:  {impacts['serious']}")
    print(f"  Moderate: {impacts['moderate']}")
    print(f"  Minor:    {impacts['minor']}")

    if impacts["critical"] > 0 or impacts["serious"] > 0:
        print(f"FAIL: Found {impacts['critical']} critical and {impacts['serious']} serious violations.")
        sys.exit(1)

    print("PASS: Zero critical and zero serious violations.")
    sys.exit(0)

if __name__ == "__main__":
    main()
