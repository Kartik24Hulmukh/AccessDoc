# Runtime remediation — 6 October 2026

Verdict: source repairs locally validated; production HOLD. No main merge, commercial launch, paid provider traffic, billing or deployment-protection changes. Private email/Authy sign-in succeeded, allowing actual protected-preview diagnosis. This is not a human-release approval.

## Published baseline and live failure
Published3519ab7 exactly matched prior local tree. Both Linux full jobs, both Windows portability checks, PRmacOS,dependency/lint/evidence/secret checks passed; PUSHmacOS failed test_native_finalizer_is_not_recancelled_by_retirement_drains. Prior source passed1261tests/510subtests locally but did not establish hosted acceptance.

Vercel candidate dpl_HJvziLLzwTJ9eYJqgDTomkkgcG2H on access-58u4jtzzs-atlas16.vercel.app was READY at3519ab7, yet our authenticated-browser GET returned500 FUNCTION_INVOCATION_FAILED. Scoped invocation logs identify missing request_id in _send_static: Vercel replaces handle_one_request and dispatches directly, bypassing our initialization. READY metadata was therefore not functional acceptance. Redacted causal traceback retained; no credentials or private document content published.

## Causal repairs and independent review
- Actual method-boundary reentrant request scope now owns initialization and completion if runtime replaces parsing. Stdlib outer parser envelope still handles malformed/unsupported requests and idle EOF. Nested HEAD-to-GET does not duplicate counters,logs or SERVER spans. GET/static/metrics/POST/auth/errors/OPTIONS and both runtime dispatch shapes tested with actual sockets and Chromium.
- Independent review found a missed keepalive431 stale-trace inheritance case after the first combined green suite. Fixed parser400/414/431/505 by discarding untrusted headers/context; fully parsed unsupported501 preserves its current inbound parent. Old-fail/new-pass probe and regression retained; no credential disclosure was demonstrated. Exact-once accounting/teardown preserved.
- Supported small newline-bearing findings caused ReportLab LayoutError and500 on both adapters. Finding-table display-only line folding now generates valid ZIPs; canonical evidence untouched. Healthy PDF,receipt,attestation and whole ZIP match preserved original bytes. Six real HTTP500 cases fixed without new rejection/limits or global normalization.
- Header-invalid/known-oversize requests no longer consume generation permits while draining. Existing host/auth/origin/operator/READY/rate policy ordering remains. Drain15s/16MiB/connection bounds unchanged; valid body reads remain admitted. Real socket test proves healthy bundle200 while two offender drains are still pending,then413/413;no leaked permits/unhandled errors.
- Native finalizer test assumed its coroutine started within an80ms flush. Controlled90ms submit delay reproduced the exact failure with zero coroutine entries: correct production had retired cancellation-before-start. Explicit startup barrier now establishes the tested finalizer before unchanged flush(.08),cancelling.wait(.2),flush(.03),cleanup/inflight/no-recancel assertions. Separate callback-gated test proves legitimate no-finalizer cancellation path. No production native code or timer bound changed; exact test digest refreshed.

## Measured validation
First combined suite1278passed/549subtests/one deployed-target skip,109.72s was green but lacked the independently found parser case. Its receipt is preserved,not portrayed as sufficient. Corrected final source worktree:ALL10local release gates PASS,1280passed,567subtests,one actual deployed-target skip,three intentional duplicateZIPwarnings,109.83s. New parser regression existed unchanged during that run and was then tracked in its own semantic commit;14parser/sourceguard tests passed after tracking. Exact file hashes in manifest bind tested bytes. Evidence-only documentation follows source validation.

Scoped,overlapping reviews:59lifecycle/parser tests;71renderer/29subtests;52admission/38subtests;17native ownership +3order checks;40independentintegration/56subtests before parser repair. These are NOT added to full totals or human participant counts. Earlier default-interpreter import failures are retained separately;existing installed venv is the actual application test runtime. No Docker executable exists locally,no image build/scan/immutable rollback claimed.

Renderer's unchanged100worker200mixed gate passed:134x200/33x413/33x422,zero observed5xx/errors/retries,recovery≤8.72ms. P95=11732.59ms,not a speedup vs prior11530.81ms sample or a100xcapacity claim. Valid workload renders tens of thousands of finding instances;speculative LongTable optimization was rejected after overlapping/no-material-gain measurements.

## Next exact target and production boundaries
Source changes require fresh exact-head hosted checks and actual protected preview revalidation;old-head results do not transfer. Earlier preview remains a failed baseline,not a repaired target. Preview configuration was inspected without revealing values;an unsaved private-key form was closed without saving because Preview-only scope could not be reliably selected. No auth key,environment,billing or deployment protection was changed. Do not infer a configured private pilot from that inspection.

Actual account is Atlas Hobby. Current official Hobby documentation restricts it to non-commercial personal use,offers no Spend Management and only1hour runtime logs. No paid upgrade was authorized or performed. A commercial startup release requires an explicitly approved eligible target/terms/budget,not merely source merge or a READY preview. GHCR is a registry,not a host.

Issue96still needs private scoped credentials,exact-source authenticated smoke,actual fleet/edge/resource/spend/log/collector/alert/retention controls,sustained approved staging and immutable rollback. Issues97/98still need actual consenting practitioner/qualified accessibility/security/legal/release decisions. No AI council,synthetic persona,repository permission or green test supplies genuine human assent. No Axiom-Grid repository changed. Exposed chat credentials were not reused and should be rotated privately.

Existing aiohttp/c-ares,ReportLab/OpenACR,Playwright/axe,OTLP and verifier remain the justified tools from catalogue review. No speculative OCR/RAG/plugin integration needed for these demonstrated failures. Arbitrary-document OCR is not this product's supported boundary.

## Reproduce
Use the recorded existing Python3.13venv plus actual browser prerequisites:
```bash
python scripts/verify_release.py
python -m pytest tests/test_vercel_runtime_lifecycle.py tests/test_vercel_parser_rejection_lifecycle.py tests/test_reporter_table_linefold.py tests/test_main_header_admission.py tests/test_otlp_cleanup_ownership.py -q
```
Preserve all original deadlines,failures and assertion semantics. Live smoke must bind an observed exact deployment/source origin and never send credentials to arbitrary hosts or model workloads without approved spend scope.
