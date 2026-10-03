"""Hostile manual tables must be bounded before dictionary expansion."""
import json
import os
import threading
import tracemalloc
import unittest
from unittest.mock import patch
from http.server import HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.limits import LimitExceeded, MAX_MANUAL_FINDINGS
from app.manual import parse_manual_findings


def wide_table(markdown=False, count=MAX_MANUAL_FINDINGS + 1):
    header = ["id"] + ["c%d" % i for i in range(999)]
    if markdown:
        return "| " + " | ".join(header) + " |\n|---|\n" + "|x|\n" * count
    return ",".join(header) + "\n" + "x\n" * count


class ManualStreamingTests(unittest.TestCase):
    def test_wide_csv_rejects_without_large_allocation(self):
        text = wide_table()
        tracemalloc.start()
        try:
            with self.assertRaises(LimitExceeded):
                parse_manual_findings(text)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 20 * 1024 * 1024,
                        "small CSV expanded before rejection: %d bytes" % peak)

    def test_wide_markdown_rejects_without_large_allocation(self):
        text = wide_table(markdown=True)
        tracemalloc.start()
        try:
            with self.assertRaises(LimitExceeded):
                parse_manual_findings(text)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 20 * 1024 * 1024,
                        "small Markdown expanded before rejection: %d bytes" % peak)

    def test_csv_stops_before_consuming_rows_past_limit(self):
        consumed = []
        def rows(*args, **kwargs):
            yield ["id"]
            for i in range(MAX_MANUAL_FINDINGS + 2):
                consumed.append(i)
                yield ["x"]
        with patch("app.manual.csv.reader", side_effect=rows):
            with self.assertRaises(LimitExceeded):
                parse_manual_findings("id\nx")
        self.assertEqual(len(consumed), MAX_MANUAL_FINDINGS + 1)

    def test_valid_csv_aliases_quotes_missing_cells_and_ignored_columns(self):
        text = 'rule,desc,wcag,selector,helpUrl,ignored\nkeyboard,"a,b","2.1.1;2.4.3",#x,https://example.com,noise\nempty\n'
        findings = parse_manual_findings(text)
        self.assertEqual(len(findings), 2)
        first, second = findings
        self.assertEqual(first.id, "keyboard")
        self.assertEqual(first.description, "a,b")
        self.assertEqual(first.wcag_scs, ["2.1.1", "2.4.3"])
        self.assertEqual(first.target, "#x")
        self.assertEqual(first.help_url, "https://example.com")
        self.assertEqual(second.description, "")

    def test_duplicate_csv_headers_keep_last_column(self):
        self.assertEqual(parse_manual_findings("id,id\nfirst,last")[0].id, "last")

    def test_exact_limit_is_accepted_for_both_table_formats(self):
        for markdown in (False, True):
            with self.subTest(markdown=markdown):
                self.assertEqual(len(parse_manual_findings(wide_table(
                    markdown=markdown, count=MAX_MANUAL_FINDINGS))),
                    MAX_MANUAL_FINDINGS)

    def test_markdown_keeps_aliases_and_missing_cells(self):
        text = "| rule | impact | desc | target |\nignored prose\n|---|:---:|---|---|\n| keyboard | serious | Test | #x |\n| short |\n"
        findings = parse_manual_findings(text)
        self.assertEqual(len(findings), 2)
        self.assertEqual(findings[0].target, "#x")
        self.assertEqual(findings[1].id, "short")
        self.assertEqual(findings[1].impact, "moderate")

    def test_both_adapters_reject_wide_tables_before_renderer(self):
        from api.handler import handler
        from app.main import Handler, Server
        for server_type, handler_type in ((HTTPServer, handler), (Server, Handler)):
            with self.subTest(adapter=handler_type.__module__):
                server = server_type(("127.0.0.1", 0), handler_type)
                runner = threading.Thread(
                    target=lambda: server.serve_forever(poll_interval=0.01))
                runner.start()
                env = {"ACCESSDOC_REQUIRE_AUTH": "false", "ACCESSDOC_API_KEY": "",
                       "ACCESSDOC_API_KEYS": "", "RATE_LIMIT_PER_MINUTE": "100000",
                       "ALLOWED_HOSTS": "127.0.0.1:%d" % server.server_port}
                try:
                    with patch.dict(os.environ, env), patch(
                            "app.service.generate_pdf_report") as renderer:
                        for markdown in (False, True):
                            body = json.dumps({
                                "scanner_input": {"violations": []},
                                "manual_findings": wide_table(markdown),
                            }).encode()
                            request = Request(
                                "http://127.0.0.1:%d/api/bundle" % server.server_port,
                                data=body, headers={"Content-Type": "application/json"})
                            with self.assertRaises(HTTPError) as error:
                                urlopen(request, timeout=5)
                            with error.exception:
                                self.assertEqual(error.exception.code, 413)
                                error.exception.read()
                        renderer.assert_not_called()
                finally:
                    server.shutdown()
                    server.server_close()
                    runner.join(2)
                    self.assertFalse(runner.is_alive())


if __name__ == "__main__":
    unittest.main()