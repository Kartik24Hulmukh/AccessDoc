import types
import unittest
from unittest import mock

from app.scan import AXE_CDN, run_scan, ScanUnavailable


class _FakePage:
    def __init__(self, axe_version=None, axe_result=None):
        self.url = "https://93.184.216.34/"
        self.axe_version = axe_version
        self.axe_result = axe_result or {"violations": [], "passes": [], "incomplete": []}
        self.injected_url = None

    def route(self, *_args, **_kwargs):
        return None

    def goto(self, *_args, **_kwargs):
        return None

    def add_script_tag(self, content=None, url=None):
        self.injected_url = url
        return None

    def evaluate(self, script):
        if "axe.version" in script:
            return self.axe_version
        if "axe.run" in script:
            return dict(self.axe_result)
        return None


class _FakeBrowser:
    def __init__(self, page):
        self._page = page

    def new_page(self):
        return self._page

    def close(self):
        return None


class _FakeChromium:
    def __init__(self, page):
        self._page = page

    def launch(self, headless=True):
        return _FakeBrowser(self._page)


class _FakePlaywrightContext:
    def __init__(self, page):
        self.chromium = _FakeChromium(page)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestRunScanFallback(unittest.TestCase):
    def _run_with_fake_playwright(self, page):
        fake_sync = lambda: _FakePlaywrightContext(page)
        fake_module = types.SimpleNamespace(sync_playwright=fake_sync)
        with (
            mock.patch.dict("sys.modules", {"playwright.sync_api": fake_module}),
            mock.patch("app.scan._load_axe_source", return_value=None),
            mock.patch("app.scan._resolve_host", return_value=["93.184.216.34"]),
        ):
            return run_scan("https://93.184.216.34/")

    def test_uses_published_cdn_fallback_version(self):
        page = _FakePage(axe_version="4.11.0")
        self._run_with_fake_playwright(page)
        self.assertEqual(
            page.injected_url,
            "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.11.0/axe.min.js",
        )
        self.assertEqual(AXE_CDN, page.injected_url)

    def test_fails_closed_when_axe_not_loaded(self):
        page = _FakePage(axe_version=None)
        with self.assertRaises(ScanUnavailable) as ctx:
            self._run_with_fake_playwright(page)
        msg = str(ctx.exception)
        self.assertIn("ACCESSDOC_AXE_PATH", msg)
        self.assertIn("failed to initialize", msg)

    def test_records_runtime_fallback_engine_version(self):
        page = _FakePage(axe_version="4.11.0", axe_result={"violations": []})
        result = self._run_with_fake_playwright(page)
        self.assertEqual(result["testEngine"]["version"], "4.11.0")
