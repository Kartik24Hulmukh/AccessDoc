"""Real-socket regression coverage for BOTH production adapters."""
import http.client
import json
import os
import threading
import unittest
from email.message import Message
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from api.handler import handler
from app.main import Handler
from app.bundle import validate_bundle
from app.http_policy import auth_error
from app.store import TTLReportStore


class HostedBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"ACCESSDOC_API_KEY": "", "ACCESSDOC_API_KEYS": "", "ACCESSDOC_REQUIRE_AUTH": "false", "RATE_LIMIT_PER_MINUTE": "100000"})
        self.env.start()
        self.servers = []
        for adapter in (handler, Handler):
            server = ThreadingHTTPServer(("127.0.0.1", 0), adapter)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.servers.append((server, thread))
        os.environ["ALLOWED_HOSTS"] = ",".join(f"127.0.0.1:{s.server_port}" for s, _ in self.servers)

    def tearDown(self):
        for server, thread in self.servers:
            server.shutdown()
            server.server_close()
            thread.join()
        self.env.stop()

    def post(self, index, body=None, headers=None, path="/api/bundle", raw=None):
        server = self.servers[index][0]
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        try:
            conn.request("POST", path, raw if raw is not None else json.dumps(body or {"scanner_input": {"violations": None}}).encode(), {"Content-Type": "application/json", **(headers or {})})
            response = conn.getresponse()
            return response.status, response.read(), response.will_close
        finally:
            conn.close()

    def test_both_adapters_generate_verifiable_bundle(self):
        for index in (0, 1):
            status, data, _ = self.post(index)
            self.assertEqual(status, 200)
            self.assertTrue(validate_bundle(data)["valid"])

    def test_both_adapters_strip_cli_only_options(self):
        for index in (0, 1):
            status, data, _ = self.post(index, {"scanner_input": {"violations": []}, "pdf_engine": "weasyprint", "receipt_history": [42]})
            self.assertEqual(status, 200, data)
            self.assertTrue(validate_bundle(data)["valid"])

    def test_both_adapters_ignore_local_oversize_optout(self):
        with patch.dict(os.environ, {"ACCESSDOC_ALLOW_OVERSIZED": "1"}):
            for index in (0, 1):
                status, _, _ = self.post(index, {"scanner_input": {"violations": [{"id": "x", "description": "x" * 10001}]}})
                self.assertEqual(status, 413)

    def test_auth_missing_wrong_valid_and_unconfigured(self):
        for index in (0, 1):
            with patch.dict(os.environ, {"ACCESSDOC_API_KEY": "pilot-test-secret"}):
                self.assertEqual(self.post(index)[0], 401)
                self.assertEqual(self.post(index, headers={"Authorization": "Bearer wrong"})[0], 401)
                self.assertEqual(self.post(index, headers={"Authorization": "Bearer pilot-test-secret"})[0], 200)
            with patch.dict(os.environ, {"ACCESSDOC_REQUIRE_AUTH": "true"}):
                self.assertEqual(self.post(index)[0], 503)

    def test_legacy_keys_work_on_both_adapters_with_bearer_precedence(self):
        for index in (0, 1):
            with patch.dict(os.environ, {"ACCESSDOC_API_KEYS": "legacy-one,legacy-two"}):
                self.assertEqual(self.post(index)[0], 401)
                self.assertEqual(self.post(index, headers={"X-API-Key": "legacy-two"})[0], 200)
                with patch.dict(os.environ, {"ACCESSDOC_API_KEY": "new-key"}):
                    self.assertEqual(self.post(index, headers={"X-API-Key": "legacy-two"})[0], 401)
                    self.assertEqual(self.post(index, headers={"Authorization": "Bearer new-key"})[0], 200)

    def test_rejected_post_closes_connection(self):
        for index in (0, 1):
            status, _, closed = self.post(index, raw=b"{", headers={"Content-Type": "text/plain"})
            self.assertIn(status, (415, 422))
            self.assertTrue(closed)

    def test_unsupported_framing(self):
        for index in (0, 1):
            for headers in ({"Transfer-Encoding": "chunked"}, {"Content-Encoding": "gzip"}):
                self.assertIn(self.post(index, headers=headers)[0], (400, 422))

    def test_duplicate_content_length(self):
        for server, _ in self.servers:
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            try:
                conn.putrequest("POST", "/api/bundle")
                conn.putheader("Content-Type", "application/json")
                conn.putheader("Content-Length", "2")
                conn.putheader("Content-Length", "5")
                conn.endheaders(b"{}")
                response = conn.getresponse()
                self.assertIn(response.status, (400, 422))
                response.read()
            finally:
                conn.close()

    def test_malformed_unicode_and_deep_json_are_client_errors(self):
        for index in (0, 1):
            for raw in (b"\xff", b"[" * 1500 + b"]" * 1500):
                self.assertIn(self.post(index, raw=raw)[0], (400, 422))

    def test_overload_returns_retry_after_and_recovers(self):
        import api.handler as adapter
        import app.main as main
        for index, module in ((0, adapter), (1, main)):
            with patch.object(module, "GENERATION_CAPACITY", threading.BoundedSemaphore(1)):
                module.GENERATION_CAPACITY.acquire()
                try:
                    self.assertEqual(self.post(index)[0], 503)
                finally:
                    module.GENERATION_CAPACITY.release()
                self.assertEqual(self.post(index)[0], 200)

    def test_selfhosted_generation_aliases_and_downloads(self):
        for path in ("/api/generate", "/api/v1/generate"):
            status, data, _ = self.post(1, path=path)
            self.assertEqual(status, 201, data)
            result = json.loads(data)
            self.assertEqual(result["finding_count"], 0)
            self.assertEqual(set(result["severity_counts"]), {"critical", "serious", "moderate", "minor", "unknown"})
            self.assertEqual(result["catalog_review_required"], 0)
            for key, prefix in (("download_url", b"%PDF"), ("html_companion_url", b"<!DOCTYPE"), ("receipt_url", b"{")):
                conn = http.client.HTTPConnection("127.0.0.1", self.servers[1][0].server_port, timeout=5)
                try:
                    conn.request("GET", result[key])
                    response = conn.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertTrue(response.read().startswith(prefix))
                finally:
                    conn.close()


class StoreAndAuthTests(unittest.TestCase):
    def test_store_exact_capacity_does_not_evict(self):
        store = TTLReportStore(max_items=1, max_bytes=3)
        token = store.put(b"p", b"h", b"r", "a.pdf")
        self.assertIsNotNone(store.get(token))
        self.assertEqual(store.stats, {"items": 1, "bytes": 3})
        newer = store.put(b"p", b"h", b"r", "b.pdf")
        self.assertIsNone(store.get(token))
        self.assertIsNotNone(store.get(newer))

    def test_oversized_item_does_not_destroy_existing_report(self):
        store = TTLReportStore(max_items=2, max_bytes=3)
        token = store.put(b"p", b"h", b"r", "a.pdf")
        with self.assertRaises(ValueError):
            store.put(b"pp", b"h", b"r", "b.pdf")
        self.assertIsNotNone(store.get(token))

    def test_store_rejects_invalid_configuration(self):
        for kwargs in ({"max_items": 0}, {"max_bytes": 0}, {"ttl_seconds": 0}):
            with self.assertRaises(ValueError):
                TTLReportStore(**kwargs)

    def test_auth_rejects_duplicate_and_non_ascii_headers(self):
        with patch.dict(os.environ, {"ACCESSDOC_API_KEY": "test"}):
            headers = Message()
            headers["Authorization"] = "Bearer test"
            headers["Authorization"] = "Bearer test"
            self.assertEqual(auth_error(headers)[0], 401)
            del headers["Authorization"]
            headers["Authorization"] = "Bearer é"
            self.assertEqual(auth_error(headers)[0], 401)
