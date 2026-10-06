"""Offline credential-origin regression tests; no upstream requests."""
import importlib.util
from pathlib import Path
import unittest
import urllib.error
import urllib.request

spec = importlib.util.spec_from_file_location(
    "smoke_origin_ports", Path(__file__).parents[1] / "scripts/production_smoke.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class SmokeOriginPortTests(unittest.TestCase):
    def test_remote_nonstandard_ports_rejected_before_credentials(self):
        for host in ("access-doc.vercel.app", "access-abc123-atlas16.vercel.app"):
            for port in ("0", "444", "8443", "65536", "invalid"):
                for credential in ("bypass", "api_key"):
                    with self.subTest(host=host, port=port, credential=credential):
                        with self.assertRaises(ValueError):
                            smoke.smoke_headers(
                                f"https://{host}:{port}", "POST",
                                **{credential: "synthetic-only"})

    def test_https_default_and_explicit_443_allowed(self):
        for suffix in ("", ":443"):
            result = smoke.smoke_headers(
                "https://access-doc.vercel.app" + suffix, "POST",
                bypass="synthetic-bypass", api_key="synthetic-app")
            self.assertEqual(result["Authorization"], "Bearer synthetic-app")
            self.assertEqual(result["x-vercel-protection-bypass"], "synthetic-bypass")

    def test_loopback_valid_port_allowed_zero_rejected(self):
        smoke.validate_target_url("http://127.0.0.1:8123", api_key=True)
        with self.assertRaises(ValueError):
            smoke.validate_target_url("http://127.0.0.1:0", api_key=True)

    def test_redirect_invalid_or_cross_port_rejected(self):
        req = urllib.request.Request(
            "https://access-doc.vercel.app/",
            headers={"Authorization": "Bearer synthetic-only"})
        for target in (
            "https://access-doc.vercel.app:0/",
            "https://access-doc.vercel.app:444/",
            "https://access-doc.vercel.app:65536/",
            "https://access-doc.vercel.app:invalid/",
            "https://user@access-doc.vercel.app/",
            "http://access-doc.vercel.app/"):
            with self.subTest(target=target):
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    smoke.SameOriginRedirectHandler().redirect_request(
                        req, None, 302, "Found", {}, target)
                caught.exception.close()

    def test_same_origin_explicit_default_port_keeps_headers(self):
        req = urllib.request.Request(
            "https://access-doc.vercel.app/",
            headers={"Authorization": "Bearer synthetic-only"})
        redirected = smoke.SameOriginRedirectHandler().redirect_request(
            req, None, 302, "Found", {},
            "https://access-doc.vercel.app:443/healthz")
        self.assertEqual(redirected.get_header("Authorization"), "Bearer synthetic-only")