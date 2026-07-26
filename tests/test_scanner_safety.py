"""Tests for the live scanner network boundary (Phase 7).

These tests exercise ``app.scan.validate_url`` — the pre-navigation gate —
and the redirect/post-redirect re-validation logic.  They do **not** require
Playwright or network access; the URL validation is pure-Python and can be
tested deterministically.
"""
import unittest
from unittest import mock

from app.scan import (
    validate_url,
    UnsafeTargetError,
    _is_safe_ip,
    _check_request_host,
)


class TestSchemeDenial(unittest.TestCase):
    """7.1 — denied schemes are rejected."""

    def test_file_url_rejected(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url("file:///etc/passwd")

    def test_data_url_rejected(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url("data:text/html,<h1>hi</h1>")

    def test_javascript_url_rejected(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url("javascript:alert(1)")

    def test_ftp_url_rejected(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url("ftp://example.com/file")

    def test_chrome_url_rejected(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url("chrome://settings")

    def test_unknown_scheme_rejected(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url("gopher://example.com")

    def test_missing_scheme_rejected(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url("example.com/page")


class TestLoopbackRejection(unittest.TestCase):
    """7.3 — localhost and loopback addresses rejected."""

    def test_localhost_rejected(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url("http://localhost/")

    def test_localhost_localdomain_rejected(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url("http://localhost.localdomain/")

    def test_localhost4_rejected(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url("http://localhost4/")

    def test_localhost6_rejected(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url("http://localhost6/")

    def test_127_ipv4_rejected(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url("http://127.0.0.1/")

    def test_127_other_octet_rejected(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url("http://127.255.255.255/")

    def test_ipv6_loopback_rejected(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url("http://[::1]/")

    def test_ipv6_loopback_bracketed_rejected(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url("http://[0:0:0:0:0:0:0:1]/")


class TestPrivateIPv4Rejection(unittest.TestCase):
    """7.3 — RFC1918 private ranges rejected."""

    def test_10_range_rejected(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url("http://10.0.0.1/")

    def test_10_other_rejected(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url("http://10.255.255.255/")

    def test_172_16_range_rejected(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url("http://172.16.0.1/")

    def test_172_31_range_rejected(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url("http://172.31.255.255/")

    def test_192_168_range_rejected(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url("http://192.168.1.1/")

    def test_192_168_other_rejected(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url("http://192.168.0.0/")


class TestLinkLocalRejection(unittest.TestCase):
    """7.3 — link-local and cloud-metadata rejected."""

    def test_link_local_ipv4_rejected(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url("http://169.254.1.1/")

    def test_cloud_metadata_rejected(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url("http://169.254.169.254/")

    def test_ipv6_link_local_rejected(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url("http://[fe80::1]/")


class TestIPv6PrivateRejection(unittest.TestCase):
    """7.3 — IPv6 private (fc00::/7) rejected."""

    def test_ipv6_private_fc_rejected(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url("http://[fc00::1]/")

    def test_ipv6_private_fd_rejected(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url("http://[fd12:3456:789a::1]/")


class TestSpecialAddressRejection(unittest.TestCase):
    """7.3 — multicast, unspecified rejected."""

    def test_unspecified_ipv4_rejected(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url("http://0.0.0.0/")

    def test_unspecified_ipv6_rejected(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url("http://[::]/")

    def test_multicast_ipv4_rejected(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url("http://224.0.0.1/")


class TestEncodedAndNumericIPVariants(unittest.TestCase):
    """7.3 — numeric/encoded IP variants rejected.

    Browsers accept decimal, octal, and hex integer forms of IPv4 addresses.
    ``urllib.parse.urlsplit`` extracts the hostname, and ``ipaddress`` parses
    integer forms, so we validate those too.
    """

    def test_decimal_ipv4_rejected(self):
        # 127.0.0.1 == 2130706433
        with self.assertRaises(UnsafeTargetError):
            validate_url("http://2130706433/")

    def test_hex_ipv4_rejected(self):
        # 127.0.0.1 == 0x7f000001
        with self.assertRaises(UnsafeTargetError):
            validate_url("http://0x7f000001/")

    def test_octal_ipv4_rejected(self):
        # 127.0.0.1 == 0177.0.0.1
        with self.assertRaises(UnsafeTargetError):
            validate_url("http://0177.0.0.1/")

    def test_ipv6_with_scope_rejected(self):
        # fe80::1%eth0 — link-local with zone
        with self.assertRaises(UnsafeTargetError):
            validate_url("http://[fe80::1%25eth0]/")


class TestHostnameResolvesToPrivate(unittest.TestCase):
    """7.3 — a hostname that resolves to a private IP is rejected."""

    def test_hostname_resolving_to_loopback_rejected(self):
        with mock.patch("app.scan._resolve_host", return_value=["127.0.0.1"]):
            with self.assertRaises(UnsafeTargetError) as ctx:
                validate_url("http://internal.test/")
            self.assertIn("127.0.0.1", str(ctx.exception))

    def test_hostname_resolving_to_private_rejected(self):
        with mock.patch("app.scan._resolve_host", return_value=["10.1.2.3"]):
            with self.assertRaises(UnsafeTargetError):
                validate_url("http://internal.test/")

    def test_hostname_resolving_to_metadata_rejected(self):
        with mock.patch(
            "app.scan._resolve_host", return_value=["169.254.169.254"]
        ):
            with self.assertRaises(UnsafeTargetError):
                validate_url("http://metadata.test/")

    def test_hostname_resolving_to_mixed_rejected(self):
        # Even if one IP is public, a private one in the list blocks it.
        with mock.patch(
            "app.scan._resolve_host",
            return_value=["93.184.216.34", "10.0.0.5"],
        ):
            with self.assertRaises(UnsafeTargetError):
                validate_url("http://mixed.test/")

    def test_unresolvable_hostname_rejected(self):
        with mock.patch("app.scan._resolve_host", return_value=[]):
            with self.assertRaises(UnsafeTargetError):
                validate_url("http://nonexistent.test/")


class TestPublicAccepted(unittest.TestCase):
    """7.3 — allowed public HTTPS accepted (no network needed via mock)."""

    def test_public_literal_ip_accepted(self):
        # 93.184.216.34 is example.com's public IP — a literal public IP
        # is validated without DNS resolution.
        url = validate_url("https://93.184.216.34/")
        self.assertEqual(url, "https://93.184.216.34/")

    def test_public_hostname_accepted_with_mock_resolution(self):
        with mock.patch(
            "app.scan._resolve_host", return_value=["93.184.216.34"]
        ):
            url = validate_url("https://example.com/")
        self.assertEqual(url, "https://example.com/")

    def test_http_public_accepted(self):
        with mock.patch(
            "app.scan._resolve_host", return_value=["93.184.216.34"]
        ):
            url = validate_url("http://example.com/")
        self.assertEqual(url, "http://example.com/")


class TestAllowPrivateNetworkOptIn(unittest.TestCase):
    """The --allow-private-network opt-in bypasses IP checks but not scheme."""

    def test_private_ip_allowed_with_opt_in(self):
        url = validate_url(
            "http://10.0.0.1/", allow_private_network=True
        )
        self.assertEqual(url, "http://10.0.0.1/")

    def test_loopback_allowed_with_opt_in(self):
        url = validate_url(
            "http://127.0.0.1/", allow_private_network=True
        )
        self.assertEqual(url, "http://127.0.0.1/")

    def test_localhost_alias_still_rejected_with_opt_in(self):
        # Hostname aliases are always denied regardless of opt-in.
        with self.assertRaises(UnsafeTargetError):
            validate_url(
                "http://localhost/", allow_private_network=True
            )

    def test_file_url_still_rejected_with_opt_in(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url(
                "file:///etc/passwd", allow_private_network=True
            )

    def test_javascript_still_rejected_with_opt_in(self):
        with self.assertRaises(UnsafeTargetError):
            validate_url(
                "javascript:alert(1)", allow_private_network=True
            )


class TestRequestHostCheck(unittest.TestCase):
    """The Playwright route handler helper enforces the same policy."""

    def test_request_to_private_blocked(self):
        self.assertFalse(_check_request_host("http://10.0.0.1/", False))

    def test_request_to_loopback_blocked(self):
        self.assertFalse(_check_request_host("http://127.0.0.1/", False))

    def test_request_to_metadata_blocked(self):
        self.assertFalse(
            _check_request_host("http://169.254.169.254/", False)
        )

    def test_request_to_file_blocked(self):
        self.assertFalse(_check_request_host("file:///etc/passwd", False))

    def test_request_to_public_allowed(self):
        self.assertTrue(
            _check_request_host("https://93.184.216.34/", False)
        )

    def test_request_to_private_allowed_with_opt_in(self):
        self.assertTrue(
            _check_request_host("http://10.0.0.1/", True)
        )


class TestRedirectToPrivateBlocked(unittest.TestCase):
    """7.3 — redirect to a private address is blocked.

    The route handler intercepts every request including redirect targets,
    so a redirect from a public URL to a private URL is blocked by the same
    ``_check_request_host`` gate.  We simulate the redirect chain here.
    """

    def test_redirect_to_private_blocked_by_route_handler(self):
        # Simulate: browser is about to follow a redirect to 10.0.0.1.
        # The route handler would be called with the redirect target URL.
        redirect_target = "http://10.0.0.1/internal"
        self.assertFalse(
            _check_request_host(redirect_target, False)
        )

    def test_redirect_to_loopback_blocked_by_route_handler(self):
        redirect_target = "http://127.0.0.1/admin"
        self.assertFalse(
            _check_request_host(redirect_target, False)
        )

    def test_redirect_to_metadata_blocked_by_route_handler(self):
        redirect_target = "http://169.254.169.254/latest/meta-data/"
        self.assertFalse(
            _check_request_host(redirect_target, False)
        )

    def test_redirect_to_file_blocked_by_route_handler(self):
        redirect_target = "file:///etc/shadow"
        self.assertFalse(
            _check_request_host(redirect_target, False)
        )

    def test_validate_url_blocks_redirect_target_directly(self):
        """validate_url is called on the final URL after navigation redirects."""
        with self.assertRaises(UnsafeTargetError):
            validate_url("http://10.0.0.1/internal", allow_private_network=False)

    def test_redirect_to_public_allowed(self):
        redirect_target = "https://93.184.216.34/new-path"
        self.assertTrue(
            _check_request_host(redirect_target, False)
        )


class TestIsSafeIPHelper(unittest.TestCase):
    """Direct unit tests for the _is_safe_ip helper."""

    def test_public_ip_safe(self):
        self.assertTrue(_is_safe_ip("93.184.216.34"))

    def test_loopback_unsafe(self):
        self.assertFalse(_is_safe_ip("127.0.0.1"))

    def test_private_unsafe(self):
        self.assertFalse(_is_safe_ip("10.1.2.3"))
        self.assertFalse(_is_safe_ip("172.16.0.1"))
        self.assertFalse(_is_safe_ip("192.168.1.1"))

    def test_link_local_unsafe(self):
        self.assertFalse(_is_safe_ip("169.254.1.1"))

    def test_metadata_unsafe(self):
        self.assertFalse(_is_safe_ip("169.254.169.254"))

    def test_unspecified_unsafe(self):
        self.assertFalse(_is_safe_ip("0.0.0.0"))

    def test_multicast_unsafe(self):
        self.assertFalse(_is_safe_ip("224.0.0.1"))

    def test_ipv6_loopback_unsafe(self):
        self.assertFalse(_is_safe_ip("::1"))

    def test_ipv6_private_unsafe(self):
        self.assertFalse(_is_safe_ip("fc00::1"))
        self.assertFalse(_is_safe_ip("fd12::1"))

    def test_ipv6_link_local_unsafe(self):
        self.assertFalse(_is_safe_ip("fe80::1"))

    def test_ipv6_public_safe(self):
        self.assertTrue(_is_safe_ip("2606:2800:220:1:248:1893:25c8:1946"))

    def test_invalid_ip_unsafe(self):
        self.assertFalse(_is_safe_ip("not-an-ip"))


if __name__ == "__main__":
    unittest.main()
