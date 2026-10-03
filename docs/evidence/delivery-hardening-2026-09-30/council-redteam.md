# AccessDoc — independent read-only red-team release review

**Disposition: HOLD.** Reviewed HEAD `4270da84dc8f89a99b2e354a62c92543fe639edb` (`4270da8`). No evidence here establishes a passed exact-deployment release gate.

## Evidence and boundaries

- Existing `/data/accessdoc-turn4-final-live-gateway.json`: **11/12 successful model attempts**, not 11 failed attempts. Kimi is 2/3, with one HTTP 504 at **40,026.15 ms**; overall `verdict.exit_code` is **1**, `probes_only` is false. All three resilience probes are marked passed; this does not turn the model run into a pass.
- Exact deployment is **protected / 401**, as supplied by the requester. No fresh deployment probe was performed; no independently verified deployed identity or authenticated hosted pass is available from this review.
- Read the requested smoke script, both workflows, integrity tests and manual parser, plus narrowly related adapter, limit and verifier code/tests. No broad research, deployment, external HTTP, paid provider request, or private credential-file access.
- Local reproductions used synthetic inputs and loopback only. Credential-bearing environment was cleared for HTTP probes and test suites. Python bytecode writes were disabled. Initial and final `git status --short` were empty; no repository files were edited.
- Scoped regression results: `test_manual_csv_boundary.py`: **4/4 passed**; `test_release_validation_integrity.py`: **9/9 passed**. These are local tests, not a release certification. Full CI and paid/live gates were not rerun.

## Actionable findings (3)

### 1. Medium — GSA CI gate can accept a validator that exits nonzero

**Location:** `.github/workflows/ci.yml:30–37`, specifically the pipeline at line 35. Neither this job nor the step specifies an explicit shell or `set -o pipefail`.

**Why:** GitHub's implicit Linux bash shell uses `bash -e`, unlike explicitly selected bash's `-eo pipefail`. The pipeline's status therefore comes from `tee`, not the validator. The remaining checks accept output containing `Valid!` without `Invalid`, even if validation subsequently crashes or exits unsuccessfully. This is a demonstrated gate-logic false positive, not a claim that the real validator currently does this.

**Offline repro:** Replace the validator solely in an isolated shell simulation with a process that prints `Valid!` and exits 42, preserving the workflow's pipeline/grep logic:

```bash
# Run outside the repo; OUT is a temporary filename.
bash --noprofile --norc -e -c '
  { printf "Valid!\n"; exit 42; } 2>&1 | tee "$1"
  grep -q "Invalid" "$1" && { exit 1; }
  grep -q "Valid\!" "$1" || { exit 1; }
' bash "$OUT"
```

**Observed:** validator simulation exits **42**, gate exits **0**.

**Fix:** Set `shell: bash` explicitly or `set -euo pipefail`, and require the validator's success exit in addition to expected output. Add a regression for “prints Valid!, then fails.”

### 2. Low — “no exception leakage” smoke contract ignores JSON keys

**Location:** `scripts/production_smoke.py:30–51`, especially lines 41 and 48; used for all seven negative contracts at lines 343–346. Current leakage regressions at `tests/test_release_validation_integrity.py:53–56` test values only.

**Why:** The traversal starts with `payload.values()` and recursively visits dictionary values, never keys. A JSON error response can expose traceback text, source paths, or exception descriptions in a key while the leakage gate reports success.

**Offline repro:**

```python
import json
from scripts.production_smoke import error_response_matches
body = json.dumps({
    "error": "Invalid input",
    "diagnostics": {
        'Traceback (most recent call last): File "private.py"': "redacted"
    }
}).encode()
print(error_response_matches(422, body, 422))
```

**Observed:** **True**, despite decoded traceback/file text in the response. This demonstrates the checker weakness; no actual hosted response with this shape was observed.

**Fix:** Scan decoded dictionary keys as well as values at every depth. Add top-level and nested key-leak cases to the integrity tests. Consider an allowlisted public error schema rather than relying solely on three marker substrings.

### 3. Low — malformed manual `nodes` still exposes a raw Python exception in the local adapter

**Location:** `app/manual.py:52`; propagation at `app/main.py:284`. The hosted adapter's `api/handler.py:651–654` instead returns a generic message.

**Why:** `str.isdigit()` is true for some Unicode digits that `int()` cannot parse, such as superscript `²`. This raises an uncaught conversion `ValueError` outside the CSV syntax-error normalization at `app/manual.py:91–99`. The local adapter returns `str(e)` verbatim, echoing the offending cell and interpreter detail. This is not a demonstrated credential or server-secret leak, and the hosted adapter does not leak this exception.

**Loopback repro:** POST `/api/bundle`, JSON Content-Type, with:

```json
{"scanner_input":{"violations":[]},"manual_findings":"id,nodes\nx,²"}
```

Run with synthetic local auth disabled; no model/remediation route is involved.

**Observed:**

- `app.main`: **422**, `error.message = "invalid literal for int() with base 10: '²'"`.
- `api.handler`: **422**, `error = "Invalid axe-core data"`.
- PDF renderer was **not called** in either adapter.
- Direct list input `[{"id":"x","nodes":"²"}]` raises the same conversion error, so this is not CSV-only.

**Fix:** Define and validate a bounded nonnegative node-count representation, catch conversion failures and emit a stable generic validation error. Do not return arbitrary `ValueError` text from `app.main`. Extend the CSV boundary/adapter tests to cover Unicode digit conversion and large numeric strings.

## Authentication and resource checks: limits of the review

- Smoke bypass headers are injected at `scripts/production_smoke.py:95–98`; target restriction is at lines 9–20 and cross-origin redirects are rejected at lines 54–62. The synthetic cross-origin redirect regression passed. **No concrete bypass-header exfiltration was demonstrated**; this is not an exhaustive assurance about project ownership or all target configurations.
- The recent CSV implementation translates both oversized fields and malformed quoted cells to bounded errors, including header and ignored-column faults. Its four regression tests passed. The new finding is the later numeric conversion, not a regression in those CSV syntax/resource checks. No new resource-exhaustion exploit was established.
- The CI hostile-fixture shell loop accepts arbitrary nonzero exits, but `tests/test_hostile_fixtures.py` separately asserts exact exit codes for eight fixtures and is collected by CI's pytest step. This mitigates treating that shell weakness as a standalone whole-CI bypass; it is not counted as a fourth finding.

## Release decision

**Keep HOLD.** Fix and regression-test the three issues above, obtain an authorized smoke report proving the complete target SHA on the exact deployment, and obtain a passing live gateway verdict under the agreed latency/error criteria. Local regression successes and static inspection cannot override the supplied live failure or protected-deployment evidence.
