"""Self-accessibility regression test.

Generates report.html and vpat-draft.html from the sample fixture and runs
axe-core against them via Playwright. Asserts zero critical/serious violations.

This test requires Playwright + chromium. It is skipped if Playwright is not
installed, but SHOULD be run in CI.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.service import build_artifacts

_FIXTURE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "fixtures", "axe-sample.json",
)

# Impact levels we treat as must-fix.
_BLOCKING_IMPACTS = {"critical", "serious"}


def _has_playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return True
    except Exception:
        return False


@unittest.skipUnless(_has_playwright(), "Playwright not installed")
class TestSelfAccessibility(unittest.TestCase):
    """AccessDoc's own HTML outputs must be accessible."""

    @classmethod
    def setUpClass(cls):
        with open(_FIXTURE) as f:
            axe_json = f.read()
        body = {
            "scanner_input": axe_json,
            "client_name": "Self-Audit Test",
            "include_vpat": True,
        }
        cls.artifacts = build_artifacts(body)
        cls.report_html = cls.artifacts.html_bytes.decode()
        cls.vpat_html = cls.artifacts.vpat_html

    def _run_axe(self, html_content):
        """Run axe-core against an HTML string; return violations list."""
        import tempfile, time
        from playwright.sync_api import sync_playwright

        # Write to temp file so Playwright can load it
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False, encoding="utf-8"
        ) as f:
            f.write(html_content)
            tmp_path = f.name

        try:
            # Try local axe-core file first, then CDN fallback
            axe_source = None
            axe_path = os.environ.get("ACCESSDOC_AXE_PATH", "")
            if axe_path and os.path.exists(axe_path):
                with open(axe_path, "r") as af:
                    axe_source = af.read()

            # Also try common locations
            if not axe_source:
                for candidate in [
                    "/home/user/axe-core.min.js",
                    os.path.join(os.path.dirname(__file__), "..", "node_modules", "axe-core", "axe.min.js"),
                ]:
                    candidate = os.path.abspath(candidate)
                    if os.path.exists(candidate):
                        with open(candidate, "r") as af:
                            axe_source = af.read()
                        break

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(f"file://{tmp_path}", wait_until="load", timeout=10000)
                if axe_source:
                    page.add_script_tag(content=axe_source)
                else:
                    page.add_script_tag(
                        url="https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.11.2/axe.min.js"
                    )
                time.sleep(1)
                result = page.evaluate(
                    "async () => { try { return await axe.run(document, "
                    "{resultTypes:['violations']}); } catch(e) { return {error: e.message}; } }"
                )
                browser.close()

            if isinstance(result, dict) and "error" in result:
                self.fail(f"axe.run failed: {result['error']}")
            return result.get("violations", [])
        finally:
            os.unlink(tmp_path)

    def test_report_html_no_blocking_violations(self):
        """report.html must have zero critical/serious axe violations."""
        violations = self._run_axe(self.report_html)
        blocking = [v for v in violations if v.get("impact") in _BLOCKING_IMPACTS]
        if blocking:
            msgs = []
            for v in blocking:
                msgs.append(
                    f"  [{v.get('impact')}] {v.get('id')}: {v.get('description', '')}"
                )
            self.fail(
                f"report.html has {len(blocking)} blocking axe violations:\n"
                + "\n".join(msgs)
            )

    def test_vpat_html_no_blocking_violations(self):
        """vpat-draft.html must have zero critical/serious axe violations."""
        violations = self._run_axe(self.vpat_html)
        blocking = [v for v in violations if v.get("impact") in _BLOCKING_IMPACTS]
        if blocking:
            msgs = []
            for v in blocking:
                msgs.append(
                    f"  [{v.get('impact')}] {v.get('id')}: {v.get('description', '')}"
                )
            self.fail(
                f"vpat-draft.html has {len(blocking)} blocking axe violations:\n"
                + "\n".join(msgs)
            )

    def test_report_html_has_main_landmark(self):
        """report.html must contain a <main> element."""
        self.assertIn("<main>", self.report_html)

    def test_report_html_has_scoped_headers(self):
        """report.html table headers must have scope attributes."""
        self.assertIn("scope='col'", self.report_html)

    def test_vpat_html_has_main_landmark(self):
        """vpat-draft.html must contain a <main> element."""
        self.assertIn("<main>", self.vpat_html)

    def test_vpat_html_has_scoped_headers(self):
        """vpat-draft.html table headers must have scope attributes."""
        self.assertIn('scope="col"', self.vpat_html)


if __name__ == "__main__":
    unittest.main()
