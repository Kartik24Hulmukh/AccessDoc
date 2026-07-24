"""Optional scan companion: run axe-core against a live URL.

The deterministic evidence core stays stdlib-only. This module is the ONLY
part that needs a browser + axe-core, and it degrades gracefully: if Playwright
is not installed it raises ScanUnavailable with install instructions rather
than crashing an import.

Usage:
    from app.scan import run_scan, ScanUnavailable
    axe_json = run_scan("https://example.com")   # returns axe-core result dict

Install extras:
    pip install playwright && playwright install chromium
"""
import json
import os

# axe-core UMD is fetched from a CDN at scan time OR loaded from a local path
# via ACCESSDOC_AXE_PATH. We never bundle axe-core source (license hygiene).
AXE_CDN = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.11.2/axe.min.js"


class ScanUnavailable(RuntimeError):
    """Raised when the optional scan dependencies are not available."""


def _load_axe_source():
    local = os.environ.get("ACCESSDOC_AXE_PATH")
    if local and os.path.exists(local):
        with open(local, "r", encoding="utf-8") as f:
            return f.read()
    return None  # signal: inject from CDN via add_script_tag(url=...)


def run_scan(url, timeout_ms=30000):
    """Run axe-core against `url` using Playwright; return the axe result dict.

    Raises ScanUnavailable if Playwright (and a browser) are not installed.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # ImportError or environment error
        raise ScanUnavailable(
            "Playwright is not installed. Install the scan extra:\n"
            "  pip install playwright && playwright install chromium"
        ) from exc

    axe_source = _load_axe_source()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="load", timeout=timeout_ms)
            if axe_source:
                page.add_script_tag(content=axe_source)
            else:
                page.add_script_tag(url=AXE_CDN)
            result = page.evaluate(
                "async () => { return await axe.run(document, "
                "{resultTypes:['violations','passes','incomplete']}); }"
            )
            browser.close()
    except ScanUnavailable:
        raise
    except Exception as exc:
        raise ScanUnavailable(f"Scan failed for {url}: {exc}") from exc

    # Normalise into the axe JSON shape our parser expects.
    if "url" not in result:
        result["url"] = url
    if "testEngine" not in result:
        result["testEngine"] = {"name": "axe-core", "version": "4.11.2"}
    return result


def run_scan_json(url, timeout_ms=30000):
    """Convenience wrapper returning a JSON string."""
    return json.dumps(run_scan(url, timeout_ms))
