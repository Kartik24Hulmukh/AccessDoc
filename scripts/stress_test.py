#!/usr/bin/env python3
"""Adversarial stress test for AccessDoc v0.6.0-beta.1.

Throws malformed, hostile, and edge-case inputs at the pipeline to catch
crashes, injections, and silent data corruption. Exit code is non-zero if any
check FAILS, so it can gate CI. Helpers are defined before use.
"""
import io
import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.service import build_artifacts
from app.bundle import build_bundle, validate_bundle

RESULTS = []


def _record(status, name, detail=""):
    RESULTS.append((status, name, detail))


def expect_ok(name, fn):
    try:
        fn()
        _record("PASS", name)
    except Exception as exc:
        _record("FAIL", name, f"{type(exc).__name__}: {exc}")


def expect_raise(name, fn, exc_types=(ValueError,)):
    try:
        fn()
    except exc_types:
        _record("PASS", name)
    except Exception as exc:
        _record("FAIL", name, f"raised {type(exc).__name__}, wanted {exc_types}: {exc}")
    else:
        _record("FAIL", name, "expected an exception but none was raised")


def axe_ok(url="https://x.com", violations=None):
    return json.dumps({
        "url": url,
        "testEngine": {"name": "axe-core", "version": "4.11.2"},
        "violations": violations or [],
    })


# ---- 1. Malformed / hostile input ----
expect_raise("empty scanner_input string -> ValueError",
             lambda: build_artifacts({"scanner_input": ""}))
expect_raise("missing scanner_input -> ValueError",
             lambda: build_artifacts({}))
expect_raise("garbage json -> raises cleanly",
             lambda: build_artifacts({"scanner_input": "{not valid json"}))
expect_raise("non-object json (list) -> ValueError",
             lambda: build_artifacts({"scanner_input": "[1,2,3]"}))
expect_ok("violations=null -> tolerated (no crash)",
          lambda: build_artifacts({"scanner_input": json.dumps({"violations": None})}))


# ---- 2. Injection payloads ----
def _xss_client():
    arts = build_artifacts({"scanner_input": axe_ok(),
                            "client_name": "<script>alert(1)</script>"})
    assert "<script>alert(1)</script>" not in arts.html_bytes.decode()
expect_ok("XSS in client_name -> HTML escaped", _xss_client)


def _xss_url():
    arts = build_artifacts({"scanner_input": axe_ok(url="x</p><script>x</script>")})
    assert "<script>x</script>" not in arts.html_bytes.decode()
expect_ok("XSS in url field -> HTML escaped", _xss_url)


def _xss_violation():
    arts = build_artifacts({"scanner_input": axe_ok(violations=[
        {"id": "<img src=x onerror=alert(1)>", "impact": "critical",
         "description": "<script>bad</script>", "helpUrl": "h", "nodes": [{}]}])})
    html = arts.html_bytes.decode()
    assert "<script>bad</script>" not in html
    assert "<img src=x onerror=alert(1)>" not in html
expect_ok("XSS in violation id/description -> HTML escaped", _xss_violation)


def _yaml_injection():
    import yaml
    arts = build_artifacts({"scanner_input": axe_ok(),
                            "client_name": 'evil"\ninjected_key: pwned'})
    doc = yaml.safe_load(arts.openacr_yaml)
    assert "injected_key" not in doc, "attacker added a top-level YAML key"
expect_ok("YAML injection in client_name -> OpenACR safe", _yaml_injection)


# ---- 3. Scale ----
def _load():
    viols = [{"id": f"rule-{i}", "impact": "minor", "description": "d" * 200,
              "helpUrl": "h", "nodes": [{}] * 3} for i in range(5000)]
    build_bundle(build_artifacts({"scanner_input": axe_ok(violations=viols)}))
expect_ok("5000 violations -> builds without crash", _load)


# ---- 4. Unicode / emoji ----
def _unicode():
    build_bundle(build_artifacts({
        "scanner_input": axe_ok(url="https://ex\u00e4mple.com/\u65e5\u672c",
            violations=[{"id": "image-alt", "impact": "critical",
                         "description": "caf\u00e9 \u2615 \u65e5\u672c\u8a9e \U0001f389",
                         "helpUrl": "h", "nodes": [{}]}]),
        "client_name": "\u00dcn\u00efc\u00f6d\u00e9 \u00c7\u00f6rp \u65e5\u672c \U0001f389"}))
expect_ok("unicode/emoji client + description -> builds", _unicode)


# ---- 5. Tamper detection ----
def _tamper():
    zip_bytes = build_bundle(build_artifacts({"scanner_input": axe_ok()}))
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zin, zipfile.ZipFile(buf, "w") as zout:
        for n in zin.namelist():
            data = zin.read(n)
            if n == "report.pdf":
                data += b"TAMPERED"
            zout.writestr(n, data)
    res = validate_bundle(buf.getvalue())
    assert res["valid"] is False, "tamper NOT detected by validate_bundle"
expect_ok("tamper report.pdf -> validate_bundle fails", _tamper)


# ---- 6. Impact edge cases ----
expect_ok("unknown impact 'catastrophic' -> no crash",
          lambda: build_artifacts({"scanner_input": axe_ok(violations=[
              {"id": "image-alt", "impact": "catastrophic", "description": "d",
               "helpUrl": "h", "nodes": [{}]}])}))
expect_ok("missing impact field -> no crash",
          lambda: build_artifacts({"scanner_input": axe_ok(violations=[
              {"id": "image-alt", "description": "d", "helpUrl": "h", "nodes": [{}]}])}))


# ---- 7. Determinism ----
def _determinism():
    body = {"scanner_input": axe_ok(violations=[
        {"id": "image-alt", "impact": "critical", "description": "d",
         "helpUrl": "h", "nodes": [{}]}]),
        "client_name": "C", "audit_date": "2026-07-24"}
    a1 = build_artifacts(body)
    a2 = build_artifacts(body)
    assert a1.receipt_json == a2.receipt_json, "receipts differ across runs"
    assert a1.openacr_yaml == a2.openacr_yaml, "openacr differs across runs"
    assert a1.html_bytes == a2.html_bytes, "html differs across runs"
expect_ok("determinism: receipt/openacr/html identical across runs", _determinism)


# ---- report ----
fails = [r for r in RESULTS if r[0] == "FAIL"]
print("=" * 60)
for status, name, detail in RESULTS:
    mark = "\u2713" if status == "PASS" else "\u2717"
    print(f"{mark} [{status}] {name}" + (f" -- {detail}" if detail else ""))
print("=" * 60)
print(f"{len(RESULTS)} checks run, {len(fails)} failures")
sys.exit(1 if fails else 0)
