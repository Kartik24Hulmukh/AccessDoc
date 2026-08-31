"""Optional scan companion: run axe-core against a live URL.

The deterministic evidence core stays stdlib-only. This module is the ONLY
part that needs a browser + axe-core, and it degrades gracefully: if Playwright
is not installed it raises ScanUnavailable with install instructions rather
than crashing an import.

Usage:
    from app.scan import run_scan, ScanUnavailable
    axe_json = run_scan("https://example.com")   # returns axe-core result dict

Install extras:
    pip install playwright && playwright install chromium

NETWORK BOUNDARY SAFETY
-----------------------
By default the scanner refuses to navigate to any URL whose resolved host
falls inside a private, loopback, link-local, multicast, unspecified, or
cloud-metadata address range.  Only public http/https URLs are accepted.
This prevents an attacker (or a careless operator) from pointing the scanner
at internal services, cloud metadata endpoints (169.254.169.254), or the
local machine itself.

The ``allow_private_network=True`` opt-in (surfaced as ``--allow-private-network``
on the CLI) explicitly disables the boundary check.  It must never be the
default and must never be set by automated workflows that process untrusted
URL input.

DNS-rebinding limitations
~~~~~~~~~~~~~~~~~~~~~~~~~
The hostname-to-IP check is performed **once**, before navigation.  A
determined attacker who controls the authoritative DNS server for a domain
can answer the pre-navigation resolution with a public IP (passing the
check) and then answer the browser's subsequent DNS lookup with a private
IP, causing the browser to connect to an internal host despite the gate.
This is the classic DNS-rebinding (TOCTOU) attack.

Mitigations implemented here, in order of strength:

1. **Post-redirect re-validation.**  Every HTTP redirect is intercepted and
   the new Location is re-validated (scheme + resolved host) before the
   browser is allowed to follow it.  This closes the most common rebinding
   vector where a public URL 302-redirects to an internal address.

2. **Playwright request interception.**  Every outgoing request (including
   sub-resource requests triggered by the page) is routed through a handler
   that re-resolves the request host and aborts the request if the resolved
   IP is private.  This narrows the TOCTOU window to the gap between the
   handler's DNS lookup and the browser's own connection, but does not
   eliminate it entirely.

What this module **cannot** guarantee:

* If the attacker flips the DNS record in the milliseconds between the
  interception handler's ``socket.getaddrinfo`` call and the browser's
  actual TCP connect, the browser may still reach the internal host.
  A fully robust defence requires a browser-level hook that pins the
  resolved IP for the connection (Playwright does not currently expose
  this), or running the browser inside a network namespace that has no
  route to private ranges.

* The pre-navigation check uses the system resolver.  A compromised or
  poisoned resolver can defeat the gate regardless of timing.

Therefore: the boundary check is a **strong default safety rail**, not a
cryptographic guarantee.  For environments where DNS rebinding is an
accepted threat model, run the scanner inside an isolated network
namespace with no route to RFC1918 space, and do not rely on this
module alone.
"""

import ipaddress
import json
import os
import socket
import urllib.parse

# axe-core UMD is fetched from a CDN at scan time OR loaded from a local path
# via ACCESSDOC_AXE_PATH. We never bundle axe-core source (license hygiene).
AXE_FALLBACK_VERSION = "4.11.0"
AXE_CDN = (
    "https://cdnjs.cloudflare.com/ajax/libs/axe-core/"
    f"{AXE_FALLBACK_VERSION}/axe.min.js"
)

# Schemes the scanner is allowed to navigate to by default.
ALLOWED_SCHEMES = frozenset({"http", "https"})

# Schemes that are always rejected, regardless of opt-in flags.
# ``file`` can read local disks, ``data``/``javascript`` execute inline
# content, ``ftp`` is unencrypted and unsupported by the browser scanner,
# ``chrome`` accesses browser-internal pages.
DENIED_SCHEMES = frozenset({
    "file", "data", "javascript", "ftp", "chrome", "chrome-extension",
})

# Hostnames that are loopback aliases and must be rejected even when they
# would otherwise resolve via DNS.
DENIED_HOSTNAMES = frozenset({
    "localhost", "localhost.localdomain", "localhost4", "localhost6",
    "ip6-localhost", "ip6-loopback", "broadcasthost",
})


class ScanUnavailable(RuntimeError):
    """Raised when the optional scan dependencies are not available."""


class UnsafeTargetError(ValueError):
    """Raised when a URL targets a denied scheme or private/loopback network."""


# ---------------------------------------------------------------------------
# URL & network boundary validation
# ---------------------------------------------------------------------------

def _is_safe_ip(ip: str) -> bool:
    """Return True if ``ip`` is a public, non-special address.

    Returns False for loopback, private, link-local, multicast, unspecified,
    and cloud-metadata addresses.
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False

    # Cloud metadata endpoint (AWS/GCP/Azure) — 169.254.169.254 is link-local
    # but we call it out explicitly for clarity and defence-in-depth.
    if str(addr) == "169.254.169.254":
        return False

    if addr.is_loopback:
        return False
    if addr.is_private:
        return False
    if addr.is_link_local:
        return False
    if addr.is_multicast:
        return False
    if addr.is_unspecified:
        return False
    if addr.is_reserved:
        return False
    return True


def _resolve_host(hostname: str):
    """Resolve *hostname* to a list of IP address strings.

    Returns an empty list if resolution fails.
    """
    try:
        infos = socket.getaddrinfo(hostname, None)
    except (socket.gaierror, socket.herror, UnicodeError, OSError):
        return []
    ips = []
    for family, _stype, _proto, _canon, sockaddr in infos:
        if family == socket.AF_INET:
            ip = sockaddr[0]
        elif family == socket.AF_INET6:
            # sockaddr for IPv6 is (host, port, flowinfo, scope_id)
            ip = sockaddr[0]
            # Strip IPv6 scope/zone (e.g. fe80::1%eth0)
            if "%" in ip:
                ip = ip.split("%", 1)[0]
        else:
            continue
        if ip not in ips:
            ips.append(ip)
    return ips


def validate_url(raw_url: str, allow_private_network: bool = False) -> str:
    """Validate *raw_url* against the network boundary policy.

    Returns the normalised URL string if it is safe to navigate to.

    Raises :class:`UnsafeTargetError` if the scheme is denied, the host is a
    loopback alias, or any resolved IP for the host falls inside a denied
    range (and ``allow_private_network`` is False).

    When ``allow_private_network`` is True the IP-range checks are skipped
    but scheme and hostname-alias checks are still enforced — a user opting
    into private-network scanning still cannot use ``file://`` or
    ``javascript:`` URLs.
    """
    if not raw_url or not isinstance(raw_url, str):
        raise UnsafeTargetError("URL must be a non-empty string")

    parsed = urllib.parse.urlsplit(raw_url)
    scheme = (parsed.scheme or "").lower()

    if not scheme:
        raise UnsafeTargetError("URL is missing a scheme")

    if scheme in DENIED_SCHEMES:
        raise UnsafeTargetError(f"Scheme '{scheme}' is not permitted for scanning")

    if scheme not in ALLOWED_SCHEMES:
        raise UnsafeTargetError(
            f"Scheme '{scheme}' is not in the allowed list {sorted(ALLOWED_SCHEMES)}"
        )

    host = (parsed.hostname or "").lower()
    if not host:
        raise UnsafeTargetError("URL is missing a host")

    if host in DENIED_HOSTNAMES:
        raise UnsafeTargetError(f"Hostname '{host}' is a denied loopback alias")

    # If the host is already a literal IP, validate it directly.
    try:
        ipaddress.ip_address(host)
        is_literal_ip = True
    except ValueError:
        is_literal_ip = False

    if is_literal_ip:
        if not allow_private_network and not _is_safe_ip(host):
            raise UnsafeTargetError(
                f"Literal IP '{host}' is inside a denied network range"
            )
    else:
        # Hostname: resolve and check every returned address.
        if not allow_private_network:
            ips = _resolve_host(host)
            if not ips:
                # Unresolvable — let the browser surface the error rather than
                # silently treating it as safe.  But we do block it here so a
                # rebinding attacker cannot exploit a transient NXDOMAIN.
                raise UnsafeTargetError(
                    f"Could not resolve host '{host}' for pre-navigation check"
                )
            for ip in ips:
                if not _is_safe_ip(ip):
                    raise UnsafeTargetError(
                        f"Host '{host}' resolves to denied address '{ip}'"
                    )

    return raw_url


def _check_request_host(url: str, allow_private_network: bool) -> bool:
    """Return True if a request to *url* should be allowed.

    Used by the Playwright route handler for every outgoing request
    (including sub-resources and redirects).
    """
    if allow_private_network:
        # Still enforce scheme/alias checks.
        try:
            validate_url(url, allow_private_network=True)
        except UnsafeTargetError:
            return False
        return True
    try:
        validate_url(url, allow_private_network=False)
    except UnsafeTargetError:
        return False
    return True


# ---------------------------------------------------------------------------
# axe-core loading
# ---------------------------------------------------------------------------

def _load_axe_source():
    local = os.environ.get("ACCESSDOC_AXE_PATH")
    if local and os.path.exists(local):
        with open(local, "r", encoding="utf-8") as f:
            return f.read()
    return None  # signal: inject from CDN via add_script_tag(url=...)


def _require_axe_runtime(page):
    """Return loaded axe version or raise ScanUnavailable with actionable steps."""
    version = page.evaluate(
        "() => (typeof axe !== 'undefined' && axe && axe.version) "
        "? String(axe.version) : null"
    )
    if not version:
        raise ScanUnavailable(
            "axe-core failed to initialize after script injection. "
            "Set ACCESSDOC_AXE_PATH to a local axe.min.js for hermetic scans, "
            f"or ensure CDN access to {AXE_CDN}."
        )
    return version


# ---------------------------------------------------------------------------
# Public scan entry points
# ---------------------------------------------------------------------------

def run_scan(url, timeout_ms=30000, allow_private_network=False):
    """Run axe-core against `url` using Playwright; return the axe result dict.

    Raises :class:`UnsafeTargetError` if the URL (or any redirect target)
    violates the network boundary policy.
    Raises :class:`ScanUnavailable` if Playwright (and a browser) are not
    installed or the scan otherwise fails.
    """
    # Pre-navigation gate.
    validate_url(url, allow_private_network=allow_private_network)

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # ImportError or environment error
        raise ScanUnavailable(
            "Playwright is not installed. Install the scan extra:\n"
            "  pip install playwright && playwright install chromium"
        ) from exc

    axe_source = _load_axe_source()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # Intercept every outgoing request (navigations + sub-resources)
            # and abort any that target a denied host after re-resolution.
            def _route_handler(route):
                request = route.request
                req_url = request.url
                if not _check_request_host(req_url, allow_private_network):
                    try:
                        route.abort()
                    except Exception:
                        pass
                    return
                try:
                    route.continue_()
                except Exception:
                    pass

            page.route("**/*", _route_handler)

            page.goto(url, wait_until="load", timeout=timeout_ms)

            # Re-validate the final URL after any redirects the browser
            # followed at the navigation layer.
            final_url = page.url
            if final_url and final_url != url:
                validate_url(final_url, allow_private_network=allow_private_network)

            if axe_source:
                page.add_script_tag(content=axe_source)
            else:
                page.add_script_tag(url=AXE_CDN)
            axe_version = _require_axe_runtime(page)
            result = page.evaluate(
                "async () => { return await axe.run(document, "
                "{resultTypes:['violations','passes','incomplete']}); }"
            )
            browser.close()
    except UnsafeTargetError:
        raise
    except ScanUnavailable:
        raise
    except Exception as exc:
        raise ScanUnavailable(f"Scan failed for {url}: {exc}") from exc

    # Normalise into the axe JSON shape our parser expects.
    if "url" not in result:
        result["url"] = url
    if "testEngine" not in result:
        result["testEngine"] = {"name": "axe-core", "version": axe_version}
    return result


def run_scan_json(url, timeout_ms=30000, allow_private_network=False):
    """Convenience wrapper returning a JSON string."""
    return json.dumps(
        run_scan(url, timeout_ms, allow_private_network=allow_private_network)
    )
