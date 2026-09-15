"""Provider response bodies are untrusted, including compressed JSON."""
import unittest
from unittest.mock import Mock, patch
import requests
from app.gateway import ModelGateway, CANONICAL_CHAIN, GatewayError

class ResponseBoundsTests(unittest.TestCase):
    def response(self, chunks, status=200, headers=None):
        r = Mock(status_code=status, headers=headers or {})
        r.iter_content.return_value = iter(chunks)
        return r

    def call(self, response, limit=64, remaining=2):
        gw = ModelGateway(api_key="test-only", max_response_bytes=limit)
        with patch.object(gw._session, "post", return_value=response) as post:
            try:
                result = gw._post(CANONICAL_CHAIN[0], [], remaining=remaining)
                self.assertTrue(post.call_args.kwargs["stream"])
                return result
            finally:
                response.close.assert_called_once()
                gw._session.close()

    def test_valid_body_at_exact_decoded_limit(self):
        body = b'{"a":1}'
        self.assertEqual(self.call(self.response([body]), len(body))[2], {"a": 1})

    def test_decoded_body_over_limit_without_content_length(self):
        with self.assertRaises(GatewayError) as caught:
            self.call(self.response([b"x" * 32, b"x" * 33]))
        self.assertEqual(caught.exception.status, 502)

    def test_compressed_body_uses_decoded_byte_limit(self):
        with self.assertRaises(GatewayError):
            self.call(self.response([b"x" * 65], headers={"Content-Encoding": "gzip", "Content-Length": "20"}))

    def test_429_body_not_consumed(self):
        r = self.response([b"x" * 100000], status=429, headers={"Retry-After": "1"})
        self.assertEqual(self.call(r)[:2], (429, {"Retry-After": "1"}))
        r.iter_content.assert_not_called()

    def test_invalid_and_deep_json_fail_closed(self):
        for body in [b"not json", b"[" * 1100 + b"0" + b"]" * 1100]:
            self.assertEqual(self.call(self.response([body]), 4096)[2], {})

    def test_stream_error_closes_response(self):
        r = self.response([])
        r.iter_content.side_effect = requests.ConnectionError("stream interrupted")
        with self.assertRaises(requests.ConnectionError):
            self.call(r)

    def test_elapsed_deadline_rejects_next_chunk(self):
        clock = [0.0]
        def chunks():
            clock[0] = 3.0
            yield b"{}"
        r = self.response([])
        r.iter_content.return_value = chunks()
        with patch("app.gateway.time.monotonic", side_effect=lambda: clock[0]):
            with self.assertRaises(GatewayError) as caught:
                self.call(r, remaining=2)
        self.assertEqual(caught.exception.status, 504)

    def test_limit_must_be_positive(self):
        with self.assertRaises(ValueError):
            ModelGateway(max_response_bytes=0)


class RealHTTPBoundsTests(unittest.TestCase):
    """Exercise requests decompression and recovery over a real local socket."""
    def test_gzip_expansion_fails_then_next_request_recovers(self):
        import gzip
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        body = gzip.compress(b"x" * 100000)
        good = b'{"choices":[{"message":{"content":"recovered"}}]}'
        class Handler(BaseHTTPRequestHandler):
            count = 0
            def log_message(self, *args):
                pass
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                Handler.count += 1
                self.send_response(200)
                data = body if Handler.count == 1 else good
                if Handler.count == 1:
                    self.send_header("Content-Encoding", "gzip")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        gateway = ModelGateway(api_key="test-only", chain=(CANONICAL_CHAIN[0],),
                               max_response_bytes=1024, max_retries=0)
        try:
            with patch("app.gateway.MELIOUS_BASE_URL", "http://127.0.0.1:%d" % server.server_port), patch.object(gateway, "_log"):
                self.assertTrue(gateway.chat("fix contrast").fallback)
                result = gateway.chat("fix contrast")
                self.assertFalse(result.fallback)
                self.assertEqual(result.text, "recovered")
        finally:
            gateway._session.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
