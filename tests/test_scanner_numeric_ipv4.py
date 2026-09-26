"""SSRF pre-check must parse numeric IPv4 hosts the way Chromium does.

macOS libc resolves ``0177.0.0.1`` as the public 177.0.0.1 while Chromium
(WHATWG URL parser) dials 127.0.0.1. The macOS portability job exposed this;
these tests emulate that resolver on every platform.
"""

import socket
import unittest
from unittest import mock

from app.scan import UnsafeTargetError, _whatwg_ipv4, validate_url

METADATA = ".".join(str(n) for n in (0xA9, 0xFE, 0xA9, 0xFE))


def _darwin_like_getaddrinfo(host, *args, **kwargs):
    # Decimal-only parsing, as macOS libc does for leading-zero octets.
    try:
        octets = [str(int(p, 10)) for p in host.split(".")]
    except ValueError:
        raise socket.gaierror(8, "nodename nor servname provided")
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (".".join(octets), 0))]


class WhatwgIpv4Tests(unittest.TestCase):
    def test_browser_numeric_forms_canonicalise(self):
        cases = {
            "0177.0.0.1": "127.0.0.1",
            "0x7f000001": "127.0.0.1",
            str(0x7F000001): "127.0.0.1",
            "0x7f.1": "127.0.0.1",
            "127.1": "127.0.0.1",
            "127.0.0.1.": "127.0.0.1",
            "0xA9FEA9FE": METADATA,
            "8.8.8.8": "8.8.8.8",
        }
        for host, want in cases.items():
            self.assertEqual(_whatwg_ipv4(host), want, host)

    def test_non_numeric_hosts_are_left_to_dns(self):
        for host in ("example.com", "1.2.3.4.5", "256.1.1.1", "08.0.0.1", "1e3.0.0.1", "+1.0.0.1", ""):
            self.assertIsNone(_whatwg_ipv4(host), host)

    def test_rejection_does_not_depend_on_platform_resolver(self):
        with mock.patch("app.scan.socket.getaddrinfo", side_effect=_darwin_like_getaddrinfo):
            for url in ("http://0177.0.0.1/", "http://0x7f.1/", "http://0xA9FEA9FE/", "http://127.1./"):
                with self.assertRaises(UnsafeTargetError, msg=url):
                    validate_url(url)


if __name__ == "__main__":
    unittest.main()
