"""P1-2: narrow-screen reflow contract (WCAG 1.4.10 / 2.5.8).

The static CSS contract always runs. The live audit drives real headless
Chromium against a live server and is skipped (never faked) when Chromium
or websocket-client is unavailable.
"""
import importlib.util
import os
import re
import shutil
import threading
import unittest

from app.main import Server, Handler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class NarrowCssContractTests(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "public", "static", "app.css"), encoding="utf-8") as f:
            self.css = f.read()
        with open(os.path.join(ROOT, "public", "index.html"), encoding="utf-8") as f:
            self.html = f.read()

    def test_viewport_meta_is_device_width_and_zoomable(self):
        self.assertIn('content="width=device-width,initial-scale=1"', self.html)
        self.assertNotIn("user-scalable=no", self.html)
        self.assertNotIn("maximum-scale=1", self.html)

    def test_summary_tiles_collapse_to_one_column_at_420px(self):
        m = re.search(r"@media\(max-width:420px\)\{(.*?)\}\}", self.css)
        self.assertIsNotNone(m, "420px breakpoint missing")
        self.assertIn(".summary{grid-template-columns:1fr}", m.group(1))

    def test_touch_targets_at_least_48px(self):
        self.assertIn("min-height:48px", self.css)


@unittest.skipUnless(shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome"),
                     "real Chromium not installed")
@unittest.skipUnless(importlib.util.find_spec("websocket"), "websocket-client not installed")
class NarrowViewportLiveAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = Server(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls._env = {k: os.environ.get(k) for k in ("ALLOWED_HOSTS", "ALLOWED_ORIGINS")}
        os.environ["ALLOWED_HOSTS"] = f"127.0.0.1:{cls.port},localhost:{cls.port}"
        os.environ["ALLOWED_ORIGINS"] = f"http://127.0.0.1:{cls.port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        for k, v in cls._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_no_reflow_failure_at_320_375_414_768(self):
        spec = importlib.util.spec_from_file_location("nva", os.path.join(ROOT, "scripts", "narrow_viewport_audit.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        rc = mod.main([f"http://127.0.0.1:{self.port}/", "--widths", "320,375,414,768"])
        self.assertEqual(rc, 0, "narrow-viewport audit failed; see stdout")


if __name__ == "__main__":
    unittest.main()
