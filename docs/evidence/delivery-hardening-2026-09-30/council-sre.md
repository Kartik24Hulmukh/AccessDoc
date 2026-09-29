# Independent SRE / architecture release review

**Target:** `4270da84dc8f89a99b2e354a62c92543fe639edb` (six commits `f931f20` through `4270da8`).
**Recommendation: HOLD public release / public uploads.** No concrete critical correctness regression introduced by these six commits was established in this scoped review. This is not a claim of exhaustive correctness or production readiness.

## Introduced critical findings

**None substantiated.** Inspected the six-commit diff, `app/http_body.py`, the changed ingestion/error paths in `app/main.py` and `api/handler.py`, CSV parsing, new regression tests, smoke script/workflow, and `docs/RELEASE_GATES.md`. Do not turn the live failure or missing deployment evidence into an invented code regression.

- Absolute body deadline: `app/http_body.py:32–47` recomputes the remaining wall-clock budget around each `read1`, bounds socket inactivity by that budget, and translates timeout. Both adapters close POST connections and release their admission slots in `finally` (`api/handler.py:539–571`, `app/main.py:234–297`). Local drip tests reproduced 408 at roughly 200 ms and subsequent 400/422 recovery; oversized-drain tests reproduced 413 under the same deadline.
- CSV faults: `app/manual.py:85–102` translates lazy CSV parser failures to bounded validation errors. Real HTTP regression tests verified 413/422, no private-cell echo, no renderer invocation on rejection, and subsequent 200 recovery.
- Smoke integrity: `scripts/production_smoke.py:9–27,54–62,149–152,379–387` restricts bypass targets, rejects cross-origin redirects, requires full commit identity, fails on protected deployment responses, and rechecks identity after functional checks. Relevant new integrity tests passed locally.

## Observed release blockers — not newly introduced correctness bugs

1. **Final live gateway gate failed.** Supplied `accessdoc-turn4-final-live-gateway.json`: `kimi-k3` succeeded 2/3 times; one attempt returned 504 after 40,026.15 ms; verdict exit code is 1. Resilience probes passed, but that does not erase the failed live gate. Cause and production frequency are unproven; three samples cannot establish reliability. Do not certify the complete canonical chain on this evidence.
2. **Exact deployed candidate remains unverified.** Deployment protected 401 is user-reported, not independently re-probed here. It is an authorization/evidence blocker, not proof the application is broken. Obtain an authorized exact-SHA functional smoke artifact for this candidate; do not bypass the gate by accepting 401 or substituting loopback results.
3. **Public release requires additional approval evidence.** `docs/RELEASE_GATES.md:3–20` requires hosted-CI repository evidence, practitioner validation, and named editorial/legal approval, and prohibits a public upload service until all tracks pass. The supplied verifier/load/chaos artifacts do not establish completion of those tracks. Missing evidence here is not a claim that approvals do not exist elsewhere.

## Verification and limits

- Supplied strict verifier: 900 passed, 1 skipped, ten checks PASS. Supplied load and chaos artifacts pass within their explicitly loopback/synthetic scope; not production capacity certification. Supplied before/after upload artifacts support the deadline repair.
- Independently ran 6 deadline/CSV tests and 9 release-integrity tests using `PYTHONDONTWRITEBYTECODE=1 python -m unittest ... -q`; all 15 passed, including real loopback sockets and the shipped smoke script against a local fixture.
- Attempted targeted pytest with cache disabled; pytest is not installed in either checked system interpreter. Did not install dependencies or rerun the full suite; the 900-test result is supplied evidence, not my independent run.
- No repository changes, deployment, provider calls, private-path reads, or credential-result reads. Initial repository status was clean. Only this requested report was intentionally written outside the repository.

**Exit criteria:** resolve or explicitly narrow the failed live-chain release claim; obtain authorized exact-target smoke and hosted-CI/security artifacts; provide the required named approvals. Until then, retain experimental-beta positioning and do not open public uploads.
