"""Required storage and coherent byte quotas must support valid report handoffs."""
import json
import os
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from app.limits import LimitExceeded
from app.store import TTLReportStore

ROOT = Path(__file__).resolve().parents[1]


class StorageContractTests(unittest.TestCase):
    def test_required_storage_import_failure_is_startup_failure(self):
        code = """
import builtins
original = builtins.__import__
def fail(name, globals=None, locals=None, fromlist=(), level=0):
    if (name == 'store' and level == 1 and globals and
            globals.get('__package__') == 'app'):
        raise ModuleNotFoundError('Injected required storage import failure')
    return original(name, globals, locals, fromlist, level)
builtins.__import__ = fail
try:
    import app.main
except ModuleNotFoundError as exc:
    assert str(exc) == 'Injected required storage import failure'
else:
    raise AssertionError('Required storage failure was hidden by a fake store')
"""
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_receipt_size_is_bounded_by_aggregate_store_budget(self):
        receipt = b"r" * 200_000
        store = TTLReportStore(max_bytes=len(receipt) + 2)
        token = store.put(b"p", b"h", receipt, "report.pdf")
        self.assertEqual(store.get(token).receipt, receipt)
        self.assertEqual(store.stats, {"items": 1, "bytes": len(receipt) + 2})

    def test_quota_rejection_is_typed_and_preserves_existing_report(self):
        store = TTLReportStore(max_bytes=3)
        token = store.put(b"p", b"h", b"r", "first.pdf")
        with self.assertRaises(LimitExceeded) as error:
            store.put(b"pp", b"h", b"r", "second.pdf")
        self.assertEqual(error.exception.limit_name, "REPORT_MAX_BYTES")
        self.assertEqual(error.exception.actual, 4)
        self.assertIsNotNone(store.get(token))
        self.assertEqual(store.stats, {"items": 1, "bytes": 3})

    def test_generate_downloads_and_quota_recovery_over_real_http(self):
        import app.main as main
        server = main.Server(("127.0.0.1", 0), main.Handler)
        runner = threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.01))
        runner.start()
        base = "http://127.0.0.1:%d" % server.server_port
        env = {"ACCESSDOC_REQUIRE_AUTH": "false", "ACCESSDOC_API_KEY": "",
               "ACCESSDOC_API_KEYS": "", "RATE_LIMIT_PER_MINUTE": "100000",
               "ALLOWED_HOSTS": "127.0.0.1:%d" % server.server_port}
        body = json.dumps({
            "scanner_input": {"violations": []},
            "manual_findings": [{"id": "keyboard", "impact": "serious",
                "description": "Keyboard navigation finding",
                "wcag_scs": ["2.1.1"], "target": "#item-%d" % i}
                for i in range(500)],
        }).encode()
        request = Request(base + "/api/generate", data=body,
                          headers={"Content-Type": "application/json"})
        try:
            with patch.dict(os.environ, env), patch.object(main, "STORE",
                                                           TTLReportStore()):
                with urlopen(request, timeout=10) as response:
                    self.assertEqual(response.status, 201)
                    generated = json.loads(response.read())
                stored = main.STORE.get(generated["report_token"])
                self.assertGreater(len(stored.receipt), 100_000)
                for key, prefix in (("download_url", b"%PDF"),
                                    ("html_companion_url", b"<!"),
                                    ("receipt_url", b"{")):
                    with urlopen(base + generated[key], timeout=5) as response:
                        self.assertEqual(response.status, 200)
                        content = response.read()
                        self.assertTrue(content.lstrip().startswith(prefix))
                        if key == "receipt_url":
                            self.assertEqual(json.loads(content)["summary"]
                                             ["manual_findings"], 500)
                self.assertLessEqual(main.STORE.stats["bytes"], main.STORE.max_bytes)
            tiny = TTLReportStore(max_bytes=3)
            retained = tiny.put(b"p", b"h", b"r", "first.pdf")
            with patch.dict(os.environ, env), patch.object(main, "STORE", tiny):
                with self.assertRaises(HTTPError) as error:
                    urlopen(request, timeout=10)
                with error.exception:
                    self.assertEqual(error.exception.code, 413)
                    self.assertEqual(json.loads(error.exception.read())["error"]
                                     ["code"], "INPUT_TOO_LARGE")
                self.assertIsNotNone(tiny.get(retained))
                # Storage quota cannot poison the shared generation admission.
                bundle_request = Request(base + "/api/bundle", data=body,
                    headers={"Content-Type": "application/json"})
                with urlopen(bundle_request, timeout=10) as response:
                    self.assertEqual(response.status, 200)
                    self.assertTrue(response.read().startswith(b"PK"))
        finally:
            server.shutdown()
            server.server_close()
            runner.join(2)
            self.assertFalse(runner.is_alive())