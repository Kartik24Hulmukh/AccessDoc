"""ZIP response accounting and disconnected-client regression tests."""
import json
import unittest
from unittest.mock import Mock, patch, call
import api.handler as adapter


class HostedZipMetricsTests(unittest.TestCase):
    def handler(self):
        h = object.__new__(adapter.handler)
        h.path = "/api/bundle"
        h.headers = {"Content-Type": "application/json"}
        h.request_id = "synthetic-test"
        h.wfile = Mock()
        h.send_response = Mock()
        h.send_header = Mock()
        h.end_headers = Mock()
        h._read_bounded_body = Mock(return_value=(json.dumps({"scanner_input": {"violations": []}}).encode(), None, None))
        h._validate_axe_structure = Mock(return_value=(True, None, None))
        return h

    def run_post(self, h):
        with patch.object(adapter, "auth_error", return_value=None), patch.object(adapter, "build_artifacts"), patch.object(adapter, "build_bundle", return_value=b"synthetic-zip"), patch.object(adapter, "_bump") as bump:
            h._post()
            return bump

    def test_successful_zip_counts_request_once(self):
        h = self.handler()
        bump = self.run_post(h)
        self.assertEqual(bump.call_args_list.count(call("requests_total")), 1)
        h.wfile.write.assert_called_once_with(b"synthetic-zip")

    def test_broken_zip_socket_is_counted_not_raised(self):
        for error in (BrokenPipeError, ConnectionResetError):
            with self.subTest(error=error):
                h = self.handler()
                h.wfile.write.side_effect = error()
                bump = self.run_post(h)
                bump.assert_any_call("client_disconnects_total")
