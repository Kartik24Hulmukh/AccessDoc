# AccessDoc hardening receipt — 13 September 2026

## Decision

**Candidate for controlled practitioner OSS beta; NOT certified production-ready.**
Base inspected: `b75b41b4cabada2714508cadd03582b12efe7a1d`. Version remains
`0.7.0-beta.5`; this is a review branch, not a tagged release. All four files
in the two supplied archives were inspected. Independent shell/test processes
ran in parallel; no separate AI-agent service was available or simulated.

The attachment patch was not safe to apply blindly: it stopped on README
text drift, imported a nonexistent `BundleHandler`, indexed the `Artifacts`
dataclass as a dict, used a fingerprint different from receipt identities,
and introduced an axe `heading-order` failure. These were corrected and
new tests were executed, rather than accepting prior claims of completion.

## Implemented

- Count severity from emitted target instances, not input rule rows. Sample
  fixture now has critical 3, serious 6, moderate 0, minor 2, unknown 0 = 11
  details. Live baseline was 3 + 5 + 0 + 1 = 9 despite 11 details.
- Unknown/missing/null automated impact is explicit `unknown`, never silently
  `minor`. Manual merge preserves this count; receipt/PDF/HTML expose it.
- HTTP explicit `violations:null` matches parser/CLI empty-array compatibility;
  missing key still fails closed. Missing provenance is prominently warned.
- Instance HTML has target, description, canonical full SHA-256 receipt
  fingerprint, WCAG references, source, severity and safe HTTP(S) help link.
  Responsive semantic cards replace the lossy aggregate table. Measured
  horizontal reflow at 320px, not merely an axe audit at that viewport.
- Reject malformed description/help URL/target types, non-object pass and
  incomplete entries, non-object manual entries, malformed option types,
  and unsupported PDF engine. CSV/Markdown manual counts share list limits.
- Preserve identity for long targets using a bounded prefix plus SHA-256,
  avoiding collisions caused by plain 200-character truncation.
- HTTP exact media-type matching, nested JSON recursion rejection, resource
  limits mapped to 413. HTTP shared scanner validation explicitly disables
  the local-only oversized-input environment opt-out.
- Receipt validation rejects non-string rule IDs without crashing and rejects
  unused rule declarations even for an empty finding set.
- Correct procurement/legal claims and cold-start installation guidance;
  reconcile active STATE/COMPLETION metadata. Do not claim built-in rate
  limiting when deployment-level protection is still required.
- Add a local-only concurrency/contract gate to CI and archive its output;
  pin CI axe-core audit engine to 4.11.0.

## Verified evidence

| Gate | Observed result |
|---|---|
| Base suite | 580 tests, 11 skipped before browser dependencies installed |
| Final release suite | 600 tests, 599 passed, 1 skipped; 39.125 s |
| Skip | Existing live-production journey; no candidate deployment |
| Adversarial stress | 15/15 pass; includes 5,000-rule generation |
| Large fixture | 10,000-rule generation completed, about 4.5–4.7 s locally |
| Explicit self-audit | axe-core 4.11.0: zero violations in report and VPAT HTML |
| Reflow | Actual report document width <=320px in Chromium |
| Local HTTP load | 100/100 successful ZIP responses, 8 workers; every ZIP validates |
| Determinism under concurrency | One unique ZIP SHA-256 across all 100 responses |
| HTTP hostile-contract matrix | 9/9 expected statuses |
| 100x fixture expansion | 1 -> 100 target instances; count invariant preserved |
| CLI demo | Full sample bundle with SARIF/VPAT/EAA/enrichment verifies intact |
| Release verifier | All ten reported categories PASS |
| Dependency audit | No known vulnerabilities in resolved core runtime dependencies |

Load snapshot: **181.39 requests/s, p50 42.0ms, p95 56.3ms, max 61.7ms**.
This is a short loopback microbenchmark on a tiny synthetic fixture, not a
serverless deployment benchmark, sustained load test, SLO, or 100x capacity
claim. Public service received only one GET and two small POST baseline probes;
no public stress traffic was sent. Browser dependencies were installed rather
than leaving accessibility checks skipped. No independent assistive-technology
or PDF/UA certification was performed.

Raw evidence is in `docs/evidence/2026-09-13/`: load/contract JSON, live baseline,
core dependency audit, axe audit and release-gate status summary. Core runtime
resolved to reportlab 5.0.1, pillow 12.1.0, charset-normalizer 3.4.9 on Python
3.14.6. An audit of an unpinned resolution is not a dependency-lock guarantee.

### Reproduce

```sh
python -m pip install -r requirements-dev.txt playwright
python -m playwright install chromium
npm install --no-save --package-lock=false axe-core@4.11.0
python -m unittest discover -s tests -v
python scripts/stress_test.py
python scripts/self_audit.py
python scripts/hardening_load.py --output hardening-load.json
python scripts/verify_release.py
python cli.py bundle fixtures/axe-sample.json --out dist/bundle.zip --sarif --vpat --eaa --enrich --audit-date 2026-09-13
python cli.py verify dist/bundle.zip
```

## Compatibility cautions

`summary.unknown` is additive to schema 1.2. Consumers must include it in
count sums. Historical pre-fix receipts remain historical artifacts; do NOT
rewrite or re-sign them as if produced by this candidate. Corrected severity
counts and long-target identities can change trends versus those receipts;
review baseline changes explicitly. Missing impact now reports unknown.
HTML moved from a table to cards; consumers scraping table markup must adapt.
Strict validation rejects some formerly tolerated malformed payloads. Manual
unknown severity still follows the existing moderate-default policy; do not
interpret it as an independently verified severity assessment.

## Premortem / remaining launch gates

| Failure scenario | Required prevention and acceptance evidence | Suggested owner |
|---|---|---|
| Green local tests but old production code | Review PR/CI; deploy exact reviewed SHA to preview; verify health commit, sample counts, null contract and malformed corpus before promotion | Maintainer |
| Anonymous PDF endpoint exhausts spend | Gateway authentication/quotas, distributed rate limits, request and rendering timeouts, bounded concurrency/queue, spend alerts; authorized staging ramp/soak with CPU/RSS/p95/error-rate evidence and overload 429/503 | Platform owner |
| Evidence input mistaken for verified scan truth | Preserve provenance warnings and draft claims; manual+AT workflow and reviewer sign-off; never call unsigned bundles authenticated evidence | Accessibility lead |
| Hostile JSON accepted on another surface | Cross-surface CLI/API/MCP/Action fixture matrix in preview and required CI; extend fuzzing to cyclic in-process objects and manual-input normalization | Maintainer |
| Signing/compliance claims overreach | Verify exact artifact's Sigstore identity/issuer; independent OpenACR validator, PDF/UA only after veraPDF and human review | Release reviewer |
| Startup launches with no users | Five named practitioners, timed real handoffs; >=3/5 sendable with <=30min editing and at least two repeat-use commitments before broad promotion | Founder |
| Incident cannot be diagnosed or rolled back | Sanitized correlated error logs, monitoring and alert drill, last-good immutable deployment and tested rollback, retention/deletion policy | Platform owner |
| Credential leak | Revoke the PAT supplied in conversation after this operation; replace with least-privilege short-lived credentials stored in a secret manager | Account owner |

Still unverified: deployed candidate, authenticated hosted tenancy, platform
rate limits, sustained target load/RSS, container build/run in this environment,
upstream GSA validator in this run, signing workflow execution, human
accessibility/legal review, adoption, revenue, and product-market fit. Existing
CI has additional checks; local release-verifier PASS is not proof CI passed.
Do not merge or deploy solely on this document. A startup outcome cannot be
guaranteed by more automated loops.

## Founder execution, 13–16 September

1. **13th:** review this bounded change set; revoke exposed PAT after push;
   require CI. Stop feature sprawl and indefinite paid-agent loops.
2. **14th:** deploy reviewed SHA to preview, run target contracts and rollback
   drill. Keep public demo explicitly bounded; no production hosting claim.
3. **15–16th:** invite five accessibility practitioners to a controlled beta.
   Position as reproducible accessibility-evidence handoff, not automated
   compliance certification. Record time-to-sendable-report, edits required,
   repeated usage and willingness to pay; do not invent traction.
4. Broader launch only after gates above. Best next investment is reliable
   workflow completion for one agency segment, not speculative repo imports
   or adding dozens of formats. Commit receipts and one next blocker to the
   ledger after each loop, then stop when that gate is satisfied.
