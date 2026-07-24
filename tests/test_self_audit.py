"""Self-accessibility regression test.

Generates report.html and vpat-draft.html from a STRESS fixture (65 violations
across all impact levels, long URLs, non-ASCII/RTL text) and runs axe-core
against them via Playwright.

Asserts zero violations at critical, serious AND moderate impact levels.
The moderate level is included because the bugs fixed in Phase 3
(landmark-one-main, region) were moderate — asserting only critical/serious
would not catch a regression of those fixes.

Also tests at 320px viewport width (WCAG 1.4.10 reflow).

This test requires Playwright + chromium. If Playwright is not installed,
the test is skipped with a LOUD warning printed to stderr — it must not
pass silently.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.service import build_artifacts

_FIXTURE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "fixtures", "axe-stress.json",
)

# Impact levels we treat as must-fix: critical, serious, AND moderate.
# Moderate is included because the landmark/region bugs fixed in Phase 3
# were moderate — excluding them would let a regression pass silently.
_BLOCKING_IMPACTS = {"critical", "serious", "moderate"}


def _has_playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return True
    except Exception:
        return False


# LOUD skip warning: print to stderr so it's visible in test output.
if not _has_playwright():
    import warnings
    msg = (
        "\n" + "=" * 70 + "\n"
        "WARNING: Self-accessibility audit tests SKIPPED — Playwright not installed.\n"
        "AccessDoc's own HTML outputs were NOT audited with axe-core.\n"
        "Install: pip install playwright && playwright install chromium\n"
        "These tests SHOULD run in CI.\n"
        + "=" * 70 + "\n"
    )
    warnings.warn(msg, RuntimeWarning, stacklevel=2)
    print(msg, file=sys.stderr)


@unittest.skipUnless(_has_playwright(),
    "Playwright not installed — self-audit DID NOT RUN. "
    "Install: pip install playwright && playwright install chromium")
class TestSelfAccessibility(unittest.TestCase):
    """AccessDoc's own HTML outputs must be accessible."""

    @classmethod
    def setUpClass(cls):
        with open(_FIXTURE) as f:
            axe_json = f.read()
        body = {
            "scanner_input": axe_json,
            "client_name": "Stress-Audit-Client-\u00dcn\u00efc\u00f6d\u00e9-\u65e5\u672c-\U0001f389",
            "include_vpat": True,
            "include_sarif": True,
            "include_eaa": True,
        }
        cls.artifacts = build_artifacts(body)
        cls.report_html = cls.artifacts.html_bytes.decode()
        cls.vpat_html = cls.artifacts.vpat_html

    def _load_axe_source(self):
        """Find axe-core JS source from local file or env var."""
        axe_source = None
        axe_path = os.environ.get("ACCESSDOC_AXE_PATH", "")
        if axe_path and os.path.exists(axe_path):
            with open(axe_path, "r") as af:
                return af.read()

        for candidate in [
            "/home/user/axe-core.min.js",
            os.path.join(os.path.dirname(__file__), "..", "node_modules",
                         "axe-core", "axe.min.js"),
        ]:
            candidate = os.path.abspath(candidate)
            if os.path.exists(candidate):
                with open(candidate, "r") as af:
                    return af.read()
        return None

    def _run_axe(self, html_content, viewport_width=None):
        """Run axe-core against an HTML string; return violations list.

        If viewport_width is set, the page is sized to that width before
        running axe (for reflow / 1.4.10 testing).
        """
        import tempfile, time
        from playwright.sync_api import sync_playwright

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False, encoding="utf-8"
        ) as f:
            f.write(html_content)
            tmp_path = f.name

        try:
            axe_source = self._load_axe_source()

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                if viewport_width:
                    page.set_viewport_size({
                        "width": viewport_width,
                        "height": 800,
                    })
                page.goto(f"file://{tmp_path}", wait_until="load",
                          timeout=10000)
                if axe_source:
                    page.add_script_tag(content=axe_source)
                else:
                    page.add_script_tag(
                        url="https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.11.2/axe.min.js"
                    )
                time.sleep(1)
                result = page.evaluate(
                    "async () => { try { return await axe.run(document, "
                    "{resultTypes:['violations']}); } catch(e) { "
                    "return {error: e.message}; } }"
                )
                browser.close()

            if isinstance(result, dict) and "error" in result:
                self.fail(f"axe.run failed: {result['error']}")
            return result.get("violations", [])
        finally:
            os.unlink(tmp_path)

    def _format_violations(self, violations):
        msgs = []
        for v in violations:
            msgs.append(
                f"  [{v.get('impact', '?')}] {v.get('id', '?')}: "
                f"{v.get('description', '')}"
            )
        return "\n".join(msgs)

    # --- axe-core violation checks (critical + serious + moderate) ---

    def test_report_html_no_blocking_violations(self):
        """report.html must have zero critical/serious/moderate violations."""
        violations = self._run_axe(self.report_html)
        blocking = [v for v in violations
                    if v.get("impact") in _BLOCKING_IMPACTS]
        if blocking:
            self.fail(
                f"report.html has {len(blocking)} blocking axe violations "
                f"(critical/serious/moderate):\n"
                + self._format_violations(blocking)
            )

    def test_vpat_html_no_blocking_violations(self):
        """vpat-draft.html must have zero critical/serious/moderate violations."""
        violations = self._run_axe(self.vpat_html)
        blocking = [v for v in violations
                    if v.get("impact") in _BLOCKING_IMPACTS]
        if blocking:
            self.fail(
                f"vpat-draft.html has {len(blocking)} blocking axe violations "
                f"(critical/serious/moderate):\n"
                + self._format_violations(blocking)
            )

    def test_report_html_reflow_320px(self):
        """report.html must have zero blocking violations at 320px width
        (WCAG 1.4.10 Reflow)."""
        violations = self._run_axe(self.report_html, viewport_width=320)
        blocking = [v for v in violations
                    if v.get("impact") in _BLOCKING_IMPACTS]
        if blocking:
            self.fail(
                f"report.html has {len(blocking)} blocking axe violations "
                f"at 320px width (reflow):\n"
                + self._format_violations(blocking)
            )

    def test_vpat_html_reflow_320px(self):
        """vpat-draft.html must have zero blocking violations at 320px width
        (WCAG 1.4.10 Reflow)."""
        violations = self._run_axe(self.vpat_html, viewport_width=320)
        blocking = [v for v in violations
                    if v.get("impact") in _BLOCKING_IMPACTS]
        if blocking:
            self.fail(
                f"vpat-draft.html has {len(blocking)} blocking axe violations "
                f"at 320px width (reflow):\n"
                + self._format_violations(blocking)
            )

    # --- Structural assertions (catch regressions of specific fixes) ---

    def test_report_html_has_main_landmark(self):
        """report.html must contain a <main> element."""
        self.assertIn("<main>", self.report_html)

    def test_report_html_has_scoped_headers(self):
        """report.html table headers must have scope attributes."""
        self.assertIn("scope='col'", self.report_html)

    def test_report_html_has_thead_tbody(self):
        """report.html table must have thead and tbody."""
        self.assertIn("<thead>", self.report_html)
        self.assertIn("<tbody>", self.report_html)

    def test_vpat_html_has_main_landmark(self):
        """vpat-draft.html must contain a <main> element."""
        self.assertIn("<main>", self.vpat_html)

    def test_vpat_html_has_scoped_headers(self):
        """vpat-draft.html table headers must have scope attributes."""
        self.assertIn('scope="col"', self.vpat_html)

    def test_vpat_html_has_thead_tbody(self):
        """vpat-draft.html table must have thead and tbody."""
        self.assertIn("<thead>", self.vpat_html)
        self.assertIn("<tbody>", self.vpat_html)


if __name__ == "__main__":
    unittest.main()
