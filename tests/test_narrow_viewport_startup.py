"""CDP startup can expose an empty target list before about:blank appears."""
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "narrow_viewport_audit.py"


@unittest.skipUnless(importlib.util.find_spec("websocket"), "websocket-client not installed")
class PageTargetStartupTests(unittest.TestCase):
    def test_empty_catalog_is_not_mistaken_for_ready(self):
        spec = importlib.util.spec_from_file_location("viewport_audit", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        # websocket-client is an explicitly required dependency of this script.
        spec.loader.exec_module(module)
        page = {"type": "page", "webSocketDebuggerUrl": "ws://127.0.0.1/page"}
        replies = [io.BytesIO(b"[]"), io.BytesIO(json.dumps([page]).encode())]
        with patch.object(module.urllib.request, "urlopen", side_effect=replies) as get, \
             patch.object(module.time, "sleep"), \
             patch.object(module.time, "monotonic", side_effect=[0, 0, 0.1]):
            self.assertEqual(module.wait_for_page_target(1234, Mock(poll=Mock(return_value=None))), page)
        self.assertEqual(get.call_count, 2)


if __name__ == "__main__":
    unittest.main()