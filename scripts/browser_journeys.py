#!/usr/bin/env python3
"""120 synthetic browser journey checks; not 120 human participants.
Run against a local adapter: python scripts/browser_journeys.py --output results.json
Requires Playwright + installed Chromium. Never load-tests a public target.
"""
import argparse
import re
import json
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.bundle import validate_bundle

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--output", required=True)
    parser.add_argument("--profiles", type=int, default=20, choices=range(1, 121),
                        help="Synthetic profile count (1-120); never human participants")
    args = parser.parse_args()
    if urlparse(args.base).hostname not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("Only loopback targets are supported")
    results = []
    with sync_playwright() as p, tempfile.TemporaryDirectory() as tmp:
        browser = p.chromium.launch(args=["--no-sandbox"])
        try:
            for profile in range(args.profiles):
                width = [320, 375, 768, 1280][profile % 4]
                locale = ["en-US", "ar", "ja-JP", "de-DE", "hi-IN"][(profile // 4) % 5]
                ctx = browser.new_context(viewport={"width": width, "height": [640, 720, 800, 900, 1080][(profile // 20) % 5]}, locale=locale,
                                          reduced_motion="reduce" if profile % 2 else "no-preference")
                page = ctx.new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(args.base)
                page.locator("#client").fill("Human journey — 日本語 العربية 👩🏽‍💻")
                page.locator("#agency").fill("QA agency")
                upload = page.locator("#evidence-file")
                scanner = page.locator("#scanner")
                def download():
                    with page.expect_download(timeout=20000) as event:
                        page.locator("#generate").click()
                    target = Path(tmp) / "bundle.zip"
                    event.value.save_as(target)
                    assert validate_bundle(target.read_bytes())["valid"]
                    assert not errors, errors
                def check(name, fn):
                    start = time.monotonic()
                    try:
                        fn()
                        row = {"status": "PASS"}
                    except Exception as e:
                        row = {"status": "FAIL", "error": str(e)[:500]}
                    row.update(profile=profile, width=width, locale=locale, journey=name,
                               ms=round((time.monotonic()-start)*1000, 1))
                    results.append(row)
                def file_only():
                    upload.set_input_files(str(ROOT / "fixtures/axe-sample.json"))
                    assert scanner.input_value() == ""
                    download()
                check("file-only Unicode client to verified ZIP", file_only)
                check("immediate resubmission to verified ZIP", download)
                def corrupt():
                    upload.set_input_files({"name": "broken.json", "mimeType": "application/json", "buffer": b"{broken"})
                    page.locator("#generate").click()
                    page.locator("#errors").wait_for(state="visible")
                    assert not page.locator("#generate").is_disabled()
                check("corrupt file recoverable error", corrupt)
                def oversize():
                    upload.set_input_files({"name": "large.json", "mimeType": "application/json", "buffer": b"x"*2000001})
                    page.locator("#generate").click()
                    page.locator("#errors").wait_for(state="visible")
                    assert "File exceeds" in page.locator("#errors").inner_text()
                check("oversize local rejection", oversize)
                def clear():
                    upload.set_input_files([])
                    assert scanner.get_attribute("required") is not None
                    assert page.locator("#file-name").inner_text() == "No file selected"
                check("clear file restores mandatory evidence", clear)
                def sample():
                    page.locator("#sample").click()
                    scanner.wait_for(state="visible")
                    expect(scanner).to_have_value(re.compile(r".+", re.S))
                    download()
                check("sample recovery after invalid uploads", sample)
                ctx.close()
        finally:
            browser.close()
    report = {"scope": f"{args.profiles} synthetic viewport/locale/height profiles x 6 journeys; no human participants",
              "checks": len(results), "passed": sum(r["status"] == "PASS" for r in results), "results": results}
    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k != "results"}))
    return int(report["passed"] != args.profiles * 6)

if __name__ == "__main__":
    raise SystemExit(main())
