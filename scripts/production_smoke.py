"""Exact-commit hosted contract smoke; never substitutes for human release gates."""
import json
import re
import urllib.request
import urllib.error
from urllib.parse import urlsplit


def validate_target_url(url, bypass=False):
    target = urlsplit(url)
    local = target.hostname in ("127.0.0.1", "::1", "localhost")
    if (target.scheme not in ("https", "http") or not target.hostname or
            (target.scheme == "http" and not local) or target.username or
            target.password or target.query or target.fragment or
            target.path not in ("", "/")):
        raise ValueError("Smoke target must be a clean HTTPS origin or local HTTP origin")
    if bypass and (target.scheme != "https" or
            not (target.hostname == "access-doc.vercel.app" or re.fullmatch(
                r"access-[a-z0-9]+-atlas16\.vercel\.app", target.hostname))):
        raise ValueError("Automation bypass is restricted to the verified AccessDoc project")


def exact_commit_matches(observed, expected):
    return (isinstance(observed, str) and isinstance(expected, str)
            and re.fullmatch(r"[0-9a-fA-F]{40}", observed) is not None
            and re.fullmatch(r"[0-9a-fA-F]{40}", expected) is not None
            and observed.lower() == expected.lower())


def error_response_matches(status, body, expected):
    if status != expected or not body:
        return False
    try:
        payload = json.loads(body)
    except (ValueError, TypeError, RecursionError):
        return False
    if not isinstance(payload, dict) or not payload.get("error"):
        return False
    # Inspect decoded strings, not JSON escape sequences that can hide quotes
    # or Unicode characters in an exception traceback.
    stack = list(payload.values())
    while stack:
        value = stack.pop()
        if isinstance(value, str):
            if any(marker in value for marker in ("Traceback", "Exception", 'File "')):
                return False
        elif isinstance(value, dict):
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return True


class SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        def origin(url):
            p = urlsplit(url)
            return p.scheme, p.hostname, p.port or (443 if p.scheme == "https" else 80)
        if origin(req.full_url) != origin(newurl):
            raise urllib.error.HTTPError(req.full_url, code,
                                         "Cross-origin smoke redirect rejected", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def main(argv=None):
    import os, sys, time, io, zipfile, tempfile, subprocess, argparse

    BASE = os.environ["PRODUCTION_URL"].rstrip("/")
    validate_target_url(BASE, bool(os.getenv("VERCEL_AUTOMATION_BYPASS_SECRET")))
    EXPECTED = os.environ["EXPECTED_VERSION"]
    TARGET_COMMIT = os.environ.get("TARGET_COMMIT", "").strip()
    POLL_INTERVAL = float(os.getenv("SMOKE_POLL_INTERVAL_SECONDS", "15"))
    MAX_WAIT = float(os.getenv("SMOKE_MAX_WAIT_SECONDS", "900"))
    REQ_TIMEOUT = 30        # per-request timeout
    deadline = time.monotonic() + MAX_WAIT

    parser = argparse.ArgumentParser(description="Exact-SHA hosted smoke gate")
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[0-9a-fA-F]{40}", TARGET_COMMIT):
        raise SystemExit("TARGET_COMMIT must be a complete 40-character Git commit")
    checks_run = []
    failures = []
    error_responses = []
    def report(passed, phase="functional"):
        if args.output:
            from pathlib import Path
            Path(args.output).write_text(json.dumps({"pass": passed, "phase": phase,
                "expected_commit": TARGET_COMMIT, "observed_commit": last_observed_commit,
                "checks": checks_run, "failures": failures}, indent=2) + "\n")

    def req(method, path, body=None, headers=None, expect_status=None):
        """Make an HTTP request with a timeout. Returns (status, headers, body_bytes)."""
        url = BASE + path
        h = dict(headers or {})
        bypass = os.getenv("VERCEL_AUTOMATION_BYPASS_SECRET", "")
        if bypass:
            h["x-vercel-protection-bypass"] = bypass
        data = None
        if body is not None:
            if isinstance(body, (dict, list)):
                data = json.dumps(body).encode("utf-8")
                h.setdefault("Content-Type", "application/json")
            elif isinstance(body, bytes):
                data = body
            else:
                data = str(body).encode("utf-8")
        r = urllib.request.Request(url, data=data, headers=h, method=method)
        try:
            with urllib.request.build_opener(SameOriginRedirectHandler()).open(r, timeout=REQ_TIMEOUT) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, dict(e.headers), e.read()
        except Exception as e:
            return None, {}, str(e).encode("utf-8")

    # ----------------------------------------------------------------
    # Phase 1: Poll health endpoint until deployment is ready.
    # ----------------------------------------------------------------
    print(f"=== Waiting for Vercel deployment at {BASE} ===")
    print(f"    Expected version: {EXPECTED}")
    if TARGET_COMMIT:
        print(f"    Target commit: {TARGET_COMMIT[:7]}")
    print(f"    Poll interval: {POLL_INTERVAL}s, max wait: {MAX_WAIT}s, req timeout: {REQ_TIMEOUT}s")

    ready = False
    attempts = 0
    last_observed_commit = None
    while time.monotonic() < deadline:
        attempts += 1
        status, hdrs, body = req("GET", "/")
        if status == 200:
            try:
                data = json.loads(body)
                ver = data.get("adapter_version", "")
                svc_status = data.get("status", "")
                deployed_commit = data.get("commit", "")
                last_observed_commit = deployed_commit
                print(f"  Attempt {attempts}: status={status}, adapter_version={ver!r}, status_field={svc_status!r}, commit={deployed_commit!r}")
                commit_matches = exact_commit_matches(deployed_commit, TARGET_COMMIT)
                if svc_status == "ok" and commit_matches:
                    ready = True
                    break
            except Exception as e:
                print(f"  Attempt {attempts}: 200 but JSON parse failed: {e}")
        else:
            print(f"  Attempt {attempts}: status={status}")
            if status in (401, 403):
                failures.append("Deployment authorization required")
                report(False, "authorization")
                sys.exit(2)
        time.sleep(POLL_INTERVAL)

    if not ready:
        print(f"FAIL: Vercel deployment not ready after {MAX_WAIT}s ({attempts} attempts). Last observed commit: {last_observed_commit!r}")
        report(False, "readiness")
        sys.exit(1)

    print(f"=== Deployment ready after {attempts} attempts ===\n")

    # ----------------------------------------------------------------
    # Phase 2: Run all smoke checks.
    # ----------------------------------------------------------------

    def check(name, condition, detail=""):
        checks_run.append(name)
        tag = "PASS" if condition else "FAIL"
        print(f"  [{tag}] {name}" + (f" — {detail}" if detail else ""))
        if not condition:
            failures.append(name)

    # --- Check 1: GET / returns 200, adapter_version, status ok ---
    print("=== Check 1: GET / health endpoint ===")
    status, hdrs, body = req("GET", "/")
    health = json.loads(body) if status == 200 else {}
    check("GET / status 200", status == 200, f"got {status}")
    check("GET / adapter_version matches expected",
          health.get("adapter_version") == EXPECTED,
          f"got {health.get('adapter_version')!r}, expected {EXPECTED!r}")
    check("GET / status field is 'ok'", health.get("status") == "ok",
          f"got {health.get('status')!r}")
    check("GET / matches exact target commit", exact_commit_matches(health.get("commit"), TARGET_COMMIT))

    # --- Check 2: Valid POST / returns a ZIP ---
    print("\n=== Check 2: Valid POST / returns ZIP ===")
    with open("fixtures/axe-sample.json", "r", encoding="utf-8") as fixture:
        axe_fixture = fixture.read()
    payload = {
        "scanner_input": axe_fixture,
        "client_name": "Production Smoke",
        "audit_date": "2026-07-27",
    }
    status, hdrs, body = req("POST", "/", body=payload,
                             headers={"Content-Type": "application/json"})
    check("POST / status 200", status == 200, f"got {status}")
    ct = hdrs.get("Content-Type", "") or hdrs.get("content-type", "")
    check("POST / Content-Type is application/zip",
          "application/zip" in ct.lower(), f"got {ct!r}")
    is_zip = False
    zip_bytes = b""
    if body and len(body) > 4:
        is_zip = body[:4] == b"PK\x03\x04"
        zip_bytes = body
    check("POST / body is a ZIP (PK magic)", is_zip,
          f"first 4 bytes: {body[:4]!r}" if body else "empty body")
    check("POST / body non-empty", len(body) > 0, f"{len(body)} bytes")

    # --- Check 3: Returned ZIP passes AccessDoc validation ---
    print("\n=== Check 3: ZIP passes cli.py verify ===")
    if is_zip:
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as zf:
            zf.write(zip_bytes)
            zip_path = zf.name
        result = subprocess.run(
            [sys.executable, "cli.py", "verify", zip_path],
            capture_output=True, text=True, timeout=60
        )
        verify_output = result.stdout + result.stderr
        print(f"  cli.py verify exit code: {result.returncode}")
        print(f"  cli.py verify output: {verify_output.strip()[:500]}")
        try:
            verify_json = json.loads(result.stdout)
            verify_valid = verify_json.get("valid", False)
        except Exception:
            verify_valid = False
        check("cli.py verify exits 0", result.returncode == 0,
              f"exit {result.returncode}")
        check("cli.py verify reports valid=true", verify_valid,
              f"output: {verify_output.strip()[:200]}")
        os.unlink(zip_path)
    else:
        check("cli.py verify (skipped — no valid ZIP)", False,
              "no ZIP to verify")
        failures.append("cli.py verify — no valid ZIP")

    # --- Check 4: receipt.json schema fields ---
    print("\n=== Check 4: receipt.json schema fields ===")
    if is_zip:
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
                receipt = json.loads(z.read("receipt.json"))
                sv = receipt.get("schema_version", "")
                av = receipt.get("accessdoc_version", "")
                rule_ids = receipt.get("rule_ids")
                violations = receipt.get("violations")
                fpv = receipt.get("finding_fingerprint_version", "")
                print(f"  schema_version: {sv!r}")
                print(f"  accessdoc_version: {av!r}")
                print(f"  rule_ids: {rule_ids}")
                print(f"  violations count: {len(violations) if isinstance(violations, list) else 'N/A'}")
                print(f"  finding_fingerprint_version: {fpv!r}")

                check("receipt schema_version is '1.2'", sv == "1.2",
                      f"got {sv!r}")
                check("receipt schema_version is NOT '1.1'", sv != "1.1",
                      f"got {sv!r}")
                check("receipt accessdoc_version matches expected",
                      av == EXPECTED, f"got {av!r}, expected {EXPECTED!r}")
                check("receipt has rule_ids (list)", isinstance(rule_ids, list),
                      f"type={type(rule_ids).__name__}")
                check("receipt has violations (list)", isinstance(violations, list),
                      f"type={type(violations).__name__}")
                check("receipt finding_fingerprint_version is '1'",
                      str(fpv) == "1", f"got {fpv!r}")

                # Validate 64-character fingerprints
                bad_fps = []
                if isinstance(violations, list):
                    for v in violations:
                        fp = v.get("finding_fingerprint", "")
                        if not (isinstance(fp, str) and len(fp) == 64 and re.match(r'^[a-f0-9]{64}$', fp)):
                            bad_fps.append(fp)
                check("all finding_fingerprints are 64-char hex",
                      len(bad_fps) == 0,
                      f"{len(bad_fps)} bad fingerprints" +
                      (f": {bad_fps[:3]}" if bad_fps else ""))
        except Exception as e:
            check("receipt.json parsing", False, str(e))
            failures.append("receipt.json parsing")
    else:
        check("receipt.json checks (skipped — no ZIP)", False)
        failures.append("receipt.json — no ZIP")

    # --- Check 5: Malformed JSON returns 400 ---
    print("\n=== Check 5: Malformed JSON returns 400 ===")
    status, hdrs, body = req("POST", "/",
                             body=b"{ not valid json }",
                             headers={"Content-Type": "application/json"})
    check("Malformed JSON -> 400", status == 400, f"got {status}")
    error_responses.append(("Malformed JSON", status, body, 400))
    resp_text = body.decode("utf-8", errors="replace") if body else ""
    check("Malformed JSON response has no exception text",
          "Traceback" not in resp_text and "Exception" not in resp_text,
          f"body: {resp_text[:200]}")

    # --- Check 6: Missing scanner_input returns 400 ---
    print("\n=== Check 6: Missing scanner_input returns 400 ===")
    status, hdrs, body = req("POST", "/",
                             body={"client_name": "test"},
                             headers={"Content-Type": "application/json"})
    check("Missing scanner_input -> 400", status == 400, f"got {status}")
    error_responses.append(("Missing scanner_input", status, body, 400))

    # --- Check 7: Wrong Content-Type returns 415 ---
    print("\n=== Check 7: Wrong Content-Type returns 415 ===")
    status, hdrs, body = req("POST", "/",
                             body=b'{"scanner_input":"{}"}',
                             headers={"Content-Type": "text/plain"})
    check("Wrong Content-Type -> 415", status == 415, f"got {status}")
    error_responses.append(("Wrong Content-Type", status, body, 415))

    # --- Check 8: Oversized request returns 413 ---
    print("\n=== Check 8: Oversized request returns 413 ===")
    # MAX_HTTP_BODY_BYTES is 2 MiB; send 3 MiB
    big_body = b'{"scanner_input":"' + b'x' * (3 * 1024 * 1024) + b'"}'
    status, hdrs, body = req("POST", "/",
                             body=big_body,
                             headers={"Content-Type": "application/json"})
    check("Oversized request -> 413", status == 413, f"got {status}")
    error_responses.append(("Oversized request", status, body, 413))

    # --- Check 9: Unsupported method returns 405 ---
    print("\n=== Check 9: Unsupported method returns 405 ===")
    status, hdrs, body = req("PUT", "/")
    check("PUT method -> 405", status == 405, f"got {status}")
    error_responses.append(("PUT method", status, body, 405))

    # --- Check 10: Unknown path returns 404 ---
    print("\n=== Check 10: Unknown path returns 404 ===")
    status, hdrs, body = req("GET", "/nonexistent")
    check("Unknown path -> 404", status == 404, f"got {status}")
    error_responses.append(("Unknown path", status, body, 404))

    # --- Check 11: status, JSON error, and leakage for every captured response ---
    print("\n=== Check 11: All seven error-response contracts ===")
    invalid_status, _, invalid_body = req("POST", "/",
        body={"scanner_input": "not_json_at_all"},
        headers={"Content-Type": "application/json"})
    check("Invalid scanner_input -> 400", invalid_status == 400, f"got {invalid_status}")
    error_responses.append(("invalid scanner_input", invalid_status, invalid_body, 400))
    check("All seven negative responses captured", len(error_responses) == 7)
    for name, status, body, expected_status in error_responses:
        check("Error contract: " + name,
              error_response_matches(status, body, expected_status),
              f"expected {expected_status}, got {status}")

    # --- Check H: hosted UI + developer docs are actually served ---
    # vercel.json routes every path into api/handler.py; before launch
    # turn 17 the report builder in public/ was dark in production.
    print("\n=== Check H: hosted UI, static assets, docs, OpenAPI ===")
    status_ui, hdrs_ui, body_ui = req("GET", "/", headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
    ui_ct = hdrs_ui.get("Content-Type", "")
    check("GET / with browser Accept serves HTML report builder",
          status_ui == 200 and ui_ct.startswith("text/html") and b'id="report-form"' in body_ui,
          f"status {status_ui}, content-type {ui_ct!r}")
    check("Hosted UI CSP forbids inline script",
          "script-src 'self'" in hdrs_ui.get("Content-Security-Policy", "") and "unsafe-inline" not in hdrs_ui.get("Content-Security-Policy", ""),
          hdrs_ui.get("Content-Security-Policy", ""))
    for asset, ct_prefix in (("/static/app.js", "text/javascript"), ("/static/app.css", "text/css"),
                             ("/sample/axe-sample.json", "application/json"), ("/docs", "text/html"),
                             ("/openapi.json", "application/json")):
        s_a, h_a, b_a = req("GET", asset)
        check(f"GET {asset} is 200 {ct_prefix}",
              s_a == 200 and h_a.get("Content-Type", "").startswith(ct_prefix) and len(b_a) > 0,
              f"status {s_a}, content-type {h_a.get('Content-Type')!r}, {len(b_a)} bytes")
    s_o, h_o, b_o = req("GET", "/openapi.json")
    try:
        spec = json.loads(b_o)
    except Exception:
        spec = {}
    check("OpenAPI info.version matches expected adapter version",
          spec.get("info", {}).get("version") == EXPECTED, f"got {spec.get('info', {}).get('version')!r}")
    s_t, h_t, b_t = req("GET", "/static/" + "%2e%2e" + "/api/handler.py")
    check("Static traversal attempt is 404 JSON", s_t == 404 and h_t.get("Content-Type", "").startswith("application/json"), f"status {s_t}")
    check("Permissions-Policy header present on JSON and HTML responses",
          "Permissions-Policy" in hdrs_ui and "Permissions-Policy" in h_o)

    # Recheck identity after functional checks; a mid-run rollback is not a pass.
    final_status, _, final_body = req("GET", "/healthz")
    try:
        final_health = json.loads(final_body)
    except (ValueError, TypeError):
        final_health = {}
    check("Exact target remains deployed after smoke",
          final_status == 200 and exact_commit_matches(final_health.get("commit"), TARGET_COMMIT))
    report(not failures)

    # ----------------------------------------------------------------
    # Summary
    # ----------------------------------------------------------------
    print(f"\n=== SMOKE TEST SUMMARY ===")
    print(f"  Total checks: {len(checks_run)}")
    print(f"  Passed: {len(checks_run) - len(failures)}")
    print(f"  Failures: {len(failures)}")
    if failures:
        print(f"  FAILED checks:")
        for f in failures:
            print(f"    - {f}")
        print(f"\n  RESULT: FAIL")
        sys.exit(1)
    else:
        print(f"\n  RESULT: PASS — all {len(checks_run)} smoke checks passed")
        sys.exit(0)

if __name__ == "__main__":
    main()
