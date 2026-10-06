# AccessDoc: implemented PDF finding-table line folding

## Source freeze ready

Authorized fix implemented on aligned HEAD `3519ab789ea3e8fd7077078f07bda4332cfe1b85`. No commit, push, checkout, admission change, remote action, real secret use, provider call, or threshold change.

Only owned checkout changes:

- `app/reporter.py`: **15 insertions / 5 deletions**. `_table_display` applies the existing `safe_text` escaping/display bound, then folds LF and tab to spaces. Five existing finding-table display fields use it; description's existing 70-character display truncation remains. CR stripping remains `safe_text`'s original behavior, so CRLF no longer creates PDF cell lines. No canonical value is assigned or mutated.
- NEW `tests/test_reporter_table_linefold.py`: five dedicated tests, including actual ReportLab rendering, canonical preservation, healthy byte identity, pending-display isolation and real loopback HTTP requests through both adapters.

Frozen SHA-256:

```
app/reporter.py
5e6383f366a42adb9d56eacf985d6a27954642b3fffa15f6910ea8a38edaf892

tests/test_reporter_table_linefold.py
f9d76916873ab56cb5daa4164d07b5b985d01353ba1c7e951b56e2421ad2a910
```

Lead received the freeze-ready notification with these hashes. No further edits to owned source/test files after that message. Concurrent modifications subsequently observed in `api/handler.py`, `tests/test_otlp_cleanup_ownership.py`, and NEW `tests/test_vercel_runtime_lifecycle.py` belong to the lead/other worker and were neither edited nor reverted here. The dedicated two-adapter validation completed before those API lifecycle changes appeared; rerun the dedicated module in the lead's final integration gate after their changes freeze.

## Causal before → after evidence

Original audit files and failures remain untouched. Pre-edit reporter preserved as `/data/accessdoc-round2-reporter-before.py`, SHA-256 `9fc2ad80dee6423a25f913938fc4bfbcb23f855830f1a04480fcbf47a587bbca`.

Dedicated regression baseline on the unmodified reporter:

- A 600-character newline-bearing rule ID, a 70-newline description, and a mixed CRLF/tab/escaped-markup rule ID all failed actual PDF layout.
- The same three within-limit payloads each returned **HTTP 500 from both adapters**: six real-socket failures, not mocked status assertions. Subsequent ordinary healthy bundles succeeded, proving the failures were isolated layout defects rather than dead servers.
- Direct cell test failed `LayoutError`; direct service cases also failed `LayoutError`.
- Corrected baseline pytest summary: **10 failed, 4 passed, 2 subtests passed**, 0.66 s. This includes one ordinary test failure and nine failing subtest cases. The earlier initial test capture contained a fixture error (missing `AuditViolation.help_url`); that log is retained separately and is not used as causal renderer evidence. The corrected baseline has no such fixture error.

After the display-only fix:

- The same six real HTTP requests return **200**, ZIP content type, PDF magic and independently valid manifest/attestation bundle digests.
- Canonical rule IDs, descriptions, scanner objects and direct finding dataclasses remain unmodified. HTML contains the original safely escaped IDs/descriptions, while receipt serialization/fingerprints/counts match the parser + canonical receipt builder and a pre-render baseline. OpenACR bytes match that same baseline. The receipt schema does not store description: preservation is asserted in original objects and HTML, not invented receipt fields.
- The direct cell test covers every displayed field, including a hostile manual source label/WCAG cell; rendered table cells contain no LF, tab, CR or active markup. Global `safe_text` and pending display still retain their intentional LF/tab behavior; pending-only bundle bytes remain identical.
- Healthy sample test compares every payload and complete ZIP against the former `safe_text`-only table display, avoiding cross-version ReportLab golden-hash brittleness in CI.

## Independent healthy byte identity

A separate verification process imported the **preserved original reporter source**, generated the original healthy sample, then compared against the fixed reporter. All artifact payloads (including attestation), PDF, receipt and entire bundle were byte-identical. It additionally matched the historical healthy probe hashes:

```
PDF     cbf7f05df68e105320018d7086c6e7ee829a2eb33fa2abb7a6b355cfeae202b7
receipt 624f27591516c400a92c74852a0d2750e8d0465a625e6739d4394f31a4aa90b5
ZIP     7182240385ab860d1c3eca562dda9b2e99fd40dc8f672ef57d5064947f641a93
```

This local historical-hash assertion uses Python 3.13.14 / ReportLab 5.0.1; CI tests use same-runtime before/after equality rather than requiring those bytes across different ReportLab versions.

## Executed validation

Existing `/data/accessdoc-venv/bin/python`; empty inherited environment, `-B`/`PYTHONDONTWRITEBYTECODE=1`, pytest cache disabled, temporary files rooted under `/data`. Focused pytest runner blocked non-loopback socket connections.

**71 passed, 29 subtests passed, 9.51 s** across:

- NEW `test_reporter_table_linefold.py`
- `test_security.py`, `test_service.py`
- `test_concurrent_bench_retry_after.py`, `test_http_body_deadlines.py`, `test_rate_limit_retry_after.py`
- `test_reporter.py`, `test_pending_evidence.py`, `test_hosted_boundary.py`

Reporter diff whitespace check passed. No full-suite, deployed Vercel, or macOS CI verdict asserted.

## Original mixed-load contract retained

Original 100-worker / 200-request / seed-7 workload rerun with explicit 32 generation permits and 256 connection permits; output redirected into NEW `/data/accessdoc-round2-linefold-benchmark-*` files. No original audit results or repository `bench_results.json` overwritten. Same diagnostic stage instrumentation as the separate prior audit rerun, no changed acceptance conditions.

- **PASS**; histogram **134 × 200, 33 × 413, 33 × 422**.
- 0 unexpected 5xx, contract violations, transport errors, transport-attempt errors or admission retries.
- Fresh health/readiness/bundle recovery: all 200; **1.32 / 1.00 / 8.72 ms**, retaining the strict <200-ms gate.
- P95 **11,732.59 ms**; wall 16.59 s; RSS sampled ceiling 217.3 MiB.
- Request-level independent verification reproduced the 200-row histogram and original percentile convention.

This is a correctness fix, **not a measured throughput optimization**. Historical P95 11,530.81 ms and prior read-only instrumented P95 12,371.52 ms remain separate observations. Do not infer causal speedup from this one post-fix local run or claim 100x gains. Admission starvation discovered in the audit remains deliberately unchanged.

## Evidence files

All under `/data`:

- `accessdoc-round2-concurrency-review.md`: original read-only audit, unchanged.
- `accessdoc-round2-reporter-before.py`: pre-fix source.
- `accessdoc-round2-linefold-before-tests.log`: initial baseline including disclosed fixture error.
- `accessdoc-round2-linefold-before-corrected-tests.log`: causal pre-fix failures.
- `accessdoc-round2-linefold-tests-run.py`, `accessdoc-round2-linefold-fixed-tests.log`: protected focused runner and result.
- `accessdoc-round2-linefold-bytecheck.py`, `accessdoc-round2-linefold-bytecheck.json`: independent original-source/healthy-hash verification.
- `accessdoc-round2-linefold-bench-probe.py`, `accessdoc-round2-linefold-benchmark.log`, `accessdoc-round2-linefold-benchmark-{verdict,requests,phases}.json`: separate post-fix mixed-load evidence.
- `accessdoc-round2-linefold-verification.log`: mixed verdict/numeric cross-check.
- `accessdoc-round2-linefold-owned.patch`: portable patch containing **only the two owned files**; no staging or concurrent edits included.

**Next owner action:** integrate these two owned files, rerun the dedicated module with final lead-owned lifecycle changes, and publish only through the lead's existing release/source-digest process. Do not add admission work to this patch.
