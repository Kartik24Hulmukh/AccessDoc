# Round 2 main-handler admission fix — frozen handoff

## Scope / status
Implemented and frozen; ready for coordinating agent's combined full verification. No commit/push, deployment, provider traffic, dependency installs, or deadline/limit changes. Only repo edits owned here: `app/main.py` and NEW `tests/test_main_header_admission.py`. Other agents' reporter, API and OTLP files were not edited. Base HEAD at start: `3519ab7`.

## Small fix
Extracted one `_validate_body_headers(limit, require_json=False)` validator from `_read`; `_read` and pre-admission POST validation both reuse it. Media type, transfer/content encoding, exactly one integer positive Content-Length, and known oversize retain their existing rejection/status behavior. Pre-admission invocation is AFTER host, route, auth, origin, operator, READY and rate policies, BEFORE generation/remediation semaphore acquisition. Header-invalid requests return existing 422 JSON; known-oversize bodies keep bounded drain then existing 413 JSON. Disconnect handling is retained without active-generation increments or releases for unacquired permits.

**Preserved:** production absolute body budget 15 seconds; drain cap 16 MiB; streaming chunks 64 KiB; connection semaphore; close-on-POST, request IDs/security headers; overload 503 + Retry-After; existing valid-upload read/JSON parse inside the generation pool. Valid bodies are NOT pre-read/buffered outside capacity. Valid-header checks run again inside `_read`, which retains the original accepted-body deadline initiation after admission.

## Frozen before-failure evidence
`/data/accessdoc-round2-admission-baseline.log` ran the new initial four tests BEFORE touching main.py: **2 root tests failed (8 additional failing header subtests), 2 passed, 6 subtests passed, 0.95s** (pytest prints `10 failed`). Deterministic receipt: two no-body oversized sockets entered actual drains; active generations=2, admission calls=2, healthy request=503; offenders=413/413; accepted/released=2/2; zero unhandled handler errors. Baseline has not been overwritten. Earlier independent edgeprobe receipts also corroborate this schedule; no fresh broad benchmark/research was performed.

## Final focused verification — PASS
`/data/accessdoc-round2-admission-frozen-focused.log`: **52 passed + 38 subtests passed, 8.64s**. Previous focused pass was 52 + 38 in 9.20s before the explicit drain-completion assertion; earlier 51 + 38 pass before adding the drain-cap regression.

Files: new dedicated regression, existing main generate/health, rate-limit Retry-After, both-adapter body deadlines, hosted framing/boundary, operational controls, zero-spend pilot contract.

New five-test coverage:
1. Two actual no-body oversized uploads synchronize on observed `_drain` entry. Healthy real `/api/bundle` response is **200 with a valid ZIP BEFORE either offender is half-closed**. Explicit temporal check: **0 drains completed when the healthy response was received**. Only then clients half-close writes to finish the bounded reads; both receive **413**, unchanged error code/connection-close/request-ID contract. Active during drains=0, admission calls during drains=0; exactly one accepted/released generation (healthy request). Connection permits balanced; no unhandled handler errors, zero errors_total; all generation slots reacquirable.
2. Eight header-invalid cases at an already saturated generation pool return 422, not 503, with **zero admission calls**: wrong media, Transfer-Encoding, Content-Encoding, missing/duplicate/malformed/zero/negative length.
3. Host, auth-unconfigured, origin, operator-disabled, READY and rate denials take precedence over invalid/oversize headers with **zero drains/admission calls**.
4. `_read` shared-validator oversized path retains exactly 16 MiB cap, 64 KiB chunks, one unchanged absolute deadline and `collect=False`.
5. Valid no-body uploads still acquire both generation slots before `_read_json`; a third healthy request correctly receives 503 until those admitted bodies arrive. Their invalid `{}` payloads receive 422, capacity releases, then healthy bundle=200. This protects against prereading every valid body outside capacity.

## Test environment / one diagnosed intermediate result
Used existing `/data/accessdoc-venv/bin/python -B`, `env -i`, disabled pytest cache, no bytecode writes, and an explicit socket guard rejecting all non-loopback connects (`/data/accessdoc-round2-admission-tests-run.py`). Dedicated fixtures explicitly retain 15s body/socket defaults, default two-generation pool and 16 connection slots; no production limit edits.

One intermediate combined ordering produced five 429 failures in older generate-endpoint tests: preceding existing boundary/deadline tests leave RATE entries, while generate-endpoint tests do not isolate RATE and restore the default 30/min limit. This is test-process ordering interference, not this header fix: run legacy generate tests FIRST, then the other files; no threshold change was made. Raw failed receipt retained at `/data/accessdoc-round2-admission-focused.log`; ordered and final successful receipts remain separate. No full-suite or cross-platform claim is made here.

## Frozen delivery / command
Source/test copies, scoped main patch and SHA-256 manifest: `/data/accessdoc-round2-admission-frozen/`. No further edits from this agent after freezing. Lead should compare manifest hashes before combined verification and review only these owned files.

```
env -i PATH=/usr/bin:/bin HOME=/data PYTHONDONTWRITEBYTECODE=1 \
 /data/accessdoc-venv/bin/python -B /data/accessdoc-round2-admission-tests-run.py \
 tests/test_app_main_generate_endpoint.py tests/test_app_main_health.py \
 tests/test_rate_limit_retry_after.py tests/test_main_header_admission.py \
 tests/test_http_body_deadlines.py tests/test_hosted_boundary.py \
 tests/test_operational_controls.py tests/test_zero_spend_pilot_contract.py
```

Remain HOLD pending combined full verification, actual owner/ops/trial gates and deployment authorization. Healthy-before-offender-release correctness is established locally; no broad throughput improvement, arbitrary OCR capability, production readiness, or launch GO is claimed.
