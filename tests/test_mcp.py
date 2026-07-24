"""Tests for the stdio MCP server."""
import base64
import json
import os
import sys
import unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mcp import server


AXE = json.dumps({
    "url": "https://example.com",
    "testEngine": {"name": "axe-core", "version": "4.11.2"},
    "violations": [{"id": "image-alt", "impact": "critical", "description": "a",
                    "helpUrl": "h", "nodes": [{}], "tags": ["wcag2a", "wcag111"]}],
})


def _call(name, args):
    return server.handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": args},
    })


class TestMcp(unittest.TestCase):
    def test_initialize(self):
        resp = server.handle_request({"jsonrpc": "2.0", "id": 0, "method": "initialize"})
        self.assertIn("serverInfo", resp["result"])

    def test_tools_list_has_expected(self):
        resp = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = {t["name"] for t in resp["result"]["tools"]}
        self.assertIn("generate_bundle", names)
        self.assertIn("export_sarif", names)
        self.assertIn("verify_bundle", names)

    def test_generate_and_verify_roundtrip(self):
        resp = _call("generate_bundle", {"scanner_input": AXE, "client_name": "C"})
        payload = json.loads(resp["result"]["content"][0]["text"])
        b64 = payload["bundle_base64"]
        vresp = _call("verify_bundle", {"bundle_base64": b64})
        vdata = json.loads(vresp["result"]["content"][0]["text"])
        self.assertTrue(vdata["valid"])

    def test_export_sarif(self):
        resp = _call("export_sarif", {"scanner_input": AXE})
        log = json.loads(resp["result"]["content"][0]["text"])
        self.assertEqual(log["version"], "2.1.0")

    def test_missing_scanner_input_is_error(self):
        resp = _call("generate_bundle", {})
        self.assertTrue(resp["result"].get("isError"))

    def test_unknown_tool_is_error(self):
        resp = _call("does_not_exist", {})
        self.assertTrue(resp["result"].get("isError"))


if __name__ == "__main__":
    unittest.main()
